from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from .db import SessionLocal, engine
from .models import Article, Base
from .rss_fetcher import fetch_rss
from .es_indexer import get_client, ensure_index, bulk_index

def init_db():
    Base.metadata.create_all(bind=engine)

def ingest_once(limit_per_feed=15):
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
                # duplicate url → skip
                continue

    bulk_index(es, indexed_docs)
    return {"fetched": len(rss_items), "inserted": inserted, "indexed": len(indexed_docs)}