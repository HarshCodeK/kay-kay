import hashlib
import hmac
import os
import secrets
from threading import Lock

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .core import Gateway, Request

app = FastAPI(title="KAY-KAY Gateway")
_KEYS: dict[str, bool] = {}
_KEYS_LOCK = Lock()
MAX_KEYS = 2_048


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def issue_key() -> str:
    key = "kk-" + secrets.token_urlsafe(18)
    with _KEYS_LOCK:
        if len(_KEYS) >= MAX_KEYS:
            # This registry is ephemeral and deliberately refuses new keys rather
            # than evicting a potentially active credential without warning.
            raise RuntimeError("key_registry_full")
        _KEYS[_hash(key)] = True
    return key


gateway = Gateway(
    {"primary": lambda request: f"echo: {request.prompt}", "fallback": lambda request: f"fallback: {request.prompt}"},
    {"default": 0.002},
    1.0,
)


class Chat(BaseModel):
    model: str = "default"
    prompt: str = Field(min_length=1, max_length=20_000)
    max_tokens: int = Field(default=256, ge=1, le=4096)


@app.get("/health")
def health():
    return {"ok": True, "mode": "deterministic_stub", "providers": len(gateway.providers)}


@app.get("/ready")
def ready():
    return {"ready": True, "budget_scope": "process-local"}


@app.get("/metrics")
def metrics():
    return gateway.snapshot()


@app.post("/v1/keys")
def keys(x_admin_token: str = Header(default="", alias="X-Admin-Token")):
    expected = os.getenv("KAYKAY_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(503, "key issuance is disabled until KAYKAY_ADMIN_TOKEN is configured")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(403, "administrator token required")
    try:
        return {"api_key": issue_key()}
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/v1/chat/completions")
def chat(body: Chat, x_api_key: str = Header(default="", alias="X-API-Key")):
    with _KEYS_LOCK:
        valid_key = bool(x_api_key) and _hash(x_api_key) in _KEYS
    if not valid_key:
        raise HTTPException(401, "invalid api key")
    try:
        response = gateway.complete(Request(x_api_key, body.model, body.prompt, body.max_tokens))
    except RuntimeError as exc:
        message = str(exc)
        status = 402 if message == "budget_exceeded" else 400 if message in {"unknown_model", "invalid_prompt", "invalid_max_tokens"} else 502
        raise HTTPException(status, message) from exc
    return {"text": response.text, "provider": response.provider, "estimated_cost": response.estimated_cost}
