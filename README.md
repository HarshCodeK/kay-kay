# KAY-KAY — LLM gateway policy lab

KAY-KAY is a small API gateway exercise focused on request validation, provider fallback, synchronized budget reservations, API-key issuance, and bounded telemetry.

## What it demonstrates

- API keys are issued only when the server-side KAYKAY_ADMIN_TOKEN is configured and supplied in the X-Admin-Token header.
- Gateway requests require an issued key in X-API-Key.
- The estimated request cost is reserved before provider execution; concurrent requests cannot reserve beyond the configured process-local budget.
- Unknown models and invalid token limits fail closed.
- Usage history is capped at 2,048 records.
- /health, /ready, and /metrics expose basic service state.

## Run locally

    python -m venv .venv
    source .venv/bin/activate
    pip install -e . pytest
    export KAYKAY_ADMIN_TOKEN='replace-with-a-local-secret'
    uvicorn kaykay.app:app --reload

Issue a development key using the admin header, then call /v1/chat/completions with the returned API key. Never put the admin secret in browser-side code.

## Test

    pytest -q
    python -m compileall -q src

Tests cover provider fallback, invalid model/token requests, bounded telemetry, admin-protected key issuance, and concurrent budget reservation.

## Honest limitations

The configured providers are deterministic stubs, not real LLM providers. Cost is a rough estimate rather than token-metered billing. Keys, usage and budget state are in memory and reset when the process restarts. Multi-worker deployment requires shared credentials and transactional shared budget accounting. See docs/RELIABILITY_AND_SECURITY.md.

## License

MIT.
