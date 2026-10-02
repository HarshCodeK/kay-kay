"""A bounded tool-calling agent that reaches the model through this gateway.

Four properties, each deliberate:

1. **It routes through the gateway.** run_agent calls providers.chat, the same
   function every other client uses. So agent turns are subject to the same spend
   caps and land in the same telemetry table. An agent that called the provider
   directly would be exactly the unbounded-spend hole this project exists to
   close.

2. **The tools are deterministic Python.** The model decides *when* to call a
   tool and supplies its arguments; the tool computes the result. A tool whose
   output the model can fabricate is not a tool, it is a suggestion.

3. **The loop is bounded.** max_rounds caps iterations, so a model that only
   ever calls tools terminates instead of spending without limit.

4. **It fails closed.** A provider failure returns a typed result with the trace
   intact, never an exception through the API.
"""
import json
import re
import time

from src import providers

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Search the supplied text with a regex and return matching lines. Use for finding errors, ids or amounts in a log the user provided.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Python regex."},
                    "text": {"type": "string"},
                },
                "required": ["pattern", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_matches",
            "description": "Count how many times a pattern matches the supplied text.",
            "parameters": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}, "text": {"type": "string"}},
                "required": ["pattern", "text"],
            },
        },
    },
]

MAX_ROUNDS = 4
MAX_PATTERN = 200
MAX_TEXT = 20_000
MAX_HITS = 25

SYSTEM = (
    "You analyse text the user supplies, using two tools. "
    "Use a tool when it gives you information you do not already have. "
    "Do not guess counts or quotes -- call the tool. "
    "When you have the answer, reply in prose with no further tool calls."
)


def _tool(name: str, args: dict) -> dict:
    """Run one tool. Failures return as data, never as exceptions: a raising
    tool would abort the loop and lose the trace, which is the part worth keeping."""
    pattern = str(args.get("pattern", ""))
    text = str(args.get("text", ""))[:MAX_TEXT]

    if not pattern:
        return {"ok": False, "error": "empty pattern"}
    if len(pattern) > MAX_PATTERN:
        return {"ok": False, "error": "pattern too long"}
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return {"ok": False, "error": f"bad regex: {e}"}

    if name == "count_matches":
        return {"ok": True, "matches": len(rx.findall(text))}
    if name == "search_text":
        hits = []
        for i, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                hits.append({"line": i, "text": line.strip()[:200]})
                if len(hits) >= MAX_HITS:
                    break
        return {"ok": True, "count": len(hits), "hits": hits}
    return {"ok": False, "error": f"unknown tool {name!r}"}


def run(task: str, model_id: str, max_rounds: int = MAX_ROUNDS, conversation: str = "", chat_fn=None) -> dict:
    """Run one agent turn. Never raises for a provider failure."""
    started = time.time()
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user",
         "content": f"{conversation}\n\nTask: {task}" if conversation else f"Task: {task}"},
    ]

    trace: list = []
    chat = chat_fn or providers.chat
    answer = ""
    rounds = 0

    for round_num in range(1, max_rounds + 1):
        t0 = time.time()
        try:
            response, provider = chat({
                "model": model_id, "messages": messages,
                "tools": TOOLS, "tool_choice": "auto", "temperature": 0.2,
            })
        except providers.ProviderError as e:
            return {
                "answer": f"Gateway unavailable: {e}",
                "rounds": rounds, "mode": "provider_error",
                "trace": trace, "model": model_id,
                "total_ms": round((time.time() - started) * 1000),
            }

        rounds = round_num
        message = response["choices"][0]["message"]
        calls = message.get("tool_calls") or []

        if not calls:
            answer = message.get("content") or ""
            trace.append({"round": round_num, "phase": "final",
                          "latency_ms": round((time.time() - t0) * 1000)})
            break

        messages.append({
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": calls,
        })

        steps = []
        for call in calls:
            fn = call.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            result = _tool(fn.get("name", ""), args)
            steps.append({"tool": fn.get("name"), "args": args, "result": result})
            messages.append({
                "role": "tool", "tool_call_id": call.get("id", ""),
                "content": json.dumps(result)[:4000],
            })

        trace.append({"round": round_num, "phase": "act", "provider": provider,
                      "tool_calls": steps,
                      "latency_ms": round((time.time() - t0) * 1000)})
    else:
        answer = ("Reached the maximum number of rounds without a final answer. "
                  "The trace shows what was tried.")

    return {
        "answer": answer, "rounds": rounds, "mode": "agent", "trace": trace,
        "model": model_id, "total_ms": round((time.time() - started) * 1000),
    }


def manifest() -> list:
    return [{"name": t["function"]["name"], "description": t["function"]["description"]}
            for t in TOOLS]
