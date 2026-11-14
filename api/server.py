"""Tiny API for on-demand research on any NSE ticker.

  GET /api/research/{symbol}         cached result if fresh, else starts a job and returns its status
  GET /api/research/{symbol}?refresh=1
  GET /api/health

The app polls the same URL every ~2s while status == "running" and shows the stage text.
Precomputed demo companies are served straight from data/research/ (instant, no model calls).

Run locally:   uvicorn api.server:app --reload --port 8000
On Render:     see render.yaml
"""
from __future__ import annotations

import json
import re
import threading
from datetime import date, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from finn.llm import LLM, LLMUnavailable
from finn.research import RESEARCH_DIR, ResearchError, research, save

app = FastAPI(title="FINN research")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

FRESH_DAYS = 14
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
SYMBOL = re.compile(r"^[A-Z0-9&\-]{1,20}$")


def _cached(sym: str) -> dict | None:
    p = RESEARCH_DIR / f"{sym}.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    if date.fromisoformat(data.get("as_of", "1970-01-01")) < date.today() - timedelta(days=FRESH_DAYS):
        return None
    return data


def _run(sym: str) -> None:
    def progress(stage: str) -> None:
        JOBS[sym]["stage"] = stage
    try:
        data = research(sym, llm=LLM(max_calls=12), progress=progress)
        save(data)
        JOBS[sym] = {"status": "ready", "data": data}
    except (ResearchError, LLMUnavailable) as e:
        JOBS[sym] = {"status": "error", "error": str(e)}
    except Exception as e:  # surface, don't crash the worker
        JOBS[sym] = {"status": "error", "error": f"unexpected: {str(e)[:200]}"}


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/research/{symbol}")
def get_research(symbol: str, refresh: int = 0):
    sym = symbol.upper().strip()
    if not SYMBOL.match(sym):
        raise HTTPException(400, "not an NSE symbol")
    if not refresh:
        data = _cached(sym)
        if data:
            return {"status": "ready", "data": data}
    with LOCK:
        job = JOBS.get(sym)
        if job and job["status"] == "running":
            return job
        if job and job["status"] in ("ready", "error") and not refresh:
            out = dict(job)
            if job["status"] == "error":
                JOBS.pop(sym, None)  # let the next request retry
            return out
        JOBS[sym] = {"status": "running", "stage": "Starting"}
        threading.Thread(target=_run, args=(sym,), daemon=True).start()
    return JOBS[sym]
