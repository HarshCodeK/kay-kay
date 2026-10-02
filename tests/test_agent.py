"""Agent tests — fully offline, no provider calls.

`run_agent` is the only thing that talks to a provider, so it is stubbed at
`providers.call_chat_completion`. Everything below it — tool dispatch, the
round cap, the trace, the error path — is real code.

Run from repo root:  python -m pytest tests/ -q
"""
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import agent as agent_mod  # noqa: E402
from src import config  # noqa: E402


# ---------------------------------------------------------------------------
# Tool dispatch — deterministic, no LLM involved
# ---------------------------------------------------------------------------
class TestTools:
    def test_search_text_finds_matching_lines(self):
        text = "line one\nERROR disk full\nline three\nERROR timeout"
        out = agent_mod._call_tool("search_text", {"pattern": "error", "text": text})
        assert out["ok"] is True
        assert out["count"] == 2
        assert out["hits"][0]["line"] == 2

    def test_count_matches(self):
        out = agent_mod._call_tool(
            "count_matches", {"pattern": r"\d+", "text": "a1 b22 c333"})
        assert out["ok"] is True
        assert out["matches"] == 3

    def test_search_is_case_insensitive(self):
        out = agent_mod._call_tool("search_text", {"pattern": "timeout", "text": "TIMEOUT"})
        assert out["count"] == 1

    def test_bad_regex_is_data_not_an_exception(self):
        out = agent_mod._call_tool("search_text", {"pattern": "[unclosed", "text": "x"})
        assert out["ok"] is False
        assert "bad regex" in out["error"]

    def test_empty_pattern_rejected(self):
        out = agent_mod._call_tool("count_matches", {"pattern": "", "text": "x"})
        assert out["ok"] is False

    def test_overlong_pattern_rejected(self):
        out = agent_mod._call_tool(
            "count_matches", {"pattern": "a" * (agent_mod.MAX_PATTERN_LEN + 1), "text": "x"})
        assert out["ok"] is False
        assert "too long" in out["error"]

    def test_unknown_tool_rejected(self):
        out = agent_mod._call_tool("rm_rf", {"pattern": "a", "text": "b"})
        assert out["ok"] is False
        assert "unknown tool" in out["error"]

    def test_hit_count_is_capped(self):
        text = "\n".join("err" for _ in range(500))
        out = agent_mod._call_tool("search_text", {"pattern": "err", "text": text})
        assert len(out["hits"]) <= agent_mod.MAX_HITS

    def test_manifest_lists_every_tool(self):
        manifest = agent_mod.tool_manifest()
        assert {t["name"] for t in manifest} == {"search_text", "count_matches"}


# ---------------------------------------------------------------------------
# The loop, with the provider stubbed
# ---------------------------------------------------------------------------
def _text_response(content):
    return {"choices": [{"message": {"content": content, "tool_calls": None}}]}, "groq"


def _tool_response(name, args):
    call = {"id": "c1", "type": "function",
            "function": {"name": name, "arguments": __import__("json").dumps(args)}}
    return {"choices": [{"message": {"content": None, "tool_calls": [call]}}]}, "groq"


class TestAgentLoop:
    def test_answers_without_using_a_tool(self, monkeypatch):
        monkeypatch.setattr(agent_mod.providers, "call_chat_completion",
                            lambda body: _text_response("Two errors."))
        result = agent_mod.run_agent("how many errors?")
        assert result["answer"] == "Two errors."
        assert result["rounds"] == 1
        assert result["mode"] == "agent"

    def test_uses_a_tool_then_answers(self, monkeypatch):
        calls = []

        def fake(body):
            calls.append(body)
            if len(calls) == 1:
                return _tool_response("count_matches", {"pattern": "err", "text": "err err"})
            return _text_response("There are 2 matches.")

        monkeypatch.setattr(agent_mod.providers, "call_chat_completion", fake)
        result = agent_mod.run_agent("count err")
        assert result["answer"] == "There are 2 matches."
        assert result["rounds"] == 2
        act = [t for t in result["trace"] if t["phase"] == "act"]
        assert act and act[0]["tool_calls"][0]["result"]["matches"] == 2

    def test_tools_are_offered_to_the_provider(self, monkeypatch):
        seen = {}

        def fake(body):
            seen.update(body)
            return _text_response("done")

        monkeypatch.setattr(agent_mod.providers, "call_chat_completion", fake)
        agent_mod.run_agent("anything")
        assert len(seen["tools"]) == 2
        assert seen["tool_choice"] == "auto"

    def test_round_cap_is_enforced(self, monkeypatch):
        """A model that always calls a tool must still terminate."""
        monkeypatch.setattr(agent_mod.providers, "call_chat_completion",
                            lambda body: _tool_response("count_matches",
                                                       {"pattern": "a", "text": "aaa"}))
        result = agent_mod.run_agent("loop forever", max_rounds=3)
        assert result["rounds"] == 3
        assert "maximum number of rounds" in result["answer"]

    def test_provider_failure_returns_trace_not_exception(self, monkeypatch):
        def boom(body):
            raise agent_mod.providers.ProviderError("all providers failed")

        monkeypatch.setattr(agent_mod.providers, "call_chat_completion", boom)
        result = agent_mod.run_agent("anything")
        assert result["mode"] == "provider_error"
        assert "Gateway unavailable" in result["answer"]
        assert result["trace"] == []

    def test_malformed_tool_arguments_do_not_crash_the_loop(self, monkeypatch):
        calls = []

        def fake(body):
            calls.append(body)
            if len(calls) == 1:
                return ({"choices": [{"message": {"content": None, "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "search_text", "arguments": "{not json"}}]}}]}, "groq")
            return _text_response("Recovered.")

        monkeypatch.setattr(agent_mod.providers, "call_chat_completion", fake)
        result = agent_mod.run_agent("x")
        assert result["answer"] == "Recovered."

    def test_default_model_is_advertised(self):
        """The agent must not default to a model the gateway does not list."""
        advertised = {m["id"] for m in config.advertised_models()}
        assert config.DEFAULT_MODELS[0] in advertised
        # Ids must be unique, or discovery is ambiguous.
        assert len(advertised) == len(config.DEFAULT_MODELS)


# ---------------------------------------------------------------------------
# No retired model may be pinned
# ---------------------------------------------------------------------------
def test_no_retired_model_in_source():
    """Guard: a retired id must not reappear as a default anywhere."""
    import ast

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    retired = {"llama-3.3-70b-versatile", "llama-4-scout-17b-16e-instruct",
               "llama-3.1-8b-instant", "qwen/qwen3-32b", "qwen/qwen3.6-27b"}
    offenders = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "tests"}]
        for name in filenames:
            if not name.endswith(".py") or name == "config.py":
                continue
            with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                    body = getattr(node, "body", None)
                    if (body and isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant)
                            and isinstance(body[0].value.value, str)):
                        docstrings.add(id(body[0].value))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and id(node) not in docstrings):
                    for dead in retired:
                        if dead in node.value:
                            offenders.append(f"{name}:{node.lineno} -> {dead}")

    assert not offenders, f"retired model pinned in code: {offenders}"


def test_every_advertised_model_is_priced():
    """A model with no price silently falls back and mis-states cost."""
    for model_id in config.DEFAULT_MODELS:
        assert config.is_priced(model_id), f"{model_id} has no price entry"
