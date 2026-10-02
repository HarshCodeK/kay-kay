"""One row per request: provider, model, status, latency, tokens, cost.

This is the "observe" half of the project. Without it, the gateway is a proxy
that hides what it spent; with it, the dashboard shows where the money went.
"""
import datetime
import json
import sqlite3
import time
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
        c.execute(
            """CREATE TABLE IF NOT EXISTS budget_reservations (
                   reservation_id TEXT PRIMARY KEY,
                   key_id TEXT NOT NULL,
                   amount_usd REAL NOT NULL,
                   expires_at REAL NOT NULL
               )"""
        )


def record(key_id, provider, model, status, latency_ms,
           prompt_tokens=0, completion_tokens=0, error=None, cost_override_usd=None):
    init()
    rid = "r_" + uuid.uuid4().hex[:12]
    with _conn() as c:
        c.execute(
            """INSERT INTO requests (request_id, at, key_id, provider, model,
                   status, latency_ms, prompt_tokens, completion_tokens, cost_usd, error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, datetime.datetime.now().isoformat(), key_id, provider, model,
             status, latency_ms, prompt_tokens, completion_tokens,
             cost_usd(model, prompt_tokens, completion_tokens)
             if cost_override_usd is None else float(cost_override_usd), error),
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


def reserve_budget(key_id: str, cap_usd: float, amount_usd: float, ttl_s: int = 300):
    """Atomically reserve worst-case request cost under a key's spend cap."""
    if cap_usd <= 0:
        return None
    amount_usd = max(float(amount_usd), 0.0)
    now = time.time()
    expires = now + ttl_s
    rid = "b_" + uuid.uuid4().hex
    init()
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("DELETE FROM budget_reservations WHERE expires_at <= ?", (now,))
        spent = c.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM requests WHERE key_id=? AND status='ok'",
            (key_id,),
        ).fetchone()[0] or 0.0
        reserved = c.execute(
            "SELECT COALESCE(SUM(amount_usd),0) FROM budget_reservations WHERE key_id=?",
            (key_id,),
        ).fetchone()[0] or 0.0
        if spent + reserved + amount_usd > cap_usd + 1e-12:
            return None
        c.execute(
            "INSERT INTO budget_reservations(reservation_id,key_id,amount_usd,expires_at) VALUES (?,?,?,?)",
            (rid, key_id, amount_usd, expires),
        )
    return rid


def release_budget(reservation_id: str | None):
    """Release one reservation; safe to call after success or failure."""
    if not reservation_id:
        return
    with _conn() as c:
        c.execute("DELETE FROM budget_reservations WHERE reservation_id=?", (reservation_id,))
