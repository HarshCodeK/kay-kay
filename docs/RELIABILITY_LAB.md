# Reliability lab

The load generator measures client-observed HTTP behavior; the /metrics endpoint measures traffic seen by one application process. They are complementary, not interchangeable.

## Local setup

~~~bash
pip install -e .
KAYKAY_ADMIN_TOKEN=local-admin-token uvicorn kaykay.app:app --host 127.0.0.1 --port 8000
~~~

Issue one API key, then ramp the workload gradually:

~~~bash
KAYKAY_ADMIN_TOKEN=local-admin-token python scripts/load_test.py --base-url http://127.0.0.1:8000 --issue-api-key --requests 100 --concurrency 10 --output artifacts/load-10.json
KAYKAY_ADMIN_TOKEN=local-admin-token python scripts/load_test.py --base-url http://127.0.0.1:8000 --issue-api-key --requests 500 --concurrency 25 --output artifacts/load-25.json
curl http://127.0.0.1:8000/metrics
~~~

The report contains p50/p95/p99/max latency, throughput, status codes, transport failures and error rate. It does not include the admin token or the issued API key. Do not upload raw terminal logs if they contain secrets. The generator uses a bounded worker pool, caps a run at 100,000 requests and 10,000 configured in-flight requests, and treats only 2xx responses as successful; these are client-side safety bounds, not target-capacity claims.

## What to measure

- Save the Git commit, hosting plan, region, cold/warm state, request count, concurrency and timestamp with every run. Repeat each level at least three times.
- Observe 401 (missing/invalid API key), 402 (budget cap), 429 (process key cap), 502 (all providers failed), 5xx and transport timeouts separately.
- `/metrics` only describes this process and resets on restart. It does not measure host CPU or memory; use the hosting dashboard/logs for those.
- Concurrency means in-flight requests, not real users or sessions. Do not claim capacity beyond the actual tested host and request mix.

## Important model and billing limitations

The primary and fallback providers are deterministic stubs. The estimated spend is a reservation calculation, not a real provider invoice or token-usage measurement. The budget and API-key registry are process-local and shared by all keys; restart resets them and invalidates issued keys. The usage diagnostic list is bounded to the latest 2,048 successful calls. This illustrates concurrency-safe reservation/fallback logic, not a durable billing implementation.

## Deployment limits

The Render blueprint is for a free demo. Free web services sleep after inactivity, use ephemeral storage, and cannot scale beyond one instance. The process-local key and budget state is therefore deliberately not represented as production-grade. Do not run uncontrolled load tests against shared/public services.
