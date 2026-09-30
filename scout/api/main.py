import os

import psycopg
from fastapi import FastAPI

app = FastAPI(title="Scout")


@app.get("/health")
def health():
    try:
        with psycopg.connect(os.environ["READER_DATABASE_URL"], connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        db = "ok"
    except Exception as e:
        db = f"error: {type(e).__name__}"
    return {"status": "ok", "db": db}
