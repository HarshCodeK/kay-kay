"""The gateway app — drop-in OpenAI-compatible endpoint.

Point an existing OpenAI client at it by changing base_url and api_key:

    from openai import OpenAI
    client = OpenAI(base_url="http://localhost:8000/v1", api_key="kk-...")
"""
import time
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src import auth, telemetry
from src.providers import call_chat_completion, list_models, ProviderError
from src.config import get_admin_key, DEFAULT_MODELS

app = FastAPI(title="Kay-Kay Gateway", version="0.2.0")
_bearer = HTTPBearer(auto_error=False)


@app.on_event("startup")
def _startup():
    """Create tables and make sure the admin key exists.

    Kept as `on_event` rather than a lifespan handler purely to match the
    sibling projects; FastAPI marks it deprecated but it still works. Migrating
    to `lifespan` is a cosmetic change, not a fix.
    """
    auth.init_tables()
    telemetry.init_tables()
    if not get_admin_key():
        raise RuntimeError("admin key missing")  # unreachable; get_admin_key generates


def _key_id(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    auth.init_tables()  # idempotent: CREATE IF NOT EXISTS + seed admin key
    # HTTPBearer already parsed the header; credentials.credentials is the bare token
    key_id = auth.verify_key(credentials.credentials) if credentials else None
    if not key_id:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    if not auth.check_key_active(key_id):
        raise HTTPException(status_code=403, detail="API key has been revoked")
    return key_id


def _admin_key_id(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    """Verify the caller is the admin key."""
    auth.init_tables()
    key_id = auth.verify_key(credentials.credentials) if credentials else None
    if not key_id or key_id != "admin":
        raise HTTPException(status_code=403, detail="Admin key required")
    return key_id


@app.post("/v1/chat/completions")
def chat_completions(body: dict, key_id: str = Depends(_key_id)):
    # --- spend cap enforcement ---
    cap = auth.get_key_spend_cap(key_id)
    if cap > 0:
        spent = telemetry.get_key_spend(key_id)
        if spent >= cap:
            raise HTTPException(status_code=402, detail={
                "error": "spend_cap_exceeded",
                "spent_usd": round(spent, 6),
                "cap_usd": cap,
                "message": f"Key {key_id} has exceeded its ${cap:.2f} spend cap (${spent:.4f} spent)",
            })

    start = time.time()
    # Default to the first advertised model rather than a hardcoded id. The
    # previous default, llama-3.3-70b-versatile, was retired by Groq on
    # 2026-07-17, so a client that omitted `model` got a 404 every time.
    model = body.get("model") or DEFAULT_MODELS[0]
    try:
        resp, provider = call_chat_completion(body)
    except ProviderError as e:
        latency = (time.time() - start) * 1000
        telemetry.log_request(key_id, "-", model, "error", 502, latency, 0, 0, str(e))
        raise HTTPException(status_code=502, detail=str(e))

    latency = (time.time() - start) * 1000
    usage = resp.get("usage", {}) or {}
    telemetry.log_request(
        key_id, provider, resp.get("model", model), "ok", 200, latency,
        usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
    )
    return resp


@app.get("/v1/models")
def models(key_id: str = Depends(_key_id)):
    return {"object": "list", "data": list_models()}


@app.get("/v1/usage")
def usage(key_id: str = Depends(_key_id)):
    return telemetry.usage_summary()


@app.get("/v1/usage/{target_key_id}")
def usage_for_key(target_key_id: str, admin: str = Depends(_admin_key_id)):
    """Admin-only: get usage for a specific key."""
    return telemetry.usage_summary(key_id=target_key_id)


# --- Agent: a bounded tool-calling loop that runs through this gateway ---

@app.post("/v1/agent")
def agent(body: dict, key_id: str = Depends(_key_id)):
    """Run one agent turn.

    The agent calls `providers.call_chat_completion`, i.e. it goes through the
    same path as any other client — so spend caps and telemetry apply to agent
    turns too. That is deliberate: an agent loop that bypassed the gateway
    would be exactly the unbounded-spend hole this project exists to close.

    `model` is validated against the advertised list so a typo becomes a 400
    naming the valid ids, rather than a provider 404 we then have to interpret.
    """
    from src import agent as agent_mod
    from src.config import DEFAULT_MODELS

    model = body.get("model") or DEFAULT_MODELS[0]
    if model not in DEFAULT_MODELS:
        raise HTTPException(status_code=400, detail={
            "error": "unknown_model",
            "model": model,
            "advertised": DEFAULT_MODELS,
        })

    cap = auth.get_key_spend_cap(key_id)
    if cap > 0 and telemetry.get_key_spend(key_id) >= cap:
        raise HTTPException(status_code=402, detail={
            "error": "spend_cap_exceeded",
            "cap_usd": cap,
        })

    start = time.time()
    result = agent_mod.run_agent(
        task=str(body.get("task", ""))[:8000],
        model=model,
        max_rounds=int(body.get("max_rounds") or agent_mod.MAX_ROUNDS_DEFAULT),
        conversation=str(body.get("conversation", ""))[:4000],
    )

    # The agent made N upstream calls; log the run as one aggregate row so the
    # ledger shows agent spend without needing per-round bookkeeping here.
    telemetry.log_request(
        key_id, "agent", model,
        "ok" if result["mode"] != "provider_error" else "error",
        200 if result["mode"] != "provider_error" else 502,
        (time.time() - start) * 1000,
        0, 0, error=result["answer"] if result["mode"] == "provider_error" else None,
    )
    return {"key_id": key_id, **result}


@app.get("/v1/agent/tools")
def agent_tools(key_id: str = Depends(_key_id)):
    """Tools available to the agent."""
    from src import agent as agent_mod

    return {"tools": agent_mod.tool_manifest()}


# --- Admin key management ---

@app.get("/v1/keys")
def list_keys(admin: str = Depends(_admin_key_id)):
    """List all API keys (admin only)."""
    return {"keys": auth.list_keys()}


@app.post("/v1/keys")
def create_key(body: dict, admin: str = Depends(_admin_key_id)):
    """Issue a new API key (admin only). Returns the key ONCE."""
    name = body.get("name", "unnamed")
    spend_cap = body.get("spend_cap_usd", 0)
    key = auth.issue_key(name, spend_cap)
    keys = auth.list_keys()
    new_key = keys[-1] if keys else {}
    return {"key": key, "key_id": new_key.get("key_id"), "name": name, "spend_cap_usd": spend_cap,
            "message": "Save this key — it won't be shown again"}


@app.post("/v1/keys/{key_id}/revoke")
def revoke_key(key_id: str, admin: str = Depends(_admin_key_id)):
    """Revoke an API key (admin only)."""
    ok = auth.revoke_key(key_id)
    if not ok:
        raise HTTPException(404, f"key not found: {key_id}")
    return {"revoked": True, "key_id": key_id}


from src.dashboard import DASHBOARD_HTML

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML
