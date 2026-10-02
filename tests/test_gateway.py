"""Offline tests. No network, no API key.

Run:  python -m pytest tests/ -q
"""
import importlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """Reload config/auth/telemetry against a throwaway database."""
    monkeypatch.setenv("KAYKAY_DB", str(tmp_path / "nested" / "kk.db"))
    monkeypatch.setenv("KAYKAY_ADMIN_KEY", "kk-test-admin")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    import src.config as config
    importlib.reload(config)
    import src.auth as auth
    importlib.reload(auth)
    import src.telemetry as telemetry
    importlib.reload(telemetry)
    import src.providers as providers
    importlib.reload(providers)
    yield config, auth, telemetry, providers
    monkeypatch.undo()
    importlib.reload(config)


# ---------------------------------------------------------------------------
# Startup: the two traps that made a fresh checkout look broken
# ---------------------------------------------------------------------------
class TestStartup:
    def test_nested_db_directory_is_created(self, fresh):
        config, *_ = fresh
        assert os.path.isdir(os.path.dirname(config.DB_PATH))

    def test_env_admin_key_authenticates(self, fresh):
        _, auth, *_ = fresh
        auth.init()
        assert auth.verify("kk-test-admin") == "admin"

    def test_env_key_overrides_a_stale_seeded_key(self, fresh):
        """The trap: seed with one key, restart with another, get 401 forever."""
        config, auth, *_ = fresh
        os.environ["KAYKAY_ADMIN_KEY"] = "kk-first-key"
        importlib.reload(config); importlib.reload(auth)
        auth.init()
        assert auth.verify("kk-first-key") == "admin"

        os.environ["KAYKAY_ADMIN_KEY"] = "kk-second-key"
        importlib.reload(config); importlib.reload(auth)
        auth.init()
        assert auth.verify("kk-second-key") == "admin"
        assert auth.verify("kk-first-key") is None

    def test_tilde_expanded(self, fresh):
        monkey = pytest.MonkeyPatch()
        monkey.setenv("KAYKAY_DB", "~/kk_probe.db")
        import src.config as config
        importlib.reload(config)
        assert "~" not in config.DB_PATH
        monkey.undo()
        importlib.reload(config)


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------
class TestKeys:
    def test_issue_and_verify(self, fresh):
        _, auth, *_ = fresh
        auth.init()
        key = auth.issue("ci")
        assert key.startswith("kk-")
        assert auth.verify(key) is not None

    def test_hashes_are_stored_not_plaintext(self, fresh):
        config, auth, *_ = fresh
        auth.init()
        key = auth.issue("ci")
        import sqlite3
        conn = sqlite3.connect(config.DB_PATH)
        hashes = {r[0] for r in conn.execute("SELECT key_hash FROM api_keys")}
        conn.close()
        assert key not in hashes

    def test_revoke_is_idempotent(self, fresh):
        """Revoking twice must not raise, and the key must stay inactive.

        Worth noting: SQLite's rowcount counts rows *matched* by an UPDATE, so a
        second revoke still reports True. The behaviour that matters is that the
        key ends up inactive and no exception escapes -- asserted here rather
        than asserting a rowcount semantic that the driver does not guarantee.
        """
        _, auth, *_ = fresh
        auth.init()
        key_id = auth.verify(auth.issue("x"))
        assert auth.revoke(key_id) is True
        assert auth.revoke(key_id) is True     # idempotent, no exception
        assert auth.is_active(key_id) is False

    def test_revoke_unknown_key_is_false(self, fresh):
        _, auth, *_ = fresh
        auth.init()
        assert auth.revoke("k_does_not_exist") is False

    def test_revoked_key_is_inactive_but_still_resolvable(self, fresh):
        _, auth, *_ = fresh
        auth.init()
        key = auth.issue("x")
        key_id = auth.verify(key)
        auth.revoke(key_id)
        assert auth.verify(key) == key_id
        assert auth.is_active(key_id) is False


