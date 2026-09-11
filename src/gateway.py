"""The gateway app — drop-in OpenAI-compatible endpoint.

Point an existing OpenAI client at it by changing base_url and api_key:

    from openai import OpenAI
    client = OpenAI(base_url="http://localhost:8000/v1", api_key="kk-...")
"""
import time
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src import auth, telemetry
from src.providers import call_chat_completion, list_models, ProviderError
from src.config import get_admin_key

app = FastAPI(title="Kay-Kay Gateway", version="0.1.0")
_bearer = HTTPBearer(auto_error=False)


@app.on_event("startup")
def _startup():
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
    return key_id


@app.post("/v1/chat/completions")
def chat_completions(body: dict, key_id: str = Depends(_key_id)):
    start = time.time()
    model = body.get("model", "llama-3.3-70b-versatile")
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
