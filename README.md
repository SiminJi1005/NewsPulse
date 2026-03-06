# NewsPulse

RSS news aggregation system with full-text search, Redis caching, and auto-scheduling.

**Architecture:**
- **Python (FastAPI)** — fetches RSS feeds every 15 min (APScheduler), writes to Postgres, indexes to Elasticsearch. Distributed lock via Redis prevents concurrent runs.
- **Java (Spring Boot 3)** — search API with Redis cache-aside, trending queries via Redis Sorted Set, article detail from Postgres
- **Web (static HTML)** — single-page search UI calling the Java API
- **Infrastructure (Docker)** — Postgres 16, Elasticsearch 8, Redis 7

```
web/index.html  →  Java :8080  →  Redis :6379  (cache / trending)
                              →  Elasticsearch :9200
                              →  Postgres :5432

Python :8001    →  Redis :6379  (distributed lock)
                →  Postgres :5432
                →  Elasticsearch :9200
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

Copy the default env file (values work out of the box for local Docker):

```bash
cp .env .env.local   # optional — .env already has local defaults
```

`.env` is git-ignored and contains all connection strings. Edit it if your ports differ.

---

## Step 2 — Start Infrastructure

```bash
docker compose up -d
```

Wait ~30 seconds for Elasticsearch to be ready. Check:

```bash
curl http://localhost:9200/_cluster/health?pretty
# "status" should be "green" or "yellow"
```

---

## Step 3 — Start Python Ingestor

```bash
cd services/ingestor-python
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

On startup the scheduler logs:
```
[scheduler] auto-ingest every 15 min
```

Articles are fetched automatically every 15 minutes. You can also trigger manually:

```bash
curl -X POST http://localhost:8001/ingest
# {"fetched": 45, "inserted": 45, "indexed": 45}
# If another run is in progress: {"skipped": true, "reason": "lock held by another process"}
```

Duplicates are silently skipped — safe to run multiple times.

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
| POST | `/ingest` | Manually trigger RSS fetch → Postgres + Elasticsearch |

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

## Verification Checklist

```
[ ] docker compose ps                    → postgres, elasticsearch, redis all "running"
[ ] curl localhost:9200/_cluster/health  → "status":"yellow" or "green"
[ ] curl localhost:8001/health           → {"status":"ok"}
[ ] curl -X POST localhost:8001/ingest   → {"fetched":N, "inserted":N, "indexed":N}
[ ] curl localhost:8080/health           → {"status":"ok"}
[ ] curl "localhost:8080/search?q=AI"    → {"total":N, "results":[...]}
[ ] curl localhost:8080/trending         → {"trending":[...]}
[ ] redis-cli keys "newspulse:*"         → search cache + trending key visible
[ ] open web/index.html                  → type keyword → articles appear
```

---

## Troubleshooting

**Elasticsearch won't start / health returns red**
```bash
docker compose logs elasticsearch

# Common fix: increase vm.max_map_count (Linux only)
sudo sysctl -w vm.max_map_count=262144

# On Mac with Docker Desktop: give Docker at least 4 GB RAM
# Docker Desktop → Settings → Resources
```

**Port already in use**
```bash
lsof -i :8080
kill -9 <PID>
```

**`curl -X POST /ingest` returns `{"skipped": true}`**
- Another ingest run is in progress (scheduler or another manual trigger holds the Redis lock).
- Wait a few seconds and try again, or check: `redis-cli get newspulse:lock:ingest`

**`curl -X POST /ingest` returns 0 inserted**
- Already ingested — duplicates are skipped by URL uniqueness constraint.
- Reset: `docker compose down -v && docker compose up -d` (wipes volumes), then ingest again.

**Java fails to connect to Postgres or ES**
- Make sure Docker containers are running: `docker compose ps`
- Check `.env` for correct connection strings.

**`gradle bootRun` says "Gradle not found"**
```bash
brew install gradle
```

**Python `psycopg2` install fails on Apple Silicon**
```bash
brew install libpq
pip install psycopg2-binary
```

---

## Project Structure

```
NewsPulse/
├── .env                            # Local connection strings (git-ignored)
├── docker-compose.yml              # Postgres, Elasticsearch, Redis
├── web/
│   └── index.html                  # Static search UI
└── services/
    ├── ingestor-python/
    │   ├── requirements.txt
    │   └── app/
    │       ├── main.py             # FastAPI app + APScheduler (auto-ingest every 15 min)
    │       ├── ingest.py           # ingest_once() with Redis distributed lock
    │       ├── rss_fetcher.py      # feedparser → list of dicts (bbc, techcrunch, hn)
    │       ├── models.py           # SQLAlchemy Article model
    │       ├── db.py               # engine + SessionLocal
    │       ├── es_indexer.py       # ES client, index creation, bulk index
    │       └── dedup.py            # content-hash dedup utility
    └── api-java/
        ├── build.gradle
        ├── settings.gradle
        └── src/main/java/com/newspulse/api/
            ├── Application.java        # Spring Boot entry point
            ├── ArticleEntity.java      # JPA entity → articles table
            ├── ArticleRepository.java  # JPA repository
            ├── ElasticSearchConfig.java # ES client bean
            └── ApiController.java      # /health /search /articles/{id} /trending
```