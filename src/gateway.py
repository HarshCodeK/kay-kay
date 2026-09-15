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


DASHBOARD_HTML = '''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kay-Kay — Gateway Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{--bg:#0b0f14;--card:#121822;--line:rgba(31,42,55,.6);--text:#e5e7eb;--muted:#9ca3af;--accent:#3b82f6;--ok:#22c55e;--info:#60a5fa;font-family:Inter,system-ui,sans-serif}
*{box-sizing:border-box;margin:0;padding:0}body{background:var(--bg);color:var(--text)}
.wrap{max-width:1120px;margin:0 auto;padding:24px}
header{border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:24px}
header .name{font-weight:800;font-size:18px;background:linear-gradient(135deg,#e5e7eb,var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
header .sub{color:var(--muted);font-size:13px;margin-top:2px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:24px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.stat .v{font-size:24px;font-weight:700;font-family:ui-monospace}
.stat .l{font-size:11px;color:var(--muted);margin-top:4px;text-transform:uppercase;letter-spacing:.5px}
.stat .accent{color:var(--accent)}
table{width:100%;border-collapse:collapse}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--line);font-size:13px}
th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
td{font-family:ui-monospace;font-size:12px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:24px}
.panel h3{font-size:14px;font-weight:600;margin-bottom:12px}
.bar{height:6px;border-radius:3px;background:var(--line);overflow:hidden;margin-top:4px}
.bar > div{height:100%;border-radius:3px;transition:width .6s}
.bar .green{background:var(--ok)}
code{font-family:ui-monospace;font-size:11px;background:rgba(255,255,255,.04);padding:2px 6px;border-radius:4px}
</style></head><body>
<div class="wrap">
  <header><div class="name">Kay-Kay Gateway</div><div class="sub">Chapter 1: Connect + Observe — cost accounting & provider telemetry</div></header>
  <div class="stats" id="stats"></div>
  <div class="panel"><h3>Spend by provider / model</h3><div id="by-model"></div></div>
  <div class="panel"><h3>Recent requests</h3><div id="recent"></div></div>
</div>
<script>
const API="/v1/usage";
async function load(){
  try{
    const r=await fetch(API);
    if(!r.ok){document.getElementById("stats").innerHTML='<p style="color:var(--muted)">Send a request through the gateway first. <code>curl -H "Authorization: Bearer kk-..." http://localhost:8000/v1/usage</code></p>';return;}
    const d=await r.json();
    document.getElementById("stats").innerHTML=
      '<div class="stat"><div class="v">'+d.total_requests+'</div><div class="l">Requests</div></div>'
      +'<div class="stat"><div class="v accent">$'+(d.est_cost_usd||0).toFixed(4)+'</div><div class="l">Est. cost</div></div>'
      +'<div class="stat"><div class="v" style="color:var(--ok)">'+(d.successful||0)+'</div><div class="l">Successful</div></div>'
      +'<div class="stat"><div class="v">'+(d.failed||0)+'</div><div class="l">Failed</div></div>'
      +'<div class="stat"><div class="v">'+Math.round(d.avg_latency_ms||0)+'</div><div class="l">Avg ms</div></div>'
      +'<div class="stat"><div class="v">'+((d.total_prompt_tokens||0)+(d.total_completion_tokens||0))+'</div><div class="l">Tokens</div></div>';
    const byModel=d.by_model||[];
    const maxCost=Math.max(...byModel.map(r=>r[3]||0),0.001);
    document.getElementById("by-model").innerHTML=
      '<table><thead><tr><th>Provider</th><th>Model</th><th>Requests</th><th>Cost (USD)</th></tr></thead><tbody>'
      +byModel.map(r=>`<tr><td>${r[0]}</td><td><code>${r[1]}</code></td><td>${r[2]}</td><td>$${(r[3]||0).toFixed(4)}</td></tr>`).join("")
      +'</tbody></table>';
    const recent=d.recent||[];
    document.getElementById("recent").innerHTML=
      '<table><thead><tr><th>Time</th><th>Model</th><th>Status</th><th>Latency</th><th>Cost</th></tr></thead><tbody>'
      +recent.map(r=>`<tr><td>${new Date(r[0]).toLocaleTimeString()}</td><td><code>${r[3]}</code></td><td>${r[4]}</td><td>${Math.round(r[5])}ms</td><td>$${(r[6]||0).toFixed(5)}</td></tr>`).join("")
      +'</tbody></table>';
  }catch(e){
    document.getElementById("stats").innerHTML='<p style="color:#ef4444">Backend not running. Start with: <code>python -m uvicorn src.gateway:app --reload</code></p>';
  }
}
load();setInterval(load,3000);
</script>
</body></html>'''


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML
