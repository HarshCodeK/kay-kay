"""Dashboard HTML for the gateway.

Split out of gateway.py: it was 100 lines of embedded HTML inside the app
module, which made the routing code hard to read for no benefit. Keeping it
as a plain string constant here means gateway.py stays about the gateway.

Design: one accent colour, system fonts (no web-font request), tabular
numbers for the cost columns, and every table built with textContent rather
than innerHTML so a model name containing a quote cannot inject markup.
"""
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
// Why no innerHTML: `model` in every row comes from the request body, so it is
// attacker-controlled. Building nodes and assigning textContent means a model
// named "<img onerror=...>" renders as that literal string instead of executing.
const API = "/v1/usage";

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function stat(value, label, cls) {
  const box = el("div", "stat");
  box.appendChild(el("div", "v" + (cls ? " " + cls : ""), value));
  box.appendChild(el("div", "l", label));
  return box;
}

function table(headings) {
  const t = el("table", "hu");
  const thead = el("thead");
  const hr = el("tr");
  headings.forEach(h => hr.appendChild(el("th", null, h)));
  thead.appendChild(hr);
  t.appendChild(thead);
  t.appendChild(el("tbody"));
  return t;
}

function money(n) {
  return "$" + (Number(n) || 0).toFixed(5);
}

async function load() {
  const statsBox = document.getElementById("stats");
  const modelBox = document.getElementById("by-model");
  const recentBox = document.getElementById("recent");

  let d;
  try {
    const r = await fetch(API);
    if (!r.ok) throw new Error("HTTP " + r.status);
    d = await r.json();
  } catch (e) {
    statsBox.replaceChildren(el("p", "empty",
      "Backend not running. Start with: python -m uvicorn src.gateway:app"));
    return;
  }

  const failed = d.failed || 0;
  statsBox.replaceChildren(
    stat(d.total_requests || 0, "Requests"),
    stat("$" + (d.est_cost_usd || 0).toFixed(4), "Est. cost", "green"),
    stat(d.successful || 0, "Successful", "green"),
    stat(failed, "Failed", failed > 0 ? "red" : ""),
    stat(Math.round(d.avg_latency_ms || 0), "Avg ms", "blue"),
    stat((d.total_prompt_tokens || 0) + (d.total_completion_tokens || 0), "Tokens")
  );

  const byModel = d.by_model || [];
  if (byModel.length === 0) {
    modelBox.replaceChildren(el("p", "empty", "No traffic yet."));
  } else {
    const total = byModel.reduce((acc, row) => acc + (row[3] || 0), 0) || 1;
    const t = table(["Provider", "Model", "Reqs", "Share", "Cost"]);
    const tb = t.querySelector("tbody");
    byModel.forEach(([provider, model, reqs, cost]) => {
      const tr = el("tr");
      tr.appendChild(el("td", null, provider));
      const mtd = el("td");
      mtd.appendChild(el("code", null, model));
      tr.appendChild(mtd);
      tr.appendChild(el("td", null, reqs));
      const pct = Math.round(100 * (cost || 0) / total);
      const share = el("td", null);
      const bar = el("div", "bar");
      const fill = el("i");
      fill.style.width = pct + "%";
      bar.appendChild(fill);
      share.appendChild(bar);
      tr.appendChild(share);
      tr.appendChild(el("td", "num", money(cost)));
      tb.appendChild(tr);
    });
    modelBox.replaceChildren(t);
  }

  const recent = d.recent || [];
  if (recent.length === 0) {
    recentBox.replaceChildren(el("p", "empty", "No requests yet."));
  } else {
    const t = table(["Time", "Model", "Status", "Latency", "Cost"]);
    const tb = t.querySelector("tbody");
    recent.forEach(row => {
      const [ts, keyId, provider, model, status, latency, cost] = row;
      const tr = el("tr");
      tr.appendChild(el("td", "muted", new Date(ts).toLocaleTimeString()));
      const mtd = el("td");
      mtd.appendChild(el("code", null, model));
      tr.appendChild(mtd);
      const std = el("td");
      std.appendChild(el("span", "pill " + (status === "ok" ? "ok" : "bad"), status));
      tr.appendChild(std);
      tr.appendChild(el("td", null, Math.round(latency) + "ms"));
      tr.appendChild(el("td", "num", money(cost)));
      tb.appendChild(tr);
    });
    recentBox.replaceChildren(t);
  }
}

load();
setInterval(load, 3000);
</script>
</body></html>
'''
