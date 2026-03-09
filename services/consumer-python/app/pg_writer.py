"""
pg-writer
  - reads from: deduplicated-articles  (group: pg-group)
  - writes to:  Postgres
  - idempotent: INSERT ... ON CONFLICT (url) DO NOTHING
"""
import os
import json
from datetime import datetime, timezone
from kafka import KafkaConsumer
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, func, UniqueConstraint

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
DB_URL          = os.getenv("DB_URL", "postgresql+psycopg2://newspulse:newspulse@localhost:5432/newspulse")

DEDUP_TOPIC = "deduplicated-articles"
GROUP_ID    = "pg-group"


class Base(DeclarativeBase):
    pass

class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("url", name="uq_articles_url"),)

    id:           Mapped[int]      = mapped_column(primary_key=True, autoincrement=True)
    source:       Mapped[str]      = mapped_column(String(64), nullable=False)
    title:        Mapped[str]      = mapped_column(Text, nullable=False)
    url:          Mapped[str]      = mapped_column(Text, nullable=False)
    summary:      Mapped[str]      = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def run():
    engine = create_engine(DB_URL, pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    consumer = KafkaConsumer(
        DEDUP_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=GROUP_ID,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )

    print(f"[pg-writer] listening on {DEDUP_TOPIC} ...")

    for msg in consumer:
        try:
            item = msg.value

            published_at = None
            if item.get("published_at"):
                published_at = datetime.fromisoformat(item["published_at"])

            with Session() as db:
                # Idempotent: ON CONFLICT DO NOTHING (url has unique constraint)
                db.execute(
                    text("""
                        INSERT INTO articles (source, title, url, summary, published_at)
                        VALUES (:source, :title, :url, :summary, :published_at)
                        ON CONFLICT (url) DO NOTHING
                    """),
                    {
                        "source":       item["source"],
                        "title":        item["title"],
                        "url":          item["url"],
                        "summary":      item.get("summary"),
                        "published_at": published_at,
                    }
                )
                db.commit()
            print(f"[pg-writer] upserted: {item['url']}")

        except Exception as e:
            # v1: log and skip — v2: send to dead-letter-articles
            print(f"[pg-writer] ERROR: {e}")


if __name__ == "__main__":
    run()
