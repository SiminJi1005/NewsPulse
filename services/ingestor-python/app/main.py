from fastapi import FastAPI
from .ingest import ingest_once

app = FastAPI(title="News Pulse Python Ingestor")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/ingest")
def ingest():
    # manual trigger for MVP
    return ingest_once(limit_per_feed=15)