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
from src.config import get_admin_key

app = FastAPI(title="Kay-Kay Gateway", version="0.2.0")
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


@app.get("/v1/usage/{target_key_id}")
def usage_for_key(target_key_id: str, admin: str = Depends(_admin_key_id)):
    """Admin-only: get usage for a specific key."""
    return telemetry.usage_summary(key_id=target_key_id)


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


DASHBOARD_HTML = '''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kay-Kay — Gateway Dashboard</title>
<meta name="description" content="OpenAI-compatible gateway. Provider fallback, telemetry, cost tracking, spend caps.">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#06090F;--card:#121822;--panel:rgba(15,23,35,.72);--line:rgba(31,42,55,.65);--text:#E6EDF3;--muted:#7B8A9E;--accent:#4CC38A;--ok:#4CC38A;--warn:#E3B341;--bad:#F85149;--info:#6E9BF7;--radius:16px;--mono:'JetBrains Mono',ui-monospace,Menlo,Consolas,monospace;--sans:'Inter',system-ui,sans-serif}
*{box-sizing:border-box;margin:0;padding:0}body{background:var(--bg);color:var(--text);font:15px/1.65 var(--sans);-webkit-font-smoothing:antialiased}
body::before{content:'';position:fixed;top:-220px;left:50%;transform:translateX(-50%);width:900px;height:520px;background:radial-gradient(ellipse,rgba(76,195,138,.07),transparent 65%);pointer-events:none}
.wrap{max-width:1120px;margin:0 auto;padding:0 28px;position:relative;z-index:1}
.topbar{position:sticky;top:0;background:rgba(6,9,15,.84);backdrop-filter:blur(20px);border-bottom:1px solid var(--line)}.topbar .wrap{display:flex;align-items:center;height:62px}.brand{font-weight:800;font-size:16.5px;color:var(--text);text-decoration:none}.brand span{color:var(--accent)}
.hero{padding:56px 0 26px}.eyebrow{display:inline-flex;align-items:center;gap:8px;font:12px/1 var(--mono);padding:6px 14px;border-radius:999px;border:1px solid rgba(76,195,138,.35);color:var(--accent);background:rgba(76,195,138,.07);margin-bottom:16px}.hero h1{font-size:clamp(26px,3.6vw,40px);font-weight:800;letter-spacing:-.03em}.hero h1 .grad{background:linear-gradient(135deg,var(--accent),#3BA5D6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}.hero .lead{color:var(--muted);font-size:15px;max-width:64ch;margin-top:10px}.hero code,.mono{font-family:var(--mono)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:13px;margin:26px 0 6px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:19px;backdrop-filter:blur(12px);transition:transform .25s,border-color .25s}.stat:hover{transform:translateY(-3px);border-color:rgba(76,195,138,.3)}
.stat .v{font-size:27px;font-weight:600;font-family:var(--mono)}.stat .l{font-size:11.5px;color:var(--muted);margin-top:5px}.stat .green{color:var(--accent)}.stat .red{color:var(--bad)}.stat .blue{color:var(--info)}
section{padding:34px 0;border-top:1px solid var(--line);margin-top:16px}section h2{font-size:20px;font-weight:700;letter-spacing:-.02em}section .sub{color:var(--muted);font-size:13.5px;margin:4px 0 18px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:22px;backdrop-filter:blur(12px)}.card h3{font-size:11.5px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:13px}
table.hu{width:100%;border-collapse:collapse;font-size:12px;font-family:var(--mono)}table.hu th{padding:8px 12px;text-align:left;color:var(--muted);font-weight:600;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid var(--line)}table.hu td{padding:8px 12px;border-bottom:1px solid rgba(31,42,55,.5)}table.hu tbody tr:hover{background:rgba(31,42,55,.35)}
.pill{display:inline-block;font:11px/1 var(--mono);font-weight:600;padding:4px 10px;border-radius:999px}.pill.ok{background:rgba(76,195,138,.12);color:var(--accent);border:1px solid rgba(76,195,138,.3)}.pill.bad{background:rgba(248,81,73,.1);color:var(--bad);border:1px solid rgba(248,81,73,.3)}.pill.blue{background:rgba(110,155,247,.1);color:var(--info);border:1px solid rgba(110,155,247,.3)}
.bar{height:7px;border-radius:99px;background:rgba(31,42,55,.8);overflow:hidden;margin-top:6px}.bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--accent),#3BA5D6);transition:width .6s}
code{font-family:var(--mono);font-size:11px;background:rgba(255,255,255,.05);padding:2px 7px;border-radius:6px}
.empty{color:var(--muted);font-size:13px;padding:18px 0;text-align:center}.muted{color:var(--muted)}
footer{border-top:1px solid var(--line);padding:24px 0 40px;color:var(--muted);font-size:13px;margin-top:16px}footer a{color:var(--muted);margin-right:16px;text-decoration:none}
</style></head><body>
<div class="topbar"><div class="wrap"><a class="brand" href="/dashboard">◈ Kay-Kay <span>Gateway</span></a></div></div>
<div class="wrap">
  <div class="hero">
    <span class="eyebrow">● Chapter 1: Connect + Observe</span>
    <h1>One endpoint. <span class="grad">Every provider. Full receipts.</span></h1>
    <p class="lead">Drop-in OpenAI-compatible gateway — change <code>base_url</code> + <code>api_key</code> and get provider fallback, per-call telemetry, spend caps, and honest cost estimates.</p>
  </div>
  <div class="stats" id="stats"></div>
  <section><h2>Spend by provider / model</h2><p class="sub">Estimated from a transparent USD/1M-token price table. No fake precision.</p>
  <div class="card"><h3>◈ Ledger</h3><div id="by-model"></div></div></section>
  <section><h2>Recent requests</h2><p class="sub">Live stream of gateway traffic.</p>
  <div class="card"><h3>● Stream</h3><div id="recent"></div></div></section>
</div>
<footer><div class="wrap"><a href="https://github.com/HarshCodeK/kay-kay">github.com/HarshCodeK/kay-kay</a><span style="float:right" class="muted">MIT · model-agnostic by design</span></div></footer>
<script>
const API="/v1/usage";
async function load(){
  try{
    const r=await fetch(API);
    if(!r.ok){document.getElementById("stats").innerHTML='<p class="empty">Send a request through the gateway first. <code>curl -H "Authorization: Bearer kk-..." http://localhost:8000/v1/usage</code></p>';return;}
    const d=await r.json();
    document.getElementById("stats").innerHTML=
      '<div class="stat"><div class="v">'+d.total_requests+'</div><div class="l">Requests</div></div>'
      +'<div class="stat"><div class="v green">$'+(d.est_cost_usd||0).toFixed(4)+'</div><div class="l">Est. cost</div></div>'
      +'<div class="stat"><div class="v green">'+(d.successful||0)+'</div><div class="l">Successful</div></div>'
      +'<div class="stat"><div class="v '+(d.failed>0?'red':'')+'">'+(d.failed||0)+'</div><div class="l">Failed</div></div>'
      +'<div class="stat"><div class="v blue">'+Math.round(d.avg_latency_ms||0)+'</div><div class="l">Avg ms</div></div>'
      +'<div class="stat"><div class="v">'+((d.total_prompt_tokens||0)+(d.total_completion_tokens||0))+'</div><div class="l">Tokens</div></div>';
    const byModel=d.by_model||[];
    const total=byModel.reduce((s,x)=>s+(x[3]||0),0)||1;
    document.getElementById("by-model").innerHTML=byModel.length===0
      ?'<p class="empty">No traffic yet.</p>'
      :'<table class="hu"><thead><tr><th>Provider</th><th>Model</th><th>Reqs</th><th>Share</th><th style="text-align:right">Cost</th></tr></thead><tbody>'
      +byModel.map(x=>'<tr><td>'+x[0]+'</td><td><code>'+x[1]+'</code></td><td>'+x[2]+'</td><td style="min-width:110px"><div class="bar"><i style="width:'+Math.round(100*(x[3]||0)/total)+'%"></i></div></td><td style="text-align:right">$'+(x[3]||0).toFixed(4)+'</td></tr>').join("")
      +'</tbody></table>';
    const recent=d.recent||[];
    document.getElementById("recent").innerHTML=recent.length===0
      ?'<p class="empty">No requests yet.</p>'
      :'<table class="hu"><thead><tr><th>Time</th><th>Model</th><th>Status</th><th>Latency</th><th style="text-align:right">Cost</th></tr></thead><tbody>'
      +recent.map(x=>'<tr><td class="muted">'+new Date(x[0]).toLocaleTimeString()+'</td><td><code>'+x[3]+'</code></td><td><span class="pill '+(x[4]==='ok'?'ok':'bad')+'">'+x[4]+'</span></td><td>'+Math.round(x[5])+'ms</td><td style="text-align:right">$'+(x[6]||0).toFixed(5)+'</td></tr>').join("")
      +'</tbody></table>';
  }catch(e){
    document.getElementById("stats").innerHTML='<p class="empty">Backend not running. Start with: <code>python -m uvicorn src.gateway:app --reload</code></p>';
  }
}
load();setInterval(load,3000);
</script>
</body></html>'''


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML
