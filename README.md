# NewsPulse

RSS news aggregation system with Kafka-based pipeline, full-text search, Redis caching, and auto-scheduling.

**Architecture:**
- **Python Ingestor (FastAPI, port 8001)** — fetches RSS feeds every 15 min (APScheduler), publishes raw articles to Kafka. Distributed lock via Redis prevents concurrent runs.
- **Kafka Pipeline** — decouples ingestion from storage via two topics: `raw-articles` → `deduplicated-articles`
- **dedup-consumer** — deduplicates by URL (Redis SET), forwards clean articles to `deduplicated-articles`
- **pg-writer** — consumes `deduplicated-articles`, writes to Postgres (idempotent: ON CONFLICT DO NOTHING)
- **es-writer** — consumes `deduplicated-articles`, indexes to Elasticsearch (idempotent: fixed doc ID)
- **Java API (Spring Boot 3, port 8080)** — search API with Redis cache-aside, trending queries via Redis Sorted Set
- **Web (static HTML)** — single-page search UI calling the Java API
- **Infrastructure (Docker)** — Postgres 16, Elasticsearch 8, Redis 7, Kafka 3.7 (KRaft)

```
Scheduler (15 min)
    ↓
[ingestor-python] ──→ raw-articles topic
                            ↓
                    [dedup-consumer] (dedup-group)
                     ├── duplicate → skip
                     └── new → deduplicated-articles topic
                                    ↓
                        ┌───────────┴───────────┐
                  [pg-writer]             [es-writer]
                  (pg-group)              (es-group)
                  Postgres                Elasticsearch

[api-java] ──→ Redis (cache / trending)
           ──→ Elasticsearch (search)
           ──→ Postgres (article detail)

web/index.html ──→ api-java :8080
```

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Docker Desktop | any | https://www.docker.com/products/docker-desktop |
| Python | 3.10+ | `brew install python` |
| Java | 17+ | `brew install openjdk@17` |
| Gradle | 8+ | `brew install gradle` |

---

## Step 1 — Configure Environment

`.env` is git-ignored and contains all connection strings. Values work out of the box for local Docker.

---

## Step 2 — Start Infrastructure + Kafka Pipeline

```bash
docker compose up -d kafka postgres elasticsearch redis dedup-consumer pg-writer es-writer
```

Wait ~30 seconds for Elasticsearch to be ready. Check:

```bash
curl http://localhost:9200/_cluster/health?pretty
# "status" should be "green" or "yellow"
```

---

## Step 3 — Start Python Ingestor (local)

```bash
cd services/ingestor-python
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
KAFKA_BOOTSTRAP=localhost:29092 REDIS_URL=redis://localhost:6379 python -m uvicorn app.main:app --port 8001
```

On startup the scheduler logs:
```
[scheduler] auto-ingest every 15 min
```

Articles are fetched automatically every 15 minutes. You can also trigger manually:

```bash
curl -X POST http://localhost:8001/ingest
# {"fetched": 45, "sent_to_kafka": 45}
```

Then watch the pipeline process articles:
```bash
docker compose logs -f dedup-consumer pg-writer es-writer
# [dedup] forwarded: https://...
# [pg-writer] upserted: https://...
# [es-writer] indexed: https://...
```

---

## Step 4 — Start Java Search API

In a new terminal:

```bash
cd services/api-java
gradle bootRun
```

> **First run:** Gradle downloads ~200 MB of dependencies. Subsequent runs are fast.

Verify:

```bash
curl http://localhost:8080/health
# {"status":"ok"}

curl "http://localhost:8080/search?q=AI&size=3"

curl http://localhost:8080/trending
# {"trending":[{"query":"ai","count":3},{"query":"startup","count":1}]}
```

---

## Step 5 — Open the Web UI

Open `web/index.html` directly in your browser (`open web/index.html` on macOS).

Type a keyword (e.g. `AI`, `startup`, `NASA`) and optionally filter by source (`bbc`, `techcrunch`, `hn`).

---

## API Reference

### Python Ingestor (port 8001)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/ingest` | Manually trigger RSS fetch → publish to Kafka |

### Java API (port 8080)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/search?q=...&source=...&from=0&size=10` | Full-text search (Redis cached, 60s TTL) |
| GET | `/articles/{id}` | Article detail from Postgres |
| GET | `/trending` | Top 10 search queries by volume |

**Search parameters:**

| Param | Required | Default | Example |
|-------|----------|---------|---------|
| `q` | yes | — | `AI startup` |
| `source` | no | all | `bbc` |
| `from` | no | `0` | `10` |
| `size` | no | `10` | `20` |

---

## Kafka Topics

| Topic | Producer | Consumer Group | Purpose |
|-------|----------|---------------|---------|
| `raw-articles` | ingestor | `dedup-group` | Raw RSS articles |
| `deduplicated-articles` | dedup-consumer | `pg-group`, `es-group` | Deduplicated articles ready for storage |
| `dead-letter-articles` | all consumers (v2) | TBD | Failed messages for inspection/replay |

