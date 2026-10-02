"""Forward a request to whichever provider is configured, with fallback.

Every provider speaks the OpenAI chat-completions shape, so the gateway
converts nothing -- it only decides *where to send* the request. That is what
makes it a drop-in replacement: an existing OpenAI client changes two lines.

Retry policy, and why: a 4xx that is not 429 will never succeed on retry, so it
breaks to the next provider immediately. Timeouts and transport errors are
transient and do get retried. Retrying a 400 just wastes the budget.
"""
import os
import time

import httpx

from src.config import MAX_RETRIES, PROVIDER_CHAIN, TIMEOUT_S


class ProviderError(Exception):
    """Every provider in the chain failed."""


def _endpoints() -> dict:
    """Resolve the chain to {name: base_url} for providers that are configured."""
    out = {}
    for name in PROVIDER_CHAIN:
        if name == "groq":
            if os.environ.get("GROQ_API_KEY"):
                out[name] = "https://api.groq.com/openai/v1"
        else:
            base = os.environ.get(f"{name.upper()}_BASE_URL")
            if base and os.environ.get(f"{name.upper()}_API_KEY"):
                out[name] = base.rstrip("/")
    return out


def chat(body: dict):
    """POST `body` down the chain. Returns (response_json, provider_name)."""
    endpoints = _endpoints()
    if not endpoints:
        raise ProviderError(
            "no providers configured. Set GROQ_API_KEY, or "
            "KAYKAY_PROVIDERS with a *_BASE_URL and *_API_KEY."
        )

    last = None
    for name, base_url in endpoints.items():
        headers = {
            "Authorization": f"Bearer {os.environ[_key_var(name)]}",
            "Content-Type": "application/json",
        }
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = httpx.post(f"{base_url}/chat/completions", json=body,
                               headers=headers, timeout=TIMEOUT_S)
                if r.status_code == 200:
                    return r.json(), name
                last = ProviderError(f"{name} HTTP {r.status_code}")
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    break            # retrying a client error cannot help
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = ProviderError(f"{name} {type(e).__name__}")
    raise last or ProviderError("all providers failed")


def _key_var(provider: str) -> str:
    return "GROQ_API_KEY" if provider == "groq" else f"{provider.upper()}_API_KEY"


def models_available():
    """(id, owned_by) pairs in OpenAI's response shape, from the registry."""
    from src.config import DEFAULT_MODELS
    return [{"id": m, "object": "model", "owned_by": m.split("/")[0]}
            for m in DEFAULT_MODELS]
