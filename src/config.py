"""Kay-Kay gateway — Chapter 1: Connect + Observe.

OpenAI-compatible gateway that fronts multiple LLM providers with
API-key auth, retry/fallback routing, and per-request telemetry.

Why the price and model tables changed
--------------------------------------
They listed two models Groq retired on 2026-07-17 (`llama-3.3-70b-versatile`
and `llama-4-scout-17b-16e-instruct`), and those were also the only two ids
`/v1/models` advertised. A client that connected and auto-discovered models was
told about two models that both return 404 — the gateway was unusable through
its own discovery endpoint.

Prices are now keyed to live models, and `DEFAULT_MODELS` is what the gateway
advertises. Verified against https://console.groq.com/docs/models on 2026-10-02.
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("KAYKAY_DB", os.path.join(ROOT, "kaykay.db"))

# Gateway admin key: the key YOUR app presents to this gateway.
# Set via env var when running the server; generated at first boot if absent.
ADMIN_KEY_ENV = "KAYKAY_ADMIN_KEY"
ADMIN_KEY_FILE = os.path.join(ROOT, ".admin_key")

# Provider chain, in fallback order. Every provider is OpenAI-wire-compatible.
#   KAYKAY_PROVIDERS="groq,openai"
#   GROQ_API_KEY=...            (groq native)
#   OPENAI_BASE_URL=https://api.openai.com/v1   OPENAI_API_KEY=...
PROVIDER_CHAIN = [p.strip() for p in os.environ.get("KAYKAY_PROVIDERS", "groq").split(",") if p.strip()]

# Model ids advertised on /v1/models. Live on Groq's developer tier as of
# 2026-10-02. The gateway forwards whatever id the client sends; this list is
# for clients that want discovery instead of a hardcoded model.
DEFAULT_MODELS = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

# Rough USD per 1M tokens for cost estimates — transparent assumptions, not
# billing. Keyed by model id so a price cannot silently apply to the wrong
# model: the old table's `default` row mis-priced every unlisted model.
PRICE_TABLE_USD_PER_MTOK = {
    "qwen/qwen3.8-27b":   (0.80, 4.00),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b":  (0.075, 0.30),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}
FALLBACK_PRICE = (0.50, 0.50)  # only for a model genuinely absent from the table

# Retry policy
MAX_RETRIES = 2          # attempts per provider before falling to the next
TIMEOUT_S = 60


def get_admin_key() -> str:
    """Return (or create+persist) the gateway admin key."""
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


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    ptok, ctok = PRICE_TABLE_USD_PER_MTOK.get(model, FALLBACK_PRICE)
    return (prompt_tokens * ptok + completion_tokens * ctok) / 1_000_000


def is_priced(model: str) -> bool:
    """False when the cost figure is a fallback, not a real price."""
    return model in PRICE_TABLE_USD_PER_MTOK


def advertised_models() -> list:
    """(id, owned_by) pairs for /v1/models, in OpenAI's response shape.

    Why the id is the FULL model id, not a stripped prefix: OpenAI SDKs send
    whatever id they are given straight back in the request body, and this
    gateway forwards that body verbatim. If we advertised `openai` as an id,
    a client would send `{"model": "openai"}` upstream and get a 404 — and two
    models would advertise the same id, which is worse than useless for
    discovery. So the id here must be exactly the id that works upstream.
    """
    return [
        {"id": model_id, "object": "model", "owned_by": model_id.split("/")[0]}
        for model_id in DEFAULT_MODELS
    ]
