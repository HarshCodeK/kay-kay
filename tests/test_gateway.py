"""Offline gateway tests — no network, providers stubbed via env/base_url.

Run from repo root:  python -m pytest tests/ -q
"""
import os
import sys
import json
import importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh(tmp_path, monkeypatch):
    """Isolated DB + no real provider creds, so tests never touch the network."""
    monkeypatch.setenv("KAYKAY_DB", str(tmp_path / "t.db"))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("KAYKAY_ADMIN_KEY", "kk-test-admin")
    import src.config as config
    importlib.reload(config)
    import src.auth as auth
    importlib.reload(auth)
    import src.telemetry as telemetry
    importlib.reload(telemetry)
    import src.providers as providers
    importlib.reload(providers)
    return auth, telemetry, providers, config


def test_admin_key_roundtrip(tmp_path, monkeypatch):
    auth, *_ , config = _fresh(tmp_path, monkeypatch)
    auth.init_tables()
    assert auth.authenticate("Bearer kk-test-admin") == "admin"
    assert auth.authenticate("Bearer kk-wrong") is None
    assert auth.authenticate(None) is None


def test_issue_and_verify_key(tmp_path, monkeypatch):
    auth, _, _, _ = _fresh(tmp_path, monkeypatch)
    auth.init_tables()
    k = auth.issue_key("ci")
    assert k.startswith("kk-")
    assert auth.authenticate(f"Bearer {k}") is not None
    assert auth.verify_key("kk-not-issued") is None


def test_telemetry_summary_math(tmp_path, monkeypatch):
    _, telemetry, _, _ = _fresh(tmp_path, monkeypatch)
    telemetry.init_tables()
    telemetry.log_request("admin", "groq", "llama-3.3-70b-versatile", "ok", 200, 100.0, 50, 20)
    telemetry.log_request("admin", "groq", "llama-3.3-70b-versatile", "error", 502, 300.0, 10, 0)
    s = telemetry.usage_summary()
    assert s["total_requests"] == 2
    assert s["successful"] == 1
    assert s["failed"] == 1
    assert s["total_prompt_tokens"] == 60
    # cost estimate: (50*0.59 + 20*0.79 + 10*0.59)/1M — just check it's positive & small
    assert 0 < s["est_cost_usd"] < 0.001
    assert len(s["recent"]) == 2


def test_no_providers_configured_raises(tmp_path, monkeypatch):
    _, _, providers, _ = _fresh(tmp_path, monkeypatch)
    import pytest
    with pytest.raises(providers.ProviderError, match="no providers configured"):
        providers.call_chat_completion({"model": "x", "messages": []})


def test_gateway_auth_endpoints(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    import pytest
    from fastapi.testclient import TestClient
    # import gateway AFTER env is set so module-level config re-reads it
    import src.gateway as gateway
    importlib.reload(gateway)
    client = TestClient(gateway.app)

    # no key -> 401
    r = client.get("/v1/models")
    assert r.status_code == 401
    # bad key -> 401
    r = client.get("/v1/models", headers={"Authorization": "Bearer kk-nope"})
    assert r.status_code == 401
    # admin key -> models list, OpenAI shape
    r = client.get("/v1/models", headers={"Authorization": "Bearer kk-test-admin"})
    assert r.status_code == 200
    assert r.json()["object"] == "list"
    assert any(m["id"] == "llama-3.3-70b-versatile" for m in r.json()["data"])
    # usage endpoint reflects zero requests then one failed call
    u = client.get("/v1/usage", headers={"Authorization": "Bearer kk-test-admin"}).json()
    assert u["total_requests"] == 0
    # chat completion with no providers configured -> 502 + logged
    r = client.post("/v1/chat/completions", json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": "hi"}]},
                    headers={"Authorization": "Bearer kk-test-admin"})
    assert r.status_code == 502
    u = client.get("/v1/usage", headers={"Authorization": "Bearer kk-test-admin"}).json()
    assert u["total_requests"] == 1
    assert u["failed"] == 1
