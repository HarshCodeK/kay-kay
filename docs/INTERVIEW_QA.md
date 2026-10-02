# Interview Q&A — Kay-Kay LLM Gateway

## The 30-second pitch

"Kay-Kay is an OpenAI-compatible LLM gateway. Any OpenAI client can point at it
with two lines changed. On the way through, it enforces API keys, per-key spend
caps, provider fallback, and per-request telemetry. One of its endpoints is a
bounded tool-calling agent that has to go through the same gateway, so agent
spend is capped like everything else."

## Q: Why an OpenAI-compatible shape?

A: It is the existing client contract. A client using `base_url` + `api_key`
switches two lines and every feature the gateway adds — caps, fallback,
telemetry — comes for free. Designing a custom protocol would mean writing a
client library nobody would adopt.

## Q: What exactly does "fallback" mean here?

A: `providers.chat` iterates a configured chain (GROQ_API_KEY first, then any
`*_BASE_URL` + `*_API_KEY` pairs). For each provider it retries up to
MAX_RETRIES, but only transient failures: timeouts and transport errors. A 4xx
that is not 429 breaks to the next provider immediately — retrying a 400 cannot
succeed, it just burns budget. Every provider speaks the same chat-completions
shape, so the gateway converts nothing; it only decides where to send.

## Q: Why SHA-256 for API keys instead of bcrypt?

A: The keys are `secrets.token_urlsafe(24)` — 192 bits of entropy. There is no
dictionary to attack, so a deliberately slow KDF buys latency and nothing else.
bcrypt is right when a human chooses a password; these keys are machine-generated.
The honest caveat: a lookup by hash is still a SQL comparison where timing can
leak. `compare_digest` guards the in-process comparison, not the SQL. Closing it
means comparing against every stored hash or a blind index. I state the gap
rather than hide it.

## Q: How are spend caps enforced?

A: Each request is charged to its key from the telemetry table. Before each provider call, the gateway computes a conservative worst-case cost from the bounded `max_tokens` plus a conservative prompt-size upper bound. It atomically reserves that amount in SQLite against the key's cap; if the reservation would exceed the remaining budget, the request gets HTTP 402. Actual token usage is recorded afterward and the unused reservation is released. If a successful provider response omits token-usage fields, the gateway fails closed and keeps the reservation until expiry rather than releasing unaccounted spend.

## Q: Why must the agent route through the gateway?

A: So it inherits the same controls. `agent.run` calls `providers.chat`, the
same function every client uses. An agent that called the provider SDK directly
would be exactly the unbounded-spend hole the project exists to close. There is
a test asserting agent.py never imports the provider SDK.

## Q: Why deterministic tools?

A: The model decides *when* to call a tool and supplies the arguments; a Python
function computes the result. A tool whose output the model can fabricate is
not a tool, it is a suggestion. This is what makes the agent's claims auditable:
counts and quotes in the final answer trace back to a `re.findall`, not the
model's memory.

## Q: What bounds the agent loop?

A: `max_rounds` (default 4). A model that only ever calls tools terminates
instead of spending without limit. A provider failure returns a typed result
with the trace intact — the API never raises. Tool inputs are capped (pattern
length, text size, hit count) so a single call cannot flood the context.

## Q: How is the telemetry table used?

A: Successful provider calls write rows to the `requests` table with key, provider, model, status, latency, token counts, and estimated cost. A separate `budget_reservations` table holds temporary pre-request reservations so concurrent calls cannot consume the same remaining budget. `/v1/usage` aggregates the recorded request history.

## Q: Why is the model name in the dashboard XSS-safe?

A: The model name comes from the request body, so it is attacker-controlled.
The dashboard builds rows with `createElement` and `textContent`, never
`innerHTML`, so `<img onerror=...>` in a model name renders as literal text.
A test asserts `innerHTML` never appears in the shipped JavaScript.

## Q: Why hash keys but keep admin separate?

A: The admin row is upserted from `KAYKAY_ADMIN_KEY` on startup; only the
bootstrap key can issue/revoke keys. Key material is never stored in plaintext,
and rotation is "change the env var, restart" — no key file to lose.

## Q: What happens with no provider configured?

A: `GET /health` reports `providers_configured: []` and every call returns 502
with a message naming which env vars to set. The gateway never silently
succeeds with no way to serve a request — the failure is explicit and loud.

## Q: SQLite again — why no Postgres?

A: Single-process, local, one writer. Postgres would run as a second service
with its own lifecycle. SQLite matches the deployment reality; the schema is
created idempotently on startup.

## Q: What would you add before exposing this to a network?

A: Per-IP rate limiting, lockout on repeated 401s, HTTPS termination, per-key
rate limits, and a real billing ledger — the current cost figure is an estimate
from published per-token rates. Multi-process would also mean moving SQLite off
the critical path or accepting write contention.

## Q: What if two requests arrive at the same time?

A: SQLite `BEGIN IMMEDIATE` serializes the reservation transaction. The second request sees the first request's reservation before it can reserve its own budget, so both cannot reserve the same remaining cap.

## Q: What if the provider omits token usage?

A: The gateway fails closed. It records an error and retains the reservation until expiry instead of releasing an unaccounted request. That prevents a provider response without usage metadata from becoming a free-spend path.

## Q: How is this tested?

A: Offline tests cover key issue/verify/revoke, spend-cap handling, provider fallback and retry policy with faked HTTP, agent loop termination and trace shape, dashboard script safety, and the atomic budget-reservation path. No test touches the network. key issue/verify/revoke, spend-cap 402, provider fallback
and retry policy with faked HTTP, agent loop termination and trace shape,
dashboard script safety. No test touches the network.
