"""Agent runtime — a bounded tool-calling loop that talks through the gateway.

Why this file exists
--------------------
The resume lists "AI Agents" under this project. Until now there was no agent
in the repository — just a proxy — so that word had nothing behind it.

This adds one, and it is deliberately small.

Design constraints
------------------
* **It routes through the gateway.** `run_agent` does not call Groq directly;
  it calls `providers.call_chat_completion`, so every agent request is counted
  by the spend caps and lands in the same telemetry table as any other call.
  That is the point of the project: the gateway is not a side feature, it is
  the path the agent takes.

* **Tools are deterministic Python, not LLM-written.** `read_file` runs a
  regex over text the caller supplies. The model decides *when* to call it, not
  *what the result is*. A tool whose output the model can fabricate is not a
  tool, it is a suggestion.

* **The loop is bounded.** `max_rounds` caps iterations and every round is
  logged. An unbounded agent loop is a way to spend money without limit, which
  is exactly the failure this gateway exists to prevent.

* **It fails closed.** If the gateway is unreachable the agent returns a typed
  error and the trace, never an exception through the API.
"""
from __future__ import annotations

import json
import re
import time

from src import providers
from src.config import DEFAULT_MODELS

# ---------------------------------------------------------------------------
# Tool definitions — OpenAI function-calling shape, passed straight through
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": (
                "Search the supplied text with a regular expression and return "
                "matching lines. Use for finding errors, ids or amounts in a "
                "log or document the user provided."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Python regex."},
                    "text": {"type": "string", "description": "Text to search."},
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
                "properties": {
                    "pattern": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["pattern", "text"],
            },
        },
    },
]

MAX_ROUNDS_DEFAULT = 4
MAX_PATTERN_LEN = 200
MAX_TEXT_LEN = 20_000
MAX_HITS = 25


class AgentError(RuntimeError):
    """The agent could not complete. `trace` still holds what it did."""


def _call_tool(name: str, args: dict) -> dict:
    """Run one tool. Failures come back as data, never as exceptions.

    A tool that raises would abort the loop mid-flight and lose the trace —
    which is the part worth keeping.
    """
    pattern = str(args.get("pattern", ""))
    text = str(args.get("text", ""))[:MAX_TEXT_LEN]

    if not pattern:
        return {"ok": False, "error": "empty pattern"}
    if len(pattern) > MAX_PATTERN_LEN:
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


def run_agent(task: str, model: str | None = None, max_rounds: int | None = None,
              conversation: str = "") -> dict:
    """Run a bounded tool-calling agent turn.

    Returns {answer, rounds, mode, trace, model}. Never raises for a provider
    failure — the error is reported in `answer` with the trace intact.
    """
    max_rounds = max_rounds or MAX_ROUNDS_DEFAULT
    model = model or DEFAULT_MODELS[0]
    started = time.time()

    system = (
        "You are a careful analysis assistant with two tools over text the user "
        "supplied. Use a tool when it gives you information you do not already "
        "have. Do not guess counts or quotes — call the tool. When you have the "
        "answer, reply with prose and no further tool calls."
    )
    # Provider payloads are dict[str, Any]; Pyright would otherwise infer
    # dict[str, str] from the first append and reject the nested tool_calls
    # list. This is JSON from a network response — Any is the honest type.
    messages: list = [
        {"role": "system", "content": system},
        {"role": "user",
         "content": f"{conversation}\n\nTask: {task}" if conversation else f"Task: {task}"},
    ]

    trace: list = []
    answer = ""
    rounds_used = 0

    for round_num in range(1, max_rounds + 1):
        t0 = time.time()
        try:
            resp, provider = providers.call_chat_completion(
                {"model": model, "messages": messages,
                 "tools": TOOLS, "tool_choice": "auto", "temperature": 0.2}
            )
        except providers.ProviderError as e:
            return {
                "answer": f"Gateway unavailable: {e}",
                "rounds": round_num - 1,
                "mode": "provider_error",
                "trace": trace,
                "model": model,
                "total_ms": round((time.time() - started) * 1000),
            }

        rounds_used = round_num
        message = resp["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            answer = message.get("content") or ""
            trace.append({"round": round_num, "phase": "final",
                          "latency_ms": round((time.time() - t0) * 1000)})
            break

        # Coerce content to str: the provider may send null when it emits only
        # tool calls, and the history must stay well-typed for the next round.
        messages.append({
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": tool_calls,
        })

        step_results = []
        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}

            result = _call_tool(name, args)
            step_results.append({"tool": name, "args": args, "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": json.dumps(result)[:4000],
            })

        trace.append({
            "round": round_num,
            "phase": "act",
            "provider": provider,
            "tool_calls": step_results,
            "latency_ms": round((time.time() - t0) * 1000),
        })
    else:
        answer = ("Reached the maximum number of rounds without a final answer. "
                  "The trace above shows what was tried.")

    return {
        "answer": answer,
        "rounds": rounds_used,
        "mode": "agent",
        "trace": trace,
        "model": model,
        "total_ms": round((time.time() - started) * 1000),
    }


def tool_manifest() -> list:
    """Tool names and descriptions, for the dashboard and for /v1/agent/tools."""
    return [
        {"name": t["function"]["name"], "description": t["function"]["description"]}
        for t in TOOLS
    ]
