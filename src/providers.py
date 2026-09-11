"""Provider layer: one wire format, many providers, retry + fallback.

Every provider speaks the OpenAI chat-completions shape, so the gateway
converts nothing — it just picks where to send the request. Groq is the
default; any OpenAI-compatible endpoint (OpenAI, Together, vLLM, Ollama's
compat layer...) joins via env vars.
"""
import os
import time
import httpx

from src.config import PROVIDER_CHAIN, MAX_RETRIES, TIMEOUT_S


class ProviderError(Exception):
    pass


def _providers() -> dict:
    """Resolve the chain to {name: {base_url, key, default_model}}."""
    out = {}
    for name in PROVIDER_CHAIN:
        if name == "groq":
            if os.environ.get("GROQ_API_KEY"):
                out["groq"] = {
                    "base_url": "https://api.groq.com/openai/v1",
                    "key": os.environ["GROQ_API_KEY"],
                }
        else:
            base = os.environ.get(f"{name.upper()}_BASE_URL")
            key = os.environ.get(f"{name.upper()}_API_KEY")
            if base and key:
                out[name] = {"base_url": base.rstrip("/"), "key": key}
    return out


def call_chat_completion(body: dict, log_fn=print) -> tuple[dict, str]:
    """POST body to providers in chain order; return (response_json, provider_name).

    Retries each provider MAX_RETRIES times, then falls back to the next.
    Raises ProviderError when the whole chain is exhausted.
    """
    providers = _providers()
    if not providers:
        raise ProviderError("no providers configured (set GROQ_API_KEY etc.)")

    last_err = None
    for name, p in providers.items():
        url = f"{p['base_url']}/chat/completions"
        headers = {"Authorization": f"Bearer {p['key']}",
                   "Content-Type": "application/json"}
        for attempt in range(1, MAX_RETRIES + 1):
            start = time.time()
            try:
                r = httpx.post(url, json=body, headers=headers, timeout=TIMEOUT_S)
                latency = (time.time() - start) * 1000
                if r.status_code == 200:
                    return r.json(), name
                last_err = ProviderError(f"{name} HTTP {r.status_code}: {r.text[:200]}")
                # 4xx (except 429) won't improve with retry — fall to next provider
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    break
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_err = ProviderError(f"{name} transport: {e.__class__.__name__}")
                latency = (time.time() - start) * 1000
            log_fn(f"attempt {attempt} on {name} failed ({latency:.0f}ms); "
                   f"{'retrying' if attempt < MAX_RETRIES else 'falling back'}")
    raise last_err or ProviderError("all providers failed")


def list_models() -> list[dict]:
    """Advertise a stable model list across providers."""
    return [
        {"id": "llama-3.3-70b-versatile", "object": "model", "owned_by": "groq"},
        {"id": "llama-4-scout-17b-16e-instruct", "object": "model", "owned_by": "groq"},
    ]
