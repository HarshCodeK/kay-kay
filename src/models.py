"""Which models exist, and what they cost.

One file, because a model name hardcoded anywhere else is a bug waiting to
happen. Groq retires models without a deprecation warning -- an outdated id
returns a hard 404 -- so every model used anywhere in this project is named
here and nowhere else.

Checked live on 2026-10-03 via GET /models with this account's key:
`llama-3.3-70b-versatile` and `llama-3.1-8b-instant` return 404, and
`qwen/qwen3.8-27b` is flagged preview.
"""

# id: (label, input $/1M, output $/1M)
MODELS = {
    "openai/gpt-oss-120b": ("GPT-OSS 120B", 0.15, 0.60),
    "openai/gpt-oss-20b": ("GPT-OSS 20B", 0.075, 0.30),
    "qwen/qwen3.8-27b": ("Qwen 3.8 27B (preview)", 0.80, 4.00),
    "allam-2-7b": ("ALLaM 2 7B", 0.30, 0.30),
}

DEFAULT_MODEL = "openai/gpt-oss-120b"


class UnknownModel(ValueError):
    """A model id that is not in the table above."""


def resolve(model_id: str = None) -> str:
    """Return a model id that is known to exist."""
    candidate = model_id or DEFAULT_MODEL
    if candidate not in MODELS:
        raise UnknownModel(
            f"{candidate!r} is not a known model. Available: {', '.join(MODELS)}"
        )
    return candidate


def estimate_cost_usd(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Rough cost. Unknown models are refused rather than guessed at."""
    _, per_in, per_out = MODELS[resolve(model_id)]
    return (prompt_tokens * per_in + completion_tokens * per_out) / 1_000_000
