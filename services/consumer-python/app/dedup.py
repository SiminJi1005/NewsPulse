"""
dedup-consumer
  - reads from: raw-articles       (group: dedup-group)
  - writes to:  deduplicated-articles
  - dedup strategy: Redis SET to track seen URLs
"""
import os
import json
import redis
from kafka import KafkaConsumer, KafkaProducer

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
REDIS_URL       = os.getenv("REDIS_URL", "redis://localhost:6379")

RAW_TOPIC   = "raw-articles"
DEDUP_TOPIC = "deduplicated-articles"
GROUP_ID    = "dedup-group"
SEEN_KEY    = "newspulse:seen_urls"


def run():
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

    consumer = KafkaConsumer(
        RAW_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=GROUP_ID,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )

    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    print(f"[dedup] listening on {RAW_TOPIC} ...")

    for msg in consumer:
        try:
            article = msg.value
            url = article.get("url")

            if not url:
                print(f"[dedup] missing url, skipping: {article}")
                continue

            # SADD returns 1 if new, 0 if already exists
            is_new = r.sadd(SEEN_KEY, url)
            if not is_new:
                print(f"[dedup] duplicate, skipping: {url}")
                continue

            producer.send(DEDUP_TOPIC, value=article)
            print(f"[dedup] forwarded: {url}")

        except Exception as e:
            # v1: log and skip — v2: send to dead-letter-articles
            print(f"[dedup] ERROR processing message: {e}")


if __name__ == "__main__":
    run()
