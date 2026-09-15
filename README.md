# kay-kay

> **We do not build AI. We decide how a company's software should use AI.**
> A universal AI operating layer — route, observe, optimize, govern. OpenAI-compatible gateway today. Full platform roadmap.

![python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)
![fastapi](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![sqlite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)
![license](https://img.shields.io/badge/license-MIT-lightgrey)
![tier](https://img.shields.io/badge/tier-A-E3B341)

---

## What this is

Kay-Kay is the infrastructure layer through which company software connects to, operates, routes, observes, optimizes, governs, and measures AI — without being tied to any single model provider.

```
Company Software
      │
      │  base_url = http://localhost:8000/v1
      ▼
┌────────────────────── KAY-KAY ──────────────────────┐
│  auth → route → execute → observe → optimize        │
└─────────────────────────┬───────────────────────────┘
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
      OpenAI          Anthropic       Local LLM
```

If OpenAI becomes better, we benefit. If open-source models become cheaper, we benefit. **We are AI infrastructure, not AI.**

---

## Chapter 1: Connect + Observe (built)

The first slice is a **drop-in OpenAI-compatible gateway**:

| Feature | What it does |
|---------|-------------|
| **One endpoint** | `POST /v1/chat/completions` speaks OpenAI wire format — switch by changing `base_url` |
| **Provider fallback** | Routes to Groq by default; any OpenAI-compatible provider joins the chain |
| **API-key auth** | Gateway keys are SHA-256 hashed in SQLite; admin key bootstraps from env |
| **Telemetry** | Every call logged: provider, model, latency, tokens, cost estimate |
| **Usage API** | `GET /v1/usage` returns spend by key, model, day |

---

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env   # set KAYKAY_ADMIN_KEY and GROQ_API_KEY
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
```

---

## Architecture

```
src/
├── gateway.py      # FastAPI app — the OpenAI-compatible endpoint
├── auth.py         # SHA-256 hashed keys, constant-time verify
├── providers.py    # Provider chain with retry + fallback
├── telemetry.py    # Per-request logging + usage aggregation
├── config.py       # Settings from env vars
└── tests/
    └── test_gateway.py   # 5 offline tests
```

---

## Evidence

| Metric | Value | Reproduce |
|---|---|---|
| source modules | 5 | `ls src/*.py` |
| tests | 5 offline | `python -m pytest tests/ -q` |
| auth method | SHA-256 + timing-safe compare | `grep timingSafeEqual src/auth.py` (JS) / `grep hmac src/auth.py` (Python) |
| provider fallback | chain-based | `PROVIDER_CHAIN=groq,openai` env var |
| wire format | OpenAI-compatible | `curl /v1/chat/completions` |

---

## The roadmap

| Chapter | What | Status |
|---------|------|--------|
| **1 — Connect + Observe** | Gateway, auth, telemetry, usage | ✅ Built |
| **2 — Optimize** | Model routing by task type/cost, response caching, Skills | Planned |
| **3 — Operate** | Teams, budgets, policies, audit | Planned |
| **4 — Govern + Measure** | Economic intelligence: where expensive intelligence is wasted on cheap tasks | Planned |

The moat is not the gateway. It is the platform's understanding of how a company's AI workload behaves and the accumulated ability to choose better paths.

---

## What this is NOT

- No model routing yet (Chapter 1 routes to the configured provider)
- No team/budget management (Chapter 3)
- No economic intelligence dashboard (Chapter 4)
- Single-process, single-host

---

## License

MIT
