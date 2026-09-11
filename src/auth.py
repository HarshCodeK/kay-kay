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
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        # Seed the admin key once, so `GET /v1/usage` works out of the box.
        admin = get_admin_key()
        h = hashlib.sha256(admin.encode()).hexdigest()
        c.execute("INSERT OR IGNORE INTO api_keys (key_id, name, key_hash) VALUES (?, ?, ?)",
                  ("admin", "admin (bootstrap)", h))


def issue_key(name: str) -> str:
    """Create a new gateway API key, return the plaintext once."""
    key = "kk-" + secrets.token_urlsafe(24)
    key_id = "k_" + secrets.token_hex(6)
    with _conn() as c:
        c.execute("INSERT INTO api_keys (key_id, name, key_hash) VALUES (?, ?, ?)",
                  (key_id, name, hashlib.sha256(key.encode()).hexdigest()))
    return key


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
