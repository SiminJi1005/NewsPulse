"""
es-writer
  - reads from: deduplicated-articles  (group: es-group)
  - writes to:  Elasticsearch
  - idempotent: fixed _id = hash(url), repeated index = overwrite
"""
import os
import json
import hashlib
from kafka import KafkaConsumer
from elasticsearch import Elasticsearch

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
ES_URL          = os.getenv("ES_URL", "http://localhost:9200")

DEDUP_TOPIC = "deduplicated-articles"
GROUP_ID    = "es-group"
INDEX_NAME  = "articles"


def get_es_client():
    return Elasticsearch(ES_URL)

def ensure_index(es: Elasticsearch):
    if not es.indices.exists(index=INDEX_NAME):
        es.indices.create(index=INDEX_NAME, body={
            "mappings": {
                "properties": {
                    "source":       {"type": "keyword"},
                    "title":        {"type": "text"},
                    "summary":      {"type": "text"},
                    "url":          {"type": "keyword"},
                    "published_at": {"type": "date"},
                    "created_at":   {"type": "date"},
                }
            }
        })


def url_to_doc_id(url: str) -> str:
    """Fixed document ID based on URL — ensures idempotent writes."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def run():
    es = get_es_client()
    ensure_index(es)

    consumer = KafkaConsumer(
        DEDUP_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=GROUP_ID,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )

    print(f"[es-writer] listening on {DEDUP_TOPIC} ...")

    for msg in consumer:
        try:
            item = msg.value
            doc_id = url_to_doc_id(item["url"])

            # Idempotent: same doc_id = overwrite, not duplicate
            es.index(index=INDEX_NAME, id=doc_id, document={
                "source":       item["source"],
                "title":        item["title"],
                "summary":      item.get("summary", ""),
                "url":          item["url"],
                "published_at": item.get("published_at"),
                "created_at":   item.get("created_at"),
            })
            print(f"[es-writer] indexed: {item['url']}")

        except Exception as e:
            # v1: log and skip — v2: send to dead-letter-articles
            print(f"[es-writer] ERROR: {e}")


if __name__ == "__main__":
    run()
