# NewsPulse

RSS news aggregation system with full-text search.

**Architecture:**
- **Python (FastAPI)** — fetches RSS feeds, writes to Postgres, indexes to Elasticsearch
- **Java (Spring Boot 3)** — search API backed by Elasticsearch, article detail API backed by Postgres
- **Web (static HTML)** — single-page search UI calling the Java API
- **Infrastructure (Docker)** — Postgres 16, Elasticsearch 8, Redis 7

```
web/index.html  →  Java :8080  →  Elasticsearch :9200
                              →  Postgres :5432
Python :8001    →  Postgres + Elasticsearch
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

## Step 1 — Start Infrastructure

```bash
docker compose up -d
```

Wait ~30 seconds for Elasticsearch to be ready. Check:

```bash
curl http://localhost:9200/_cluster/health?pretty
# "status" should be "green" or "yellow"
```

---

## Step 2 — Start Python Ingestor

```bash
cd services/ingestor-python
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

Verify:

```bash
curl http://localhost:8001/health
# {"status":"ok"}
```

---

## Step 3 — Ingest Articles

```bash
curl -X POST http://localhost:8001/ingest
# {"fetched": 45, "inserted": 45, "indexed": 45}
```

This fetches BBC, TechCrunch and Hacker News RSS feeds, writes them to Postgres (URL-deduped), and bulk-indexes them to Elasticsearch.

Run it multiple times safely — duplicates are silently skipped.

---

## Step 4 — Start Java Search API

In a new terminal:

```bash
cd services/api-java
gradle bootRun
```

> **First run:** Gradle downloads ~200 MB of dependencies. Subsequent runs are fast.
>
> **Prefer `./gradlew`?** Run `gradle wrapper` once in this directory to generate the wrapper scripts, then you can use `./gradlew bootRun`.

Verify:

```bash
curl http://localhost:8080/health
# {"status":"ok"}

curl "http://localhost:8080/search?q=AI&size=3"
```

---

## Step 5 — Open the Web UI

Open `web/index.html` directly in your browser (File → Open, or `open web/index.html` on macOS).

Type a keyword (e.g. `AI`, `startup`, `NASA`) and optionally filter by source (`bbc`, `techcrunch`, `hn`).

---

## API Reference

### Python Ingestor (port 8001)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/ingest` | Fetch RSS → Postgres + Elasticsearch |

### Java API (port 8080)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/search?q=...&source=...&from=0&size=10` | Full-text search via Elasticsearch |
| GET | `/articles/{id}` | Article detail from Postgres |

**Search parameters:**

| Param | Required | Default | Example |
|-------|----------|---------|---------|
| `q` | yes | — | `AI startup` |
| `source` | no | all | `bbc` |
| `from` | no | `0` | `10` |
| `size` | no | `10` | `20` |

---

## Verification Checklist

Run these in order. Each line shows the expected result.

```
[ ] docker compose ps               → postgres, elasticsearch, redis all "running"
[ ] curl localhost:9200/_cluster/health  → "status":"yellow" or "green"
[ ] curl localhost:8001/health      → {"status":"ok"}
[ ] curl -X POST localhost:8001/ingest   → {"fetched":N, "inserted":N, "indexed":N}  (N > 0)
[ ] curl localhost:8080/health      → {"status":"ok"}
[ ] curl "localhost:8080/search?q=AI"   → {"total":N, "results":[...]}  (results non-empty)
[ ] open web/index.html → type keyword → articles appear with title/source/date
```

---

## Troubleshooting

**Elasticsearch won't start / health returns red**
```bash
# Check logs
docker compose logs elasticsearch

# Common fix: increase vm.max_map_count (Linux only)
sudo sysctl -w vm.max_map_count=262144

# On Mac with Docker Desktop: give Docker at least 4 GB RAM
# Docker Desktop → Settings → Resources
```

**Port already in use**
```bash
# Find what's using a port (e.g. 8080)
lsof -i :8080
kill -9 <PID>
```

**`curl -X POST /ingest` returns 0 inserted**
- Already ingested — duplicates are skipped by URL uniqueness constraint.
- Reset: `docker compose down -v && docker compose up -d` (wipes volumes), then ingest again.

**Java fails to connect to Postgres or ES**
- Make sure Docker containers are running: `docker compose ps`
- The Java service connects to `localhost` — ensure ports 5432 and 9200 are not blocked.

**`gradle bootRun` says "Gradle not found"**
```bash
brew install gradle        # macOS
# or download from https://gradle.org/releases/
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
├── docker-compose.yml              # Postgres, Elasticsearch, Redis
├── web/
│   └── index.html                  # Static search UI
└── services/
    ├── ingestor-python/
    │   ├── requirements.txt
    │   └── app/
    │       ├── main.py             # FastAPI app, /health, /ingest
    │       ├── rss_fetcher.py      # feedparser → list of dicts
    │       ├── models.py           # SQLAlchemy Article model
    │       ├── db.py               # engine + SessionLocal
    │       ├── ingest.py           # orchestrates fetch → db → ES
    │       ├── es_indexer.py       # ES client, index creation, bulk index
    │       └── dedup.py            # content-hash dedup utility
    └── api-java/
        ├── settings.gradle
        ├── build.gradle
        └── src/main/java/com/newspulse/api/
            ├── Application.java        # Spring Boot entry point
            ├── ArticleEntity.java      # JPA entity → articles table
            ├── ArticleRepository.java  # JPA repository
            ├── ElasticSearchConfig.java # ES client bean
            └── ApiController.java      # /health, /search, /articles/{id}
```