"""Kay-Kay gateway — Chapter 1: Connect + Observe.

OpenAI-compatible gateway that fronts multiple LLM providers with
API-key auth, retry/fallback routing, and per-request telemetry.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("KAYKAY_DB", os.path.join(ROOT, "kaykay.db"))

# Gateway admin key: the key YOUR app presents to this gateway.
# Set via env var when running the server; generated at first boot if absent.
ADMIN_KEY_ENV = "KAYKAY_ADMIN_KEY"
ADMIN_KEY_FILE = os.path.join(ROOT, ".admin_key")

# Provider chain, in fallback order. Every provider is OpenAI-wire-compatible.
#   KAYKAY_PROVIDERS="groq,openai"
#   GROQ_API_KEY=...            (groq native)
#   OPENAI_BASE_URL=https://api.openai.com/v1   OPENAI_API_KEY=...   (any compatible endpoint)
PROVIDER_CHAIN = [p.strip() for p in os.environ.get("KAYKAY_PROVIDERS", "groq").split(",") if p.strip()]

# Rough USD per 1M tokens for cost estimates — transparent assumptions, not billing.
PRICE_TABLE_USD_PER_MTOK = {
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-4-scout-17b-16e-instruct": (0.11, 0.34),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "default": (0.50, 0.50),
}

# Retry policy
MAX_RETRIES = 2          # attempts per provider before falling to the next
TIMEOUT_S = 60


def get_admin_key() -> str:
    """Return (or create+persist) the gateway admin key."""
    env = os.environ.get(ADMIN_KEY_ENV)
    if env:
        return env
    if os.path.exists(ADMIN_KEY_FILE):
        return open(ADMIN_KEY_FILE).read().strip()
    import secrets
    key = "kk-" + secrets.token_urlsafe(24)
    with open(ADMIN_KEY_FILE, "w") as f:
        f.write(key)
    return key


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    ptok, ctok = PRICE_TABLE_USD_PER_MTOK.get(model, PRICE_TABLE_USD_PER_MTOK["default"])
    return (prompt_tokens * ptok + completion_tokens * ctok) / 1_000_000
