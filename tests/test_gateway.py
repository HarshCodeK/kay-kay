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


def test_spend_cap_enforcement(tmp_path, monkeypatch):
    auth, telemetry, _, _ = _fresh(tmp_path, monkeypatch)
    auth.init_tables()
    telemetry.init_tables()
    # Issue a key with a $0.01 spend cap
    key = auth.issue_key("cap-test", spend_cap_usd=0.01)
    key_id = auth.verify_key(key)
    assert key_id is not None
    # Log some spending that exceeds the cap
    telemetry.log_request(key_id, "groq", "llama-3.3-70b-versatile", "ok", 200, 100, 100000, 50000)
    spent = telemetry.get_key_spend(key_id)
    assert spent > 0.01
    # Check cap
    cap = auth.get_key_spend_cap(key_id)
    assert cap == 0.01


def test_key_lifecycle(tmp_path, monkeypatch):
    auth, _, _, _ = _fresh(tmp_path, monkeypatch)
    auth.init_tables()
    # Issue
    key = auth.issue_key("lifecycle-test", spend_cap_usd=5.0)
    key_id = auth.verify_key(key)
    assert key_id is not None
    assert auth.check_key_active(key_id) is True
    # List
    keys = auth.list_keys()
    names = [k["name"] for k in keys]
    assert "lifecycle-test" in names
    # Revoke
    assert auth.revoke_key(key_id) is True
    assert auth.check_key_active(key_id) is False
    # Still verifiable (hash exists) but active check fails
    assert auth.verify_key(key) is not None


def test_admin_key_management_api(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    import src.gateway as gateway
    importlib.reload(gateway)
    client = TestClient(gateway.app)
    headers = {"Authorization": "Bearer kk-test-admin"}

    # List keys
    r = client.get("/v1/keys", headers=headers)
    assert r.status_code == 200
    assert len(r.json()["keys"]) >= 1  # admin key seeded

    # Create key
    r = client.post("/v1/keys", json={"name": "test-key", "spend_cap_usd": 10.0}, headers=headers)
    assert r.status_code == 200
    assert r.json()["key"].startswith("kk-")
    new_key_id = r.json()["key_id"]

    # Revoke key
    r = client.post(f"/v1/keys/{new_key_id}/revoke", headers=headers)
    assert r.status_code == 200
    assert r.json()["revoked"] is True

    # Non-admin can't manage keys
    r = client.post("/v1/keys", json={"name": "nope"}, headers={"Authorization": "Bearer kk-not-admin"})
    assert r.status_code == 403