---

## Verification Checklist

```
[ ] docker compose ps                          → all containers "running"
[ ] curl localhost:9200/_cluster/health        → "status":"yellow" or "green"
[ ] curl localhost:8001/health                 → {"status":"ok"}
[ ] curl -X POST localhost:8001/ingest         → {"fetched":N, "sent_to_kafka":N}
[ ] docker compose logs dedup-consumer         → [dedup] forwarded: ...
[ ] docker compose logs pg-writer              → [pg-writer] upserted: ...
[ ] docker compose logs es-writer              → [es-writer] indexed: ...
[ ] curl localhost:8080/health                 → {"status":"ok"}
[ ] curl "localhost:8080/search?q=AI"          → {"total":N, "results":[...]}
[ ] curl localhost:8080/trending               → {"trending":[...]}
[ ] open web/index.html                        → type keyword → articles appear
```

---

## Troubleshooting

**Elasticsearch won't start / health returns red**
```bash
docker compose logs elasticsearch
# On Mac with Docker Desktop: give Docker at least 4 GB RAM
# Docker Desktop → Settings → Resources
```

**Port already in use**
```bash
lsof -i :8080
kill -9 <PID>
```

**`curl -X POST /ingest` returns `{"skipped": true}`**
- Another ingest run is in progress (Redis distributed lock held).
- Wait a few seconds: `redis-cli get newspulse:lock:ingest`

**All articles are duplicates after first ingest**
- Expected behavior — Redis remembers seen URLs.
- To reset: `docker exec newspulse-redis-1 redis-cli DEL newspulse:seen_urls`

**pg-writer / es-writer show no logs**
- Ensure `PYTHONUNBUFFERED=1` is set in docker-compose (already configured).
- Check containers are running: `docker compose ps`

**Java fails to connect to Postgres or ES**
- Make sure Docker containers are running: `docker compose ps`

**`gradle bootRun` says "Gradle not found"**
```bash
brew install gradle
```

---

## Running Tests

### Python (pytest)

```bash
cd services/ingestor-python
source .venv/bin/activate
python -m pytest tests/ -v
```

| File | Coverage |
|------|----------|
| `test_ingest.py` | Lock acquired/skipped/released, datetime serialization, Kafka failure |
| `test_ingest_http.py` | POST 200, GET 405, lock-held skipped, downstream exception 500 |

### Java (JUnit + Mockito)

```bash
cd services/api-java
./gradlew test
```

| Test | Coverage |
|------|----------|
| `should_return_success_on_health` | /health returns 200 |
| `should_return_success_when_search_request_is_valid` | cache miss → query ES → 200 |
| `should_return_cached_result_without_calling_es_on_cache_hit` | cache hit → ES never called |
| `should_record_trending_before_cache_check` | trending recorded on every search |
| `should_return_400_when_q_param_is_missing` | missing `?q` → 400 |
| `should_return_5xx_when_es_throws_exception` | ES down → 500 |
| `should_return_success_when_article_exists` | /articles/{id} found → 200 |
| `should_return_404_when_article_not_found` | /articles/{id} missing → 404 |
| `should_return_success_with_trending_list` | /trending → 200 with list |

---

## Project Structure

```
NewsPulse/
├── .env                              # Local connection strings (git-ignored)
├── docker-compose.yml                # All infrastructure + consumer services
├── web/
│   └── index.html                    # Static search UI
└── services/
    ├── ingestor-python/              # RSS fetcher → Kafka producer
    │   ├── requirements.txt
    │   ├── app/
    │   │   ├── main.py               # FastAPI + APScheduler (15 min)
    │   │   ├── ingest.py             # Redis lock + KafkaProducer → raw-articles
    │   │   └── rss_fetcher.py        # feedparser (BBC, TechCrunch, HN)
    │   └── tests/
    │       ├── test_ingest.py        # Unit tests: lock, Kafka, datetime
    │       └── test_ingest_http.py   # HTTP tests: 200/405/500
    ├── consumer-python/              # Kafka consumers (3 independent processes)
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── app/
    │       ├── dedup.py              # dedup-group: URL dedup via Redis SET
    │       ├── pg_writer.py          # pg-group: write to Postgres (idempotent)
    │       └── es_writer.py          # es-group: index to Elasticsearch (idempotent)
    └── api-java/                     # Search API
        ├── build.gradle
        ├── settings.gradle
        └── src/
            ├── main/java/com/newspulse/api/
            │   ├── Application.java
            │   ├── ArticleEntity.java
            │   ├── ArticleRepository.java
            │   ├── ElasticSearchConfig.java
            │   ├── GlobalExceptionHandler.java  # 400/404/500 error handling
            │   └── ApiController.java           # /health /search /articles/{id} /trending
            └── test/java/com/newspulse/api/
                └── ApiControllerTest.java       # 9 tests: happy path, 4xx, 5xx
```