# ---------------------------------------------------------------------------
# The agent's tools -- deterministic, no LLM involved
# ---------------------------------------------------------------------------
class TestAgentTools:
    def test_search_finds_matching_lines(self):
        from src.agent import _tool
        out = _tool("search_text", {"pattern": "error", "text": "a\nb ERROR c\nd"})
        assert out["ok"] and out["count"] == 1
        assert out["hits"][0]["line"] == 2

    def test_count_matches(self):
        from src.agent import _tool
        assert _tool("count_matches", {"pattern": r"\d", "text": "a1 b22"})["matches"] == 3

    def test_bad_regex_is_data_not_a_crash(self):
        from src.agent import _tool
        out = _tool("search_text", {"pattern": "[unclosed", "text": "x"})
        assert out["ok"] is False and "bad regex" in out["error"]

    def test_empty_and_overlong_patterns_refused(self):
        from src.agent import MAX_PATTERN, _tool
        assert _tool("count_matches", {"pattern": "", "text": "x"})["ok"] is False
        assert _tool("count_matches", {"pattern": "a" * (MAX_PATTERN + 1), "text": "x"})["ok"] is False

    def test_unknown_tool_refused(self):
        from src.agent import _tool
        assert _tool("rm_rf", {"pattern": "a", "text": "b"})["ok"] is False

    def test_hits_capped(self):
        from src.agent import MAX_HITS, _tool
        out = _tool("search_text", {"pattern": "err", "text": "\n".join(["err"] * 500)})
        assert len(out["hits"]) <= MAX_HITS


# ---------------------------------------------------------------------------
# The loop, provider stubbed
# ---------------------------------------------------------------------------
def _text(content):
    """A provider response shaped exactly like the JSON the API returns.

    Dicts, not objects: providers.chat returns the parsed response body, so a
    fake built from objects fails with a subscript error that looks like an
    agent bug rather than a test bug.
    """
    return {"choices": [{"message": {"content": content, "tool_calls": None}}]}


