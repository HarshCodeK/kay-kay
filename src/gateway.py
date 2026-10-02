"""The gateway: an OpenAI-compatible HTTP service with keys, caps and telemetry.

    from openai import OpenAI
    client = OpenAI(base_url="http://localhost:8000/v1", api_key="kk-...")

That is the entire integration. Everything else is what the gateway does on the
way through.
"""
import json
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src import auth, models as model_registry, providers, telemetry
from src.config import DEFAULT_MODELS, PROVIDER_CHAIN, DEFAULT_REQUEST_COMPLETION_TOKENS, MAX_REQUEST_COMPLETION_TOKENS

app = FastAPI(title="Kay-Kay Gateway", version="1.0.0")
_bearer = HTTPBearer(auto_error=False)


@app.on_event("startup")
def _startup():
    auth.init()
    telemetry.init()


def _key_id(creds: HTTPAuthorizationCredentials = Depends(_bearer)):
    """Verify the caller's key and that it has not been revoked."""
    key_id = auth.verify(creds.credentials) if creds else None
    if not key_id:
        raise HTTPException(401, "Invalid or missing API key")
    if not auth.is_active(key_id):
        raise HTTPException(403, "API key has been revoked")
    return key_id


def _admin(admin: HTTPAuthorizationCredentials = Depends(_bearer)):
    """Only the bootstrap key may manage other keys."""
    key_id = auth.verify(admin.credentials) if admin else None
    if key_id != "admin":
        raise HTTPException(403, "Admin key required")
    return key_id


def _prepare_body(body: dict, model_id: str) -> tuple[dict, float]:
    body = dict(body)
    body.setdefault("model", model_id)
    if body["model"] not in DEFAULT_MODELS:
        raise HTTPException(400, {"error": "unknown_model", "model": body["model"], "advertised": DEFAULT_MODELS})
    max_tokens = int(body.get("max_tokens") or DEFAULT_REQUEST_COMPLETION_TOKENS)
    if max_tokens < 1 or max_tokens > MAX_REQUEST_COMPLETION_TOKENS:
        raise HTTPException(400, {"error": "invalid_max_tokens", "max_tokens": MAX_REQUEST_COMPLETION_TOKENS})
    body["max_tokens"] = max_tokens
    prompt_upper = len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return body, model_registry.estimate_cost_usd(body["model"], prompt_upper, max_tokens)

def _run_metered_chat(key_id: str, body: dict):
    cap = auth.spend_cap(key_id)
    body, worst_case = _prepare_body(body, body.get("model") or DEFAULT_MODELS[0])
    reservation = telemetry.reserve_budget(key_id, cap, worst_case)
    if cap > 0 and reservation is None:
        raise HTTPException(402, {"error": "spend_cap_exceeded", "message": "request worst-case reservation exceeds remaining budget"})

    started = time.time()
    try:
        response, provider = providers.chat(body)
    except providers.ProviderError as ex:
        telemetry.record(key_id, "-", body.get("model"), "error",
                         (time.time() - started) * 1000, error=str(ex))
        telemetry.release_budget(reservation)
        raise HTTPException(502, str(ex))

    usage = response.get("usage") or {}
    telemetry.record(
        key_id, provider, response.get("model", body.get("model")), "ok",
        (time.time() - started) * 1000,
        usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
    )
    telemetry.release_budget(reservation)
    return response, provider

@app.post("/v1/chat/completions")
def chat_completions(body: dict, key_id: str = Depends(_key_id)):
    """Drop-in replacement for the OpenAI endpoint."""
    return _run_metered_chat(key_id, body)[0]


@app.get("/v1/models")
def models(key_id: str = Depends(_key_id)):
    return {"object": "list", "data": providers.models_available()}


# --- the agent, routed through this gateway so its spend is capped ----------

@app.post("/v1/agent")
def agent(body: dict, key_id: str = Depends(_key_id)):
    """One agent turn. Spend-capped and logged like any other call."""
    from src import agent as agent_mod

    model_id = body.get("model") or DEFAULT_MODELS[0]
    if model_id not in DEFAULT_MODELS:
        raise HTTPException(400, {
            "error": "unknown_model", "model": model_id,
            "advertised": DEFAULT_MODELS,
        })
    rounds = max(1, min(int(body.get("max_rounds") or agent_mod.MAX_ROUNDS), agent_mod.MAX_ROUNDS))
    result = agent_mod.run(
        task=str(body.get("task", ""))[:8000],
        model_id=model_id,
        max_rounds=rounds,
        conversation=str(body.get("conversation", ""))[:4000],
        chat_fn=lambda request_body: _run_metered_chat(key_id, request_body),
    )
    return {"key_id": key_id, **result}


@app.get("/v1/agent/tools")
def agent_tools(key_id: str = Depends(_key_id)):
    from src import agent as agent_mod
    return {"tools": agent_mod.manifest()}


# --- telemetry ---------------------------------------------------------------

@app.get("/v1/usage")
def usage(key_id: str = Depends(_key_id)):
    return telemetry.summary()


@app.get("/v1/usage/{target}")
def usage_for_key(target: str, admin: str = Depends(_admin)):
    return telemetry.summary(key_id=target)


# --- key management ----------------------------------------------------------

@app.get("/v1/keys")
def list_keys(admin: str = Depends(_admin)):
    return {"keys": auth.all_keys()}


@app.post("/v1/keys")
def create_key(body: dict, admin: str = Depends(_admin)):
    """Issue a key. The plaintext is returned exactly once."""
    plain = auth.issue(body.get("name", "unnamed"), float(body.get("spend_cap_usd", 0)))
    return {"key": plain, "spend_cap_usd": float(body.get("spend_cap_usd", 0)),
            "message": "Save this key -- it is not shown again"}


@app.post("/v1/keys/{key_id}/revoke")
def revoke_key(key_id: str, admin: str = Depends(_admin)):
    if not auth.revoke(key_id):
        raise HTTPException(404, f"key not found: {key_id}")
    return {"revoked": True, "key_id": key_id}


@app.get("/dashboard")
def dashboard():
    from src.dashboard import DASHBOARD_HTML
    from fastapi.responses import HTMLResponse
    return HTMLResponse(DASHBOARD_HTML)


@app.get("/health")
def health():
    """Liveness plus which providers are actually configured.

    Naming them is the point: a gateway with no provider configured returns 200
    here and then 502 on every chat call, which is a confusing thing to debug.
    """
    return {
        "status": "ok",
        "providers_configured": list(providers._endpoints()),
        "chain": PROVIDER_CHAIN,
        "models": DEFAULT_MODELS,
    }
