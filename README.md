# KAY-KAY — AI Infrastructure Platform

**We do not build AI. We decide how a company's software should use AI.**

Kay-Kay is an AI infrastructure layer: software connects to it once, and it
handles routing, execution, observation, governance, and measurement of AI
workloads — model-agnostic by design.

> Full product thesis: [PRODUCT_CONTEXT.md](PRODUCT_CONTEXT.md)

## Current milestone — Chapter 1: Connect + Observe

The first slice is a **drop-in OpenAI-compatible gateway**:

- **One endpoint** — `POST /v1/chat/completions` speaks the OpenAI wire
  format, so an existing app switches by changing `base_url` + `api_key`
- **Provider fallback** — requests route to Groq by default; any
  OpenAI-compatible provider (OpenAI, Together, vLLM, Ollama) joins the
  chain via env vars. Retries per provider, then falls back to the next
- **API-key auth** — gateway keys are SHA-256 hashed in SQLite; the admin
  key bootstraps from `KAYKAY_ADMIN_KEY` or is generated at first boot
- **Telemetry** — every call is logged (provider, model, latency, tokens,
  status) with a transparent cost estimate (USD/1M-token price table, no
  fake precision)
- **Usage API + dashboard** — `GET /v1/usage` and a Streamlit page over the
  same data

```
Your app (OpenAI SDK, any language)
        |
        |  base_url = http://localhost:8000/v1
        v
+---------------------------+
|      KAY-KAY GATEWAY      |   auth -> route -> retry/fallback
+---------------------------+        |
        |            |               v
        v            v         SQLite telemetry
      Groq        OpenAI      (tokens, latency, cost)
   (or any OpenAI-compatible provider)
```

## Quickstart

```bash
git clone https://github.com/HarshCodeK/kay-kay.git
cd kay-kay
pip install -r requirements.txt

cp .env.example .env
# set KAYKAY_ADMIN_KEY and GROQ_API_KEY

python -m uvicorn src.gateway:app --reload
```

Point any OpenAI client at it:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="kk-...")
r = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": "hello"}],
)
print(r.choices[0].message.content)
```

Check what happened:

```bash
curl -H "Authorization: Bearer kk-..." http://localhost:8000/v1/usage
python -m streamlit run usage_dashboard.py   # visual view of the same data
```

## Test suite (offline, no API keys needed)

```bash
python -m pytest tests/ -q
```

Covers: key issuance + auth round-trips, telemetry math, provider-missing
fallback, endpoint auth (401/502 paths), and the OpenAI-compatible response
shape.

## Roadmap

- **Chapter 1 — Connect + Observe** ← current (gateway, auth, telemetry, usage)
- **Chapter 2 — Optimize** — model routing by task type/cost, response caching,
  Skills (packaged repeated workflows)
- **Chapter 3 — Operate** — teams, budgets, policies, audit
- **Chapter 4 — Govern + Measure** — economic intelligence: where expensive
  intelligence is wasted on cheap tasks

## Development stance

Built incrementally around practical automation and measurable business
value — one coherent product story at a time, evidence before expansion
(see `PRODUCT_CONTEXT.md` §20).
