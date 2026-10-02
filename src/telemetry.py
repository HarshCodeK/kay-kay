"""One row per request: provider, model, status, latency, tokens, cost.

This is the "observe" half of the project. Without it, the gateway is a proxy
that hides what it spent; with it, the dashboard shows where the money went.
"""
import datetime
import json
import sqlite3
import uuid

from src.config import DB_PATH, cost_usd


def _conn():
    return sqlite3.connect(DB_PATH)


def init():
    with _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS requests (
                   request_id TEXT PRIMARY KEY,
                   at TEXT,
                   key_id TEXT,
                   provider TEXT,
                   model TEXT,
                   status TEXT,
                   latency_ms REAL,
                   prompt_tokens INTEGER,
                   completion_tokens INTEGER,
                   cost_usd REAL,
                   error TEXT
               )"""
        )


def record(key_id, provider, model, status, latency_ms,
           prompt_tokens=0, completion_tokens=0, error=None):
    init()
    rid = "r_" + uuid.uuid4().hex[:12]
    with _conn() as c:
        c.execute(
            """INSERT INTO requests (request_id, at, key_id, provider, model,
                   status, latency_ms, prompt_tokens, completion_tokens, cost_usd, error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, datetime.datetime.now().isoformat(), key_id, provider, model,
             status, latency_ms, prompt_tokens, completion_tokens,
             cost_usd(model, prompt_tokens, completion_tokens), error),
        )
    return rid


def spend_for(key_id: str) -> float:
    """Total estimated spend by one key. Enforces the spend cap."""
    init()
    with _conn() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM requests WHERE key_id=? AND status='ok'",
            (key_id,),
        ).fetchone()
    return float(row[0])


def summary(key_id: str = None) -> dict:
    init()
    where = "WHERE key_id=?" if key_id else ""
    params = (key_id,) if key_id else ()
    with _conn() as c:
        totals = c.execute(
            f"""SELECT COUNT(*),
                       COALESCE(SUM(status='ok'),0),
                       COALESCE(SUM(cost_usd),0),
                       COALESCE(AVG(latency_ms),0),
                       COALESCE(SUM(prompt_tokens),0),
                       COALESCE(SUM(completion_tokens),0)
                FROM requests {where}""", params,
        ).fetchone()
        by_model = c.execute(
            f"""SELECT provider, model, COUNT(*), COALESCE(SUM(cost_usd),0)
                FROM requests {where} GROUP BY provider, model ORDER BY 3 DESC""", params,
        ).fetchall()
        recent = c.execute(
            f"""SELECT at, key_id, provider, model, status, latency_ms, cost_usd
                FROM requests {where} ORDER BY rowid DESC LIMIT 20""", params,
        ).fetchall()
    return {
        "total_requests": totals[0] or 0,
        "successful": totals[1] or 0,
        "failed": (totals[0] or 0) - (totals[1] or 0),
        "est_cost_usd": round(totals[2], 6),
        "avg_latency_ms": round(totals[3], 2),
        "total_tokens": (totals[4] or 0) + (totals[5] or 0),
        "by_model": [list(r) for r in by_model],
        "recent": [list(r) for r in recent],
    }
