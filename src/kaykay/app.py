import hashlib
import hmac
import os
import secrets
from threading import Lock

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .core import Gateway, Request
from .observability import ProcessMetrics

app = FastAPI(title="KAY-KAY Gateway", version="0.2.0")
_KEYS: dict[str, bool] = {}
_KEYS_LOCK = Lock()
_MAX_KEYS_PER_PROCESS = 1000
_metrics = ProcessMetrics()
_METRICS_EXCLUDED = {"/", "/health", "/ready", "/metrics"}
gateway = Gateway(
    {"primary": lambda request: f"echo: {request.prompt}", "fallback": lambda request: f"fallback: {request.prompt}"},
    {"default": 0.002},
    1.0,
)


class Chat(BaseModel):
    model: str = "default"
    prompt: str = Field(min_length=1, max_length=4000)
    max_tokens: int = Field(256, ge=1, le=1024)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def issue_key() -> str:
    key = "kk-" + secrets.token_urlsafe(18)
    with _KEYS_LOCK:
        if len(_KEYS) >= _MAX_KEYS_PER_PROCESS:
            raise RuntimeError("key_limit_reached")
        _KEYS[_hash(key)] = True
    return key


@app.middleware("http")
async def collect_request_metrics(request, call_next):
    if request.url.path in _METRICS_EXCLUDED:
        return await call_next(request)
    started = _metrics.start()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        _route = request.scope.get("route")
            route_name = getattr(route, "path", "<unmatched>")
            metrics.finish(f"{request.method} {route_name}", status_code, started)


@app.get("/", response_class=HTMLResponse)
def home():
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>KAY-KAY Gateway</title><style>
body{font:16px system-ui;max-width:900px;margin:2rem auto;padding:0 1rem;color:#18212b;background:#f5f7fa}
main{background:white;border:1px solid #d9e0e8;border-radius:14px;padding:1.25rem;margin:1rem 0}
input,textarea,button{font:inherit;padding:.65rem;box-sizing:border-box;width:100%;margin:.35rem 0}
button{cursor:pointer;background:#18212b;color:white;border:0;border-radius:8px}
small{color:#526070}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f4f7;padding:1rem;border-radius:8px}
</style></head><body><h1>KAY-KAY — LLM gateway lab</h1>
<p>Explore key issuance, provider fallback, and a conservative spend reservation. Provider responses are deterministic stubs, not real model calls.</p>
<main><h2>1. Issue a demo API key</h2><p><small>Key issuance requires the deployment's admin token. Never paste this token into a public issue or screenshot.</small></p>
<input id="admin" type="password" autocomplete="off" placeholder="KAYKAY_ADMIN_TOKEN">
<button onclick="issueKey()">Issue key</button><p id="key-status"></p></main>
<main><h2>2. Run a request</h2><input id="key" type="password" autocomplete="off" placeholder="API key (kk-...)">
<textarea id="prompt" maxlength="4000" placeholder="Enter a diagnostic prompt">Explain why a provider fallback might be needed.</textarea>
<button onclick="sendRequest()">Send request</button><pre id="result">No request yet.</pre></main>
<main><h2>Observe the service</h2><p><a href="/docs">API documentation</a> · <a href="/metrics">Process metrics</a> · <a href="/health">Liveness</a> · <a href="/ready">Readiness</a></p>
<small>Metrics are process-local and reset on restart. This service uses in-memory keys and budget state; it is a portfolio lab, not a production billing ledger.</small></main>
<script>
async function issueKey(){
 const status=document.getElementById('key-status'); status.textContent='Requesting key...';
 try{
  const r=await fetch('/v1/keys',{method:'POST',headers:{'X-Admin-Token':document.getElementById('admin').value}});
  const data=await r.json();
  if(!r.ok){status.textContent='HTTP '+r.status+': '+(data.detail||'key issuance failed');return;}
  document.getElementById('key').value=data.api_key; status.textContent='Key issued for this process. Copy it to a password manager if needed; it is not persisted.';
 }catch(e){status.textContent='Request failed: '+e.name;}
}
async function sendRequest(){
 const output=document.getElementById('result'); output.textContent='Sending...';
 try{
  const r=await fetch('/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':document.getElementById('key').value},body:JSON.stringify({model:'default',prompt:document.getElementById('prompt').value,max_tokens:128})});
  const data=await r.json(); output.textContent=JSON.stringify({status:r.status,response:data},null,2);
 }catch(e){output.textContent='Request failed: '+e.name;}
}
</script></body></html>"""


@app.get("/health")
def health():
    return {"ok": True, "providers": len(gateway.providers)}


@app.get("/ready")
def ready(response: Response):
    if not gateway.providers:
        response.status_code = 503
        return {"status": "not_ready"}
    return {"status": "ready", "key_issuance": "enabled" if os.getenv("KAYKAY_ADMIN_TOKEN") else "disabled"}


@app.get("/metrics")
def metrics():
    return _metrics.snapshot()


@app.post("/v1/keys")
def keys(x_admin_token: str = Header(default="")):
    configured_token = os.getenv("KAYKAY_ADMIN_TOKEN", "")
    if not configured_token:
        raise HTTPException(503, "key issuance is disabled; configure KAYKAY_ADMIN_TOKEN")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, configured_token):
        raise HTTPException(401, "invalid admin token")
    try:
        return {"api_key": issue_key()}
    except RuntimeError as exc:
        raise HTTPException(429, "the in-memory key limit was reached; restart the demo service to reset it") from exc


@app.post("/v1/chat/completions")
def chat(body: Chat, x_api_key: str = Header(default="")):
    with _KEYS_LOCK:
        valid_key = bool(x_api_key and _KEYS.get(_hash(x_api_key)))
    if not valid_key:
        raise HTTPException(401, "invalid api key")
    try:
        result = gateway.complete(Request(x_api_key, body.model, body.prompt, body.max_tokens))
    except RuntimeError as exc:
        message = str(exc)
        status = 402 if message == "budget_exceeded" else 400 if message in {
            "unknown_model", "invalid_prompt", "invalid_max_tokens"
        } else 502
        raise HTTPException(status, message) from exc
    return {"text": result.text, "provider": result.provider, "estimated_cost": result.estimated_cost}
