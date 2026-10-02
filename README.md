# KAY-KAY — LLM Gateway

An OpenAI-compatible gateway with provider fallback, API keys, conservative spend reservations and per-request telemetry. Plus a bounded tool-calling agent whose provider calls pass through the same accounting path.

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="kk-...")
```

That is the entire integration. Everything else happens on the way through.

**Python · FastAPI · AI/LLMs · REST APIs · AI Agents**

---

## What it does

| Capability | Where |
|---|---|
| Drop-in OpenAI endpoint | `POST /v1/chat/completions` |
| Provider fallback + retry | `src/providers.py` |
| API keys, hashed | `src/auth.py` |
| Spend caps | `402` before a request whose conservative worst-case reservation would exceed the remaining budget |
| Per-request telemetry | `src/telemetry.py` |
| Usage dashboard | `/dashboard`, or `streamlit run usage_dashboard.py` |
| Tool-calling agent | `POST /v1/agent` |

---

## The spend boundary is enforced before each provider call

Each request reserves a conservative worst-case cost before it is sent upstream. The reservation includes a bounded `max_tokens` value, and SQLite makes the reservation atomic so concurrent requests cannot both consume the same remaining budget. Actual provider usage is recorded afterward and the unused reservation is released. If the provider omits token-usage fields, KAY-KAY fails closed and retains the reservation until expiry instead of treating the call as free.

Agent turns use the same metered path on every round, and `max_rounds` is clamped to the configured bound.

**The tools are deterministic Python.** The model decides *when* to call a tool
and supplies its arguments; the tool computes the result. A tool whose output the
model can fabricate is not a tool, it is a suggestion.

Measured, 6-line log:

```
mode: agent | rounds: 2 | total_ms: 3770
  CALL count_matches({"pattern": "failed login", ...})  -> {"matches": 3}
  CALL search_text({"pattern": "ERROR.*on (node-\d+)"}) -> {"count": 2}
ANSWER: There are 3 failed login attempts... hosts: node-12, node-07
```

---

## Three decisions worth explaining

**Retry policy.** A 4xx that is not 429 breaks to the next provider
immediately. Retrying a 400 cannot succeed; it just burns the budget. Timeouts
and transport errors are transient and do get retried.

**SHA-256, not bcrypt.** These keys are `secrets.token_urlsafe(24)` — 192 bits
of entropy. There is no dictionary to attack, so a deliberately slow KDF buys
latency and nothing else. bcrypt would be right if a human chose the password.

*Then state the gap yourself:* a lookup by hash is still a database comparison,
which is where timing can leak. `compare_digest` guards the in-process
comparison but not the SQL. Closing that properly means comparing against every
stored hash, or using a blind index.

**The dashboard has no `innerHTML`.** The model name in every row comes from the
request body, so it is attacker-controlled. The page is built with
`createElement` and `textContent`, so a request with `model` set to
`<img onerror=...>` renders as that literal string. There is a test asserting
`innerHTML` never appears in the shipped JavaScript.

---

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env          # add GROQ_API_KEY
uvicorn src.gateway:app --reload
open http://localhost:8000/docs
```

`GET /health` reports which providers are actually configured — a gateway with no
provider returns 200 there and then 502 on every call, which is confusing to
debug.

```bash
streamlit run usage_dashboard.py   # telemetry view
```

---

## Endpoints

| Method | Path | What |
|---|---|---|
| POST | `/v1/chat/completions` | OpenAI-compatible completion |
| GET | `/v1/models` | Live model ids |
| POST | `/v1/agent` | Bounded agent run; every provider turn is metered |
| GET | `/v1/agent/tools` | Agent tool manifest |
| GET | `/v1/usage` | Usage summary |
| GET | `/v1/usage/{key_id}` | Per-key usage (admin) |
| GET/POST | `/v1/keys` | List / issue keys (admin) |
| POST | `/v1/keys/{id}/revoke` | Revoke (admin) |
| GET | `/dashboard` | HTML usage dashboard |
| GET | `/health` | Liveness + configured providers |

---

## Interview Q&A

`docs/INTERVIEW_QA.md` — the pitch, the trust decisions, and the questions an
interviewer will actually ask, with answers grounded in this code.

## Known limits

- **Single-machine, local.** No rate limiting and no lockout after repeated
  failures. Fine bound to localhost, not exposed to a network.
- **Cost is an estimate** from published per-token rates, not billing. The reservation is deliberately conservative so the spend cap is a safety boundary, not a billing ledger.
- **The agent's tools are read-only.** Regex over text the caller supplies.
  Adding a write tool means adding a trust boundary, not just a function.
