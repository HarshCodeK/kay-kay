# Gateway limits and threat model

- API keys are stored as SHA-256 digests in a bounded in-memory registry. Keys and budget state are lost on restart; use a persistent credential store before treating this as a shared service.
- Key issuance requires the KAYKAY_ADMIN_TOKEN deployment secret and constant-time token comparison. Never expose the administrator token to the browser.
- Budget reservation is synchronized within one process and prevents concurrent calls from reserving more than the configured estimate.
- Token counts and prices are intentionally approximate. The included providers are deterministic stubs; this is not provider billing, a real LLM router, or a durable financial ledger.
- Unknown models and invalid token limits fail closed instead of silently using a default price.
- Usage telemetry retains only the latest 2,048 records to bound memory.
- Multi-worker deployment requires shared transactional budget accounting and shared credential storage.
