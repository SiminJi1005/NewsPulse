from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from .ingest import ingest_once

INGEST_INTERVAL_MINUTES = 15

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(ingest_once, "interval", minutes=INGEST_INTERVAL_MINUTES)
    scheduler.start()
    print(f"[scheduler] auto-ingest every {INGEST_INTERVAL_MINUTES} min")
    yield
    scheduler.shutdown()

app = FastAPI(title="News Pulse Python Ingestor", lifespan=lifespan)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/ingest")
def ingest():
    return ingest_once(limit_per_feed=15)