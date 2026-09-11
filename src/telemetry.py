"""Per-request telemetry — the 'Observe' half of Chapter 1.

Every gateway call (success or failure) is persisted to SQLite with
provider, model, latency, token counts, and estimated cost.
"""
import sqlite3
import uuid
import datetime

from src.config import DB_PATH, estimate_cost_usd


def _conn():
    return sqlite3.connect(DB_PATH)


def init_tables():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS requests (
            request_id TEXT PRIMARY KEY,
            ts TEXT,
            key_id TEXT,
            provider TEXT,
            model TEXT,
            status TEXT,
            http_status INTEGER,
            latency_ms REAL,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            est_cost_usd REAL,
            error TEXT
        )""")


def log_request(key_id, provider, model, status, http_status, latency_ms,
                prompt_tokens, completion_tokens, error=None):
    rid = "r_" + uuid.uuid4().hex[:12]
    cost = estimate_cost_usd(model, prompt_tokens or 0, completion_tokens or 0)
    with _conn() as c:
        c.execute("""INSERT INTO requests
            (request_id, ts, key_id, provider, model, status, http_status,
             latency_ms, prompt_tokens, completion_tokens, est_cost_usd, error)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (rid, datetime.datetime.now().isoformat(), key_id, provider, model,
                   status, http_status, latency_ms, prompt_tokens, completion_tokens, cost, error))
    return rid


def usage_summary() -> dict:
    init_tables()  # idempotent; lets /v1/usage work before any traffic
    with _conn() as c:
        total = c.execute("""SELECT COUNT(*),
                SUM(status='ok'), COALESCE(SUM(est_cost_usd),0),
                COALESCE(AVG(latency_ms),0),
                COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0)
            FROM requests""").fetchone()
        by_model = c.execute("""SELECT provider, model, COUNT(*), COALESCE(SUM(est_cost_usd),0)
            FROM requests GROUP BY provider, model ORDER BY 3 DESC""").fetchall()
        recent = c.execute("""SELECT ts, key_id, provider, model, status, latency_ms, est_cost_usd
            FROM requests ORDER BY ts DESC LIMIT 20""").fetchall()
    return {
        "total_requests": total[0] or 0,
        "successful": total[1] or 0,
        "failed": (total[0] or 0) - (total[1] or 0),
        "est_cost_usd": round(total[2], 6),
        "avg_latency_ms": round(total[3], 2),
        "total_prompt_tokens": total[4] or 0,
        "total_completion_tokens": total[5] or 0,
        "by_model": [list(r) for r in by_model],
        "recent": [list(r) for r in recent],
    }
