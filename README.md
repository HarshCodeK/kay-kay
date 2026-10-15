# KAY-KAY — LLM Gateway Prototype

KAY-KAY is a small FastAPI gateway prototype demonstrating provider fallback, API-key hashing, conservative budget reservation, and usage telemetry. Its provider functions are deterministic stubs, so the core flow can be tested without an LLM account.

**Stack:** Python, FastAPI, Pydantic, HTTPX (declared dependency), pytest.

## Problem and intended use

An application calling multiple LLM providers needs a single boundary for request validation, provider selection/fallback, budget enforcement, and usage reporting. This repository isolates a few of those control-flow ideas in a small, inspectable implementation. It is a learning prototype, not a production gateway or billing ledger.

## Request flow

`POST /v1/chat/completions → API-key check → cost estimate → atomic budget reservation → primary provider → fallback provider if needed → commit or release reservation → response`

The `Gateway` protects the budget reservation and usage list with a thread lock. It reserves estimated cost before provider work, releases the reservation if all providers fail, and charges the estimate when a provider succeeds. The current estimate is a simple word-count-plus-max-token heuristic; it is not provider-reported token usage or an invoice-grade cost.

## API

- `GET /health` — process-level health and configured provider count.
- `POST /v1/keys` — issues a random API key and stores only its SHA-256 hash in process memory.
- `POST /v1/chat/completions` — requires the `X-API-Key` header and accepts `model`, `prompt`, and bounded `max_tokens`.

Example:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn kaykay.app:app --host 0.0.0.0 --port 8000
```

Issue a demo key:

```bash
curl -X POST http://localhost:8000/v1/keys
```

Use the returned key in a request:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: REPLACE_WITH_KEY" \
  -d '{"model":"default","prompt":"Explain a timeout briefly","max_tokens":64}'
```

Run tests with `pytest -q`.

## Budget and fallback semantics

- A reservation is made under a lock before any provider is called.
- Providers are tried in dictionary insertion order.
- A successful provider consumes the reserved estimate.
- If every provider raises, the reservation is released and the request fails.
- Budget exhaustion returns HTTP 402; total provider failure returns HTTP 502.
- Usage is held in memory and disappears when the process restarts.

These semantics are intentionally simple and should not be mistaken for a distributed quota system. A single process lock cannot coordinate budgets across multiple workers or replicas.

## Security and correctness limitations

The current key-issuance endpoint is public and has no identity or authorization gate. Issued key hashes are stored only in process memory, so keys are lost on restart and do not work consistently across replicas. SHA-256 hashing is useful here for avoiding plaintext key storage, but the prototype does not provide key rotation, revocation, tenant isolation, durable usage records, audit trails, or abuse controls. Do not expose this implementation as an unrestricted public service or put real provider secrets behind it.

The provider functions currently echo a deterministic response rather than calling real LLM APIs. The returned cost is an estimate, not measured provider billing. The gateway does not yet implement request deadlines, provider-specific retries, circuit breaking, rate limits, structured output validation, or real token accounting.

## Capacity and load testing

No measured concurrency or throughput claim is made. To benchmark responsibly, record the exact commit, machine/hosting plan, process worker count, duration, request mix, and key setup. Measure throughput, p50/p95/p99 latency, error rate, budget-rejection rate, provider-fallback rate, CPU/RAM, and reservation/spend invariants under concurrency.

Start with the deterministic providers to isolate API and locking behavior. Then test injected provider latency/failures separately. A benchmark of deterministic stubs does **not** establish capacity for a real LLM provider. Validate that concurrent reservations never allow `spent + reserved` to exceed the configured budget, and verify that failed requests release reservations. Simulated clients are load-test traffic, not real customers.

## Next engineering milestones

1. Add tests for concurrent reservations, reservation release, and spend invariants.
2. Protect key issuance and add key revocation/rotation.
3. Move keys, budget state, and usage records to durable shared storage before multi-worker deployment.
4. Add bounded request/provider timeouts and explicit provider health telemetry.
5. Add rate limiting and per-tenant quotas.
6. Integrate a real provider behind an interface, then test with a strict spend cap and secret-safe logging.

## License

MIT.
