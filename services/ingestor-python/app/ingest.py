import os
import uuid
import json
import redis
from kafka import KafkaProducer
from .rss_fetcher import fetch_rss

REDIS_URL       = os.getenv("REDIS_URL", "redis://localhost:6379")
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
RAW_TOPIC       = "raw-articles"

LOCK_KEY     = "newspulse:lock:ingest"
LOCK_TTL_MS  = 5 * 60 * 1000

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

def ingest_once(limit_per_feed=15):
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    lock_id = str(uuid.uuid4())

    acquired = r.set(LOCK_KEY, lock_id, nx=True, px=LOCK_TTL_MS)
    if not acquired:
        print("[ingest] another run in progress, skipping")
        return {"skipped": True, "reason": "lock held by another process"}

    try:
        return _run_ingest(limit_per_feed)
    finally:
        r.eval(_RELEASE_SCRIPT, 1, LOCK_KEY, lock_id)

def _run_ingest(limit_per_feed):
    rss_items = fetch_rss(limit_per_feed=limit_per_feed)

    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    for item in rss_items:
        if item.get("published_at") and hasattr(item["published_at"], "isoformat"):
            item["published_at"] = item["published_at"].isoformat()
        producer.send(RAW_TOPIC, value=item)

    producer.flush()
    producer.close()

    print(f"[ingest] sent {len(rss_items)} articles to {RAW_TOPIC}")
    return {"fetched": len(rss_items), "sent_to_kafka": len(rss_items)}