def _call(name, args):
    return {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


class TestAgentLoop:
    def test_answers_without_a_tool(self, fresh, monkeypatch):
        from src import agent as agent_mod
        _, _, _, providers = fresh
        monkeypatch.setattr(agent_mod.providers, "chat",
                            lambda body: (_text("Three errors."), "groq"))
        r = agent_mod.run("how many errors?", "qwen/qwen3.8-27b")
        assert r["answer"] == "Three errors." and r["rounds"] == 1

    def test_uses_a_tool_then_answers(self, fresh, monkeypatch):
        from src import agent as agent_mod
        _, _, _, providers = fresh
        seq = [(_call("count_matches", {"pattern": "err", "text": "err err"}), "groq"),
               (_text("There are 2."), "groq")]
        monkeypatch.setattr(agent_mod.providers, "chat", lambda body: seq.pop(0))
        r = agent_mod.run("count err", "qwen/qwen3.8-27b")
        act = [t for t in r["trace"] if t["phase"] == "act"]
        assert act[0]["tool_calls"][0]["result"]["matches"] == 2

    def test_round_cap_terminates_a_runaway_model(self, fresh, monkeypatch):
        from src import agent as agent_mod
        _, _, _, providers = fresh
        monkeypatch.setattr(agent_mod.providers, "chat",
                            lambda body: (_call("count_matches", {"pattern": "a", "text": "aaa"}), "groq"))
        r = agent_mod.run("loop", "qwen/qwen3.8-27b", max_rounds=3)
        assert r["rounds"] == 3 and "maximum number of rounds" in r["answer"]

    def test_provider_failure_returns_a_result_not_an_exception(self, fresh, monkeypatch):
        from src import agent as agent_mod
        _, _, _, providers = fresh

        def boom(body):
            raise agent_mod.providers.ProviderError("all providers failed")

        monkeypatch.setattr(agent_mod.providers, "chat", boom)
        r = agent_mod.run("anything", "qwen/qwen3.8-27b")
        assert r["mode"] == "provider_error" and "Gateway unavailable" in r["answer"]

    def test_tools_are_offered_to_the_provider(self, fresh, monkeypatch):
        from src import agent as agent_mod
        _, _, _, providers = fresh
        seen = {}

        def capture(body):
            seen.update(body)
            return _text("done"), "groq"

        monkeypatch.setattr(agent_mod.providers, "chat", capture)
        agent_mod.run("x", "qwen/qwen3.8-27b")
        assert len(seen["tools"]) == 2 and seen["tool_choice"] == "auto"

    def test_agent_goes_through_the_gateway(self):
        """The agent must not import groq directly -- that would bypass caps."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "src", "agent.py"), encoding="utf-8").read()
        assert "groq" not in src.lower()


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------
class TestApi:
    def _client(self, fresh):
        """Seed the admin key, then reload the app against the test DB.

        Ordering matters: auth.init() must run against the reloaded config so
        the seed lands in the throwaway database, not a real one.
        """
        from fastapi.testclient import TestClient
        config, auth, telemetry, _ = fresh
        importlib.reload(config)
        importlib.reload(auth)
        auth.init()
        importlib.reload(telemetry)
        telemetry.init()
        import src.gateway as gateway
        importlib.reload(gateway)
        return TestClient(gateway.app)

    def test_endpoints_require_auth(self, fresh):
        client = self._client(fresh)
        assert client.get("/v1/models").status_code == 401
        assert client.get("/v1/models", headers={"Authorization": "Bearer nope"}).status_code == 401

    def test_models_lists_live_ids_only(self, fresh):
        client = self._client(fresh)
        r = client.get("/v1/models", headers={"Authorization": "Bearer kk-test-admin"})
        assert r.status_code == 200
        ids = {m["id"] for m in r.json()["data"]}
        assert "qwen/qwen3.8-27b" in ids
        assert not (ids & {"llama-3.3-70b-versatile", "llama-4-scout-17b-16e-instruct"})
        assert len(ids) == len(r.json()["data"]), "advertised ids must be unique"

    def test_chat_without_a_provider_is_502_and_logged(self, fresh):
        config, auth, telemetry, providers = fresh
        auth.init(); telemetry.init()
        client = self._client(fresh)
        r = client.post("/v1/chat/completions", json={"model": "openai/gpt-oss-120b", "messages": []},
                        headers={"Authorization": "Bearer kk-test-admin"})
        assert r.status_code == 502
        assert telemetry.summary()["failed"] == 1

    def test_unknown_model_on_agent_is_400(self, fresh):
        client = self._client(fresh)
        r = client.post("/v1/agent", json={"task": "x", "model": "nope"},
                        headers={"Authorization": "Bearer kk-test-admin"})
        assert r.status_code == 400

    def test_spend_cap_blocks_with_402(self, fresh):
        config, auth, telemetry, _ = fresh
        auth.init(); telemetry.init()
        key = auth.issue("capped", spend_cap=0.000001)
        telemetry.record(auth.verify(key), "groq", "qwen/qwen3.8-27b", "ok", 1.0, 1000, 1000)
        from fastapi.testclient import TestClient
        import src.gateway as gateway
        importlib.reload(gateway)
        client = TestClient(gateway.app)
        r = client.post("/v1/chat/completions", json={"messages": []},
                        headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 402

    def test_non_admin_cannot_manage_keys(self, fresh):
        client = self._client(fresh)
        r = client.post("/v1/keys", json={"name": "x"}, headers={"Authorization": "Bearer kk-other"})
        assert r.status_code in (401, 403)

    def test_health_names_the_providers(self, fresh):
        client = self._client(fresh)
        r = client.get("/health")
        assert r.status_code == 200 and "providers_configured" in r.json()


# ---------------------------------------------------------------------------
# The dashboard must not build HTML from request data
# ---------------------------------------------------------------------------
def test_dashboard_has_no_innerhtml():
    """The model name is attacker-controlled; innerHTML would execute it.

    Comments are stripped before the check, otherwise this test fails on the
    comment explaining why innerHTML is banned -- which is the wrong thing to
    assert on.
    """
    import re
    from src.dashboard import DASHBOARD_HTML

    code = re.sub(r"/\*.*?\*/", "", DASHBOARD_HTML, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    assert "innerHTML" not in code, "dashboard builds HTML from request data"
    assert "textContent" in DASHBOARD_HTML



def test_budget_reservation_is_atomic(fresh):
    _, auth, telemetry, _ = fresh
    auth.init(); telemetry.init()
    key = auth.issue("capped", spend_cap=0.001)
    key_id = auth.verify(key)
    import concurrent.futures
    def reserve_once(_):
        return telemetry.reserve_budget(key_id, 0.001, 0.0008)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(reserve_once, range(2)))
    assert sum(r is not None for r in results) == 1
