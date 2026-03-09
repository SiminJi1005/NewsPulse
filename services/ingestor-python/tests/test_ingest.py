"""
Unit tests for app/ingest.py

Coverage:
  1. Normal success — lock acquired, articles fetched, sent to Kafka
  2. Lock held — skipped immediately, no Kafka call
  3. Lock released after success
  4. Lock released even when ingest raises (finally block)
  5. datetime converted to isoformat before Kafka send
  6. None published_at left unchanged
  7. Downstream Kafka failure propagates correctly
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from app.ingest import ingest_once


# ── helpers ──────────────────────────────────────────────────────────────────

def make_article(url="https://example.com/a", published_at=None):
    return {
        "source": "bbc",
        "title": "Test Article",
        "url": url,
        "summary": "A summary.",
        "published_at": published_at,
    }

def mock_redis(acquired=True):
    r = MagicMock()
    r.set.return_value = acquired
    return r


# ── 1. Normal success ─────────────────────────────────────────────────────────

@patch("app.ingest.fetch_rss")
@patch("app.ingest.KafkaProducer")
@patch("app.ingest.redis.Redis.from_url")
def test_ingest_success(mock_redis_cls, mock_producer_cls, mock_fetch):
    mock_redis_cls.return_value = mock_redis(acquired=True)
    mock_fetch.return_value = [make_article(url=f"https://ex.com/{i}") for i in range(3)]
    mock_producer = MagicMock()
    mock_producer_cls.return_value = mock_producer

    result = ingest_once()

    assert result == {"fetched": 3, "sent_to_kafka": 3}
    assert mock_producer.send.call_count == 3
    mock_producer.flush.assert_called_once()
    mock_producer.close.assert_called_once()


# ── 2. Lock held → skipped ────────────────────────────────────────────────────

@patch("app.ingest.fetch_rss")
@patch("app.ingest.KafkaProducer")
@patch("app.ingest.redis.Redis.from_url")
def test_ingest_duplicate_message_skipped_when_lock_held(mock_redis_cls, mock_producer_cls, mock_fetch):
    mock_redis_cls.return_value = mock_redis(acquired=False)

    result = ingest_once()

    assert result["skipped"] is True
    assert "lock held" in result["reason"]
    mock_fetch.assert_not_called()
    mock_producer_cls.assert_not_called()


# ── 3. Lock released after success ───────────────────────────────────────────

@patch("app.ingest.fetch_rss")
@patch("app.ingest.KafkaProducer")
@patch("app.ingest.redis.Redis.from_url")
def test_lock_released_after_ingest(mock_redis_cls, mock_producer_cls, mock_fetch):
    r = mock_redis(acquired=True)
    mock_redis_cls.return_value = r
    mock_fetch.return_value = [make_article()]
    mock_producer_cls.return_value = MagicMock()

    ingest_once()

    r.eval.assert_called_once()


# ── 4. Lock released even when ingest raises ──────────────────────────────────

@patch("app.ingest.fetch_rss")
@patch("app.ingest.KafkaProducer")
@patch("app.ingest.redis.Redis.from_url")
def test_ingest_downstream_failure_still_releases_lock(mock_redis_cls, mock_producer_cls, mock_fetch):
    r = mock_redis(acquired=True)
    mock_redis_cls.return_value = r
    mock_fetch.side_effect = RuntimeError("RSS feed down")
    mock_producer_cls.return_value = MagicMock()

    with pytest.raises(RuntimeError, match="RSS feed down"):
        ingest_once()

    # Lock must be released regardless
    r.eval.assert_called_once()


# ── 5. datetime → isoformat ───────────────────────────────────────────────────

@patch("app.ingest.fetch_rss")
@patch("app.ingest.KafkaProducer")
@patch("app.ingest.redis.Redis.from_url")
def test_datetime_converted_to_isoformat_before_kafka(mock_redis_cls, mock_producer_cls, mock_fetch):
    mock_redis_cls.return_value = mock_redis(acquired=True)
    dt = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    mock_fetch.return_value = [make_article(published_at=dt)]
    mock_producer = MagicMock()
    mock_producer_cls.return_value = mock_producer

    ingest_once()

    sent = mock_producer.send.call_args[1]["value"]
    assert isinstance(sent["published_at"], str)
    assert sent["published_at"] == "2025-01-15T12:00:00+00:00"


# ── 6. None published_at unchanged ───────────────────────────────────────────

@patch("app.ingest.fetch_rss")
@patch("app.ingest.KafkaProducer")
@patch("app.ingest.redis.Redis.from_url")
def test_none_published_at_left_unchanged(mock_redis_cls, mock_producer_cls, mock_fetch):
    mock_redis_cls.return_value = mock_redis(acquired=True)
    mock_fetch.return_value = [make_article(published_at=None)]
    mock_producer = MagicMock()
    mock_producer_cls.return_value = mock_producer

    ingest_once()

    sent = mock_producer.send.call_args[1]["value"]
    assert sent["published_at"] is None


# ── 7. Kafka producer failure ─────────────────────────────────────────────────

@patch("app.ingest.fetch_rss")
@patch("app.ingest.KafkaProducer")
@patch("app.ingest.redis.Redis.from_url")
def test_ingest_downstream_failure_when_kafka_raises(mock_redis_cls, mock_producer_cls, mock_fetch):
    mock_redis_cls.return_value = mock_redis(acquired=True)
    mock_fetch.return_value = [make_article()]
    mock_producer = MagicMock()
    mock_producer.send.side_effect = Exception("Kafka broker unavailable")
    mock_producer_cls.return_value = mock_producer

    with pytest.raises(Exception, match="Kafka broker unavailable"):
        ingest_once()
