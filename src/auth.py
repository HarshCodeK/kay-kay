"""API-key authentication for the gateway.

Keys live in SQLite as SHA-256 hashes; lookups use a constant-time compare.
The admin key (env or .admin_key file) is the bootstrap key your own
application uses to talk to the gateway.
"""
import hashlib
import hmac
import secrets
import sqlite3

from src.config import DB_PATH, get_admin_key


def _conn():
    return sqlite3.connect(DB_PATH)


def init_tables():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS api_keys (
            key_id TEXT PRIMARY KEY,
            name TEXT,
            key_hash TEXT UNIQUE,
            spend_cap_usd REAL DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        # Seed the admin key once, so `GET /v1/usage` works out of the box.
        admin = get_admin_key()
        h = hashlib.sha256(admin.encode()).hexdigest()
        c.execute("INSERT OR IGNORE INTO api_keys (key_id, name, key_hash) VALUES (?, ?, ?)",
                  ("admin", "admin (bootstrap)", h))


def issue_key(name: str, spend_cap_usd: float = 0) -> str:
    """Create a new gateway API key, return the plaintext once."""
    key = "kk-" + secrets.token_urlsafe(24)
    key_id = "k_" + secrets.token_hex(6)
    with _conn() as c:
        c.execute("INSERT INTO api_keys (key_id, name, key_hash, spend_cap_usd) VALUES (?, ?, ?, ?)",
                  (key_id, name, hashlib.sha256(key.encode()).hexdigest(), spend_cap_usd))
    return key


def list_keys() -> list[dict]:
    """List all keys (without hashes)."""
    with _conn() as c:
        rows = c.execute("SELECT key_id, name, spend_cap_usd, active, created_at FROM api_keys ORDER BY created_at DESC").fetchall()
    return [{"key_id": r[0], "name": r[1], "spend_cap_usd": r[2], "active": bool(r[3]), "created_at": r[4]} for r in rows]


def revoke_key(key_id: str) -> bool:
    """Soft-revoke a key (set active=0)."""
    with _conn() as c:
        c.execute("UPDATE api_keys SET active=0 WHERE key_id=?", (key_id,))
        return c.total_changes > 0


def get_key_spend_cap(key_id: str) -> float:
    """Return the spend cap for a key (0 = unlimited)."""
    with _conn() as c:
        row = c.execute("SELECT spend_cap_usd FROM api_keys WHERE key_id=?", (key_id,)).fetchone()
    return row[0] if row else 0.0


def check_key_active(key_id: str) -> bool:
    """Check if a key is still active."""
    with _conn() as c:
        row = c.execute("SELECT active FROM api_keys WHERE key_id=?", (key_id,)).fetchone()
    return bool(row[0]) if row else False


def verify_key(key: str) -> str | None:
    """Return key_id if valid, else None."""
    if not key:
        return None
    h = hashlib.sha256(key.encode()).hexdigest()
    with _conn() as c:
        row = c.execute("SELECT key_id FROM api_keys WHERE key_hash = ?", (h,)).fetchone()
    if row:
        return row[0]
    # constant-time guard even on miss (defeats trivial timing probes)
    hmac.compare_digest(h, h)
    return None


def authenticate(authorization_header: str | None) -> str | None:
    """Parse 'Authorization: Bearer <key>' and return key_id or None."""
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return None
    return verify_key(authorization_header[7:].strip())
