# KAY-KAY — LLM gateway reliability lab

KAY-KAY is a small gateway prototype that makes three behaviors explicit: provider fallback, API-key gating, and spend reservation before provider work. Its providers are deterministic stubs, so the system is inexpensive and reproducible to test without an LLM account.

## What is implemented

- API keys are high-entropy random values; only SHA-256 hashes are retained by the running process.
- Key issuance requires a configured admin token and uses constant-time token comparison.
- Chat requests require an issued key.
- Spend is reserved under a lock before a provider is called. A failed provider path releases the reservation; a successful path commits the estimate.
- Usage diagnostics are bounded to the latest 2,048 successful requests rather than growing without limit.
- A small browser UI demonstrates key issuance and a completion request; /docs exposes the API contract.
- /metrics reports per-route request counts, status codes, in-flight requests and recent latency percentiles.

## Architecture and accounting semantics

~~~text
request + valid key → estimate/reserve budget → primary provider → fallback if needed
                                                   ↓ success
                                      commit estimate and release reservation
~~~

The estimate uses configured price per thousand estimated tokens and combines prompt word count with requested max tokens. It is not actual provider token usage. The budget is global to the process, not per API key, and the demo providers only echo text; no real LLM is called.

## Quickstart

Requires Python 3.11+.

~~~bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
KAYKAY_ADMIN_TOKEN=local-admin-token uvicorn kaykay.app:app --reload
~~~

Open the root URL for the browser demo, /docs for the API, or /metrics for process-local measurements. To issue a key from the API:

~~~bash
curl -X POST http://127.0.0.1:8000/v1/keys -H 'X-Admin-Token: local-admin-token'
~~~

The admin token is only for key issuance and must never be embedded in public client code or a screenshot. The browser UI accepts it as a password input. In deployments, set KAYKAY_ADMIN_TOKEN as a secret. If it is missing, key issuance is intentionally disabled.

## API

- GET /health: liveness.
- GET /ready: readiness and whether key issuance is enabled.
- GET /metrics: per-process observations; counters reset when the process restarts.
- POST /v1/keys: admin-gated API-key issuance; maximum 1,000 keys per process.
- POST /v1/chat/completions: requires X-API-Key and accepts model, prompt and max_tokens.
- GET /docs: interactive OpenAPI docs.

## Test

~~~bash
pytest -q
python -m compileall -q src scripts
~~~

## Reproducible load test

See docs/RELIABILITY_LAB.md. Example:

~~~bash
KAYKAY_ADMIN_TOKEN=local-admin-token python scripts/load_test.py --base-url http://127.0.0.1:8000 --issue-api-key --requests 100 --concurrency 10 --output artifacts/load-10.json
curl http://127.0.0.1:8000/metrics
~~~

Reports contain client-observed throughput, p50/p95/p99/max latency, status codes, transport errors and error rate. They make no claim about server CPU, memory, real users, or capacity beyond the measured setup.

## Deployment

The root render.yaml defines a free Render demo. The blueprint deliberately marks KAYKAY_ADMIN_TOKEN as a secret to configure in the Render dashboard. Free services sleep after inactivity and cannot scale to multiple instances. Since the API-key registry and budget are in memory, restarts invalidate keys and reset the budget. This must not be sold as a durable billing/auth platform.

## Known limitations

The providers are placeholders, budget is process-global rather than per-key, API keys and budget do not survive restarts, there is no distributed rate limit or durable ledger, and metrics are local to one process. These limitations are intentional and documented rather than hidden behind claims of OpenAI compatibility or real provider economics.

## License

MIT. See LICENSE.
