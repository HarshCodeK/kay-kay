"""Dashboard HTML.

Split out of gateway.py: it was 100 lines of markup inside the app module,
which made the routing code harder to read for no benefit.

One rule that is a security rule, not a style rule: no innerHTML anywhere. The
model name in every row comes from the request body, so it is
attacker-controlled. A request with model "<img onerror=...>" would execute if
the page were built by string concatenation. Building nodes and assigning
textContent renders that as the literal string instead.
"""
DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kay-Kay Gateway</title>
<style>
:root{--bg:#06090F;--panel:rgba(15,23,35,.72);--line:rgba(31,42,55,.65);
--text:#E6EDF3;--muted:#7B8A9E;--accent:#4CC38A;--bad:#F85149;--info:#6E9BF7;--warn:#E3B341}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font:15px/1.65 system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:0 28px}
header{padding:56px 0 26px}
h1{font-size:clamp(26px,3.6vw,38px);font-weight:800;letter-spacing:-.03em}
.sub{color:var(--muted);font-size:.95rem;margin-top:10px;max-width:64ch}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:13px;margin:26px 0}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:19px}
.stat .v{font-size:27px;font-weight:600;font-variant-numeric:tabular-nums}
.stat .l{font-size:11.5px;color:var(--muted);margin-top:5px}
section{padding:30px 0;border-top:1px solid var(--line)}
h2{font-size:19px;font-weight:700;letter-spacing:-.02em}
section .sub{font-size:.86rem;margin:4px 0 16px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{padding:8px 12px;text-align:left;color:var(--muted);font-weight:600;font-size:10.5px;
   text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid var(--line)}
td{padding:9px 12px;border-bottom:1px solid rgba(31,42,55,.5);font-variant-numeric:tabular-nums}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11.5px}
.pill{display:inline-block;font-size:11px;font-weight:600;padding:4px 10px;border-radius:999px}
.pill.ok{background:rgba(76,195,138,.12);color:var(--accent);border:1px solid rgba(76,195,138,.3)}
.pill.bad{background:rgba(248,81,73,.1);color:var(--bad);border:1px solid rgba(248,81,73,.3)}
.empty{color:var(--muted);font-size:13px;padding:14px 0}
.num{text-align:right}
footer{border-top:1px solid var(--line);padding:22px 0 40px;color:var(--muted);font-size:13px}
</style></head><body>
<div class="wrap">
  <header>
    <h1>One endpoint. Every provider. Full receipts.</h1>
    <p class="sub">Drop-in OpenAI-compatible gateway. Change <code>base_url</code> and
    <code>api_key</code> in any OpenAI client and get provider fallback, per-call
    telemetry, spend caps and honest cost estimates.</p>
  </header>
  <div class="stats" id="stats"></div>
  <section><h2>Spend by provider and model</h2>
    <p class="sub">Estimated from a published USD-per-1M-token table. Not billing reconciliation.</p>
    <div class="panel" id="by-model"></div></section>
  <section><h2>Recent requests</h2><p class="sub">Live, refreshed every three seconds.</p>
    <div class="panel" id="recent"></div></section>
  <footer>MIT &middot; model-agnostic by design</footer>
</div>
<script>
// No innerHTML: `model` comes from the request body and is attacker-controlled.
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}
function money(n) { return "$" + (Number(n) || 0).toFixed(5); }

function stat(value, label, cls) {
  const box = el("div", "stat");
  box.appendChild(el("div", "v" + (cls ? " " + cls : ""), value));
  box.appendChild(el("div", "l", label));
  return box;
}

function table(headings) {
  const t = el("table"), thead = el("thead"), hr = el("tr");
  headings.forEach(h => hr.appendChild(el("th", null, h)));
  thead.appendChild(hr); t.appendChild(thead); t.appendChild(el("tbody"));
  return t;
}

async function load() {
  const statsBox = document.getElementById("stats");
  const modelBox = document.getElementById("by-model");
  const recentBox = document.getElementById("recent");

  let d;
  try {
    const r = await fetch("/v1/usage", {headers: {"Authorization": "Bearer " + (localStorage.kkKey || "")}});
    if (!r.ok) throw new Error("HTTP " + r.status);
    d = await r.json();
  } catch (e) {
    statsBox.replaceChildren(el("p", "empty",
      "No gateway key in this browser, or the gateway is not running. "
      + "Start it with: uvicorn src.gateway:app"));
    return;
  }

  const failed = d.failed || 0;
  statsBox.replaceChildren(
    stat(d.total_requests || 0, "Requests"),
    stat("$" + (d.est_cost_usd || 0).toFixed(4), "Est. cost", null),
    stat(d.successful || 0, "Successful"),
    stat(failed, "Failed"),
    stat(Math.round(d.avg_latency_ms || 0), "Avg ms"),
    stat(d.total_tokens || 0, "Tokens")
  );

  const byModel = d.by_model || [];
  if (!byModel.length) {
    modelBox.replaceChildren(el("p", "empty", "No traffic yet."));
  } else {
    const t = table(["Provider", "Model", "Requests", "Cost"]);
    const tb = t.querySelector("tbody");
    byModel.forEach(function (row) {
      const tr = el("tr");
      tr.appendChild(el("td", null, row[0]));
      const mtd = el("td");
      mtd.appendChild(el("code", null, row[1]));
      tr.appendChild(mtd);
      tr.appendChild(el("td", null, row[2]));
      tr.appendChild(el("td", "num", money(row[3])));
      tb.appendChild(tr);
    });
    modelBox.replaceChildren(t);
  }

  const recent = d.recent || [];
  if (!recent.length) {
    recentBox.replaceChildren(el("p", "empty", "No requests yet."));
  } else {
    const t = table(["Time", "Key", "Model", "Status", "Latency", "Cost"]);
    const tb = t.querySelector("tbody");
    recent.forEach(function (row) {
      const tr = el("tr");
      tr.appendChild(el("td", null, new Date(row[0]).toLocaleTimeString()));
      tr.appendChild(el("td", null, row[1]));
      const mtd = el("td");
      mtd.appendChild(el("code", null, row[3]));
      tr.appendChild(mtd);
      const std = el("td");
      std.appendChild(el("span", "pill " + (row[4] === "ok" ? "ok" : "bad"), row[4]));
      tr.appendChild(std);
      tr.appendChild(el("td", null, Math.round(row[5]) + " ms"));
      tr.appendChild(el("td", "num", money(row[6])));
      tb.appendChild(tr);
    });
    recentBox.replaceChildren(t);
  }
}

load();
setInterval(load, 3000);
</script>
</body></html>"""
