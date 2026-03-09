"""
HTTP-level tests for POST /ingest (FastAPI endpoint)

Uses FastAPI TestClient (httpx under the hood).
ingest_once() is always mocked — no real Redis/Kafka/RSS needed.

Coverage:
  1. POST /ingest success → 200 + expected fields
  2. GET /ingest → 405 Method Not Allowed
  3. Concurrent lock held → 200 with skipped flag (not an error)
  4. ingest_once raises → 500 Internal Server Error
"""
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ── 1. Normal success ─────────────────────────────────────────────────────────

@patch("app.main.ingest_once")
def test_post_ingest_success(mock_ingest):
    mock_ingest.return_value = {"fetched": 10, "sent_to_kafka": 10}

    resp = client.post("/ingest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["fetched"] == 10
    assert body["sent_to_kafka"] == 10
    mock_ingest.assert_called_once()


# ── 2. Wrong HTTP method → 405 ────────────────────────────────────────────────

def test_get_ingest_method_not_allowed():
    resp = client.get("/ingest")
    assert resp.status_code == 405


# ── 3. Lock held → 200 with skipped flag ─────────────────────────────────────

@patch("app.main.ingest_once")
def test_ingest_duplicate_locked_returns_skipped_not_error(mock_ingest):
    mock_ingest.return_value = {"skipped": True, "reason": "lock held by another process"}

    resp = client.post("/ingest")

    # Skipped is a normal outcome, not an HTTP error
    assert resp.status_code == 200
    body = resp.json()
    assert body["skipped"] is True
    assert "lock held" in body["reason"]


# ── 4. Downstream failure → 500 ───────────────────────────────────────────────

@patch("app.main.ingest_once")
def test_ingest_downstream_failure_returns_500(mock_ingest):
    mock_ingest.side_effect = Exception("Kafka broker unavailable")

    resp = client.post("/ingest")

    assert resp.status_code == 500
