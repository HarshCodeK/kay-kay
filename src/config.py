"""Paths, provider chain, and the price table."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.models import MODELS  # noqa: E402  (after load_dotenv on purpose)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(env_var: str, default_name: str) -> str:
    """Absolutise a path and create its parent directory.

    Why: sqlite3.connect does not create intermediate directories and does not
    expand `~`, so a fresh checkout pointed at a new folder died at startup with
    "unable to open database file" -- a missing mkdir reported as a database fault.
    """
    raw = os.environ.get(env_var) or os.path.join(ROOT, default_name)
    resolved = os.path.abspath(os.path.expanduser(raw.strip()))
    parent = os.path.dirname(resolved)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return resolved


DB_PATH = _path("KAYKAY_DB", "kaykay.db")
ADMIN_KEY_ENV = "KAYKAY_ADMIN_KEY"
ADMIN_KEY_FILE = os.path.join(ROOT, ".admin_key")

PROVIDER_CHAIN = [
    p.strip() for p in os.environ.get("KAYKAY_PROVIDERS", "groq").split(",") if p.strip()
]

# Advertised on /v1/models. These ids are what a client sends back in the request
# body, and the gateway forwards that body verbatim -- so the advertised id must
# be exactly the id that resolves upstream. Verified 2026-10-02.
DEFAULT_MODELS = list(MODELS)

MAX_RETRIES = 2
TIMEOUT_S = 60

# USD per 1M tokens as (input, output). Keyed by model id so a price cannot
# silently apply to the wrong model. An unlisted model falls back rather than
# being priced at zero: a missing price must never make cost look better.
PRICE_TABLE = {mid: (meta[1], meta[2]) for mid, meta in MODELS.items()}
FALLBACK_PRICE = (0.80, 4.00)


def admin_key() -> str:
    """The bootstrap key your application presents to this gateway."""
    env = os.environ.get(ADMIN_KEY_ENV)
    if env:
        return env
    if os.path.exists(ADMIN_KEY_FILE):
        with open(ADMIN_KEY_FILE) as f:
            return f.read().strip()
    import secrets
    key = "kk-" + secrets.token_urlsafe(24)
    with open(ADMIN_KEY_FILE, "w") as f:
        f.write(key)
    return key


def cost_usd(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    pin, pout = PRICE_TABLE.get(model_id, FALLBACK_PRICE)
    return (prompt_tokens * pin + completion_tokens * pout) / 1_000_000
