import os
import uuid
import redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from .db import SessionLocal, engine
from .models import Article, Base
from .rss_fetcher import fetch_rss
from .es_indexer import get_client, ensure_index, bulk_index

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
LOCK_KEY  = "newspulse:lock:ingest"
LOCK_TTL_MS = 5 * 60 * 1000  # 5 minutes — longer than any expected run

# Lua script: atomic check-and-delete (only release if WE own the lock)
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

def init_db():
    Base.metadata.create_all(bind=engine)

def ingest_once(limit_per_feed=15):
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    lock_id = str(uuid.uuid4())

    # Try to acquire distributed lock
    acquired = r.set(LOCK_KEY, lock_id, nx=True, px=LOCK_TTL_MS)
    if not acquired:
        print("[ingest] another run in progress, skipping")
        return {"skipped": True, "reason": "lock held by another process"}

    try:
        return _run_ingest(limit_per_feed)
    finally:
        # Release lock atomically — only if we still own it
        r.eval(_RELEASE_SCRIPT, 1, LOCK_KEY, lock_id)

def _run_ingest(limit_per_feed):
    init_db()
    es = get_client()
    ensure_index(es)

    rss_items = fetch_rss(limit_per_feed=limit_per_feed)
    inserted = 0
    indexed_docs = []

    with SessionLocal() as db:
        for item in rss_items:
            a = Article(
                source=item["source"],
                title=item["title"],
                url=item["url"],
                summary=item.get("summary"),
                published_at=item.get("published_at"),
            )
            db.add(a)
            try:
                db.commit()
                db.refresh(a)
                inserted += 1

                indexed_docs.append({
                    "id": a.id,
                    "source": a.source,
                    "title": a.title,
                    "summary": a.summary or "",
                    "url": a.url,
                    "published_at": a.published_at.isoformat() if a.published_at else None,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                })
            except IntegrityError:
                db.rollback()
                continue

    bulk_index(es, indexed_docs)
    return {"fetched": len(rss_items), "inserted": inserted, "indexed": len(indexed_docs)}