from fastapi.testclient import TestClient
from kaykay.app import app


def test_health_and_metrics():
    client = TestClient(app)
    assert client.get("/health").json()["mode"] == "deterministic_stub"
    assert client.get("/metrics").json()["scope"] == "this_process_only"


def test_key_issuance_requires_admin_token(monkeypatch):
    monkeypatch.setenv("KAYKAY_ADMIN_TOKEN", "test-admin-secret")
    client = TestClient(app)
    assert client.post("/v1/keys").status_code == 403
    issued = client.post("/v1/keys", headers={"X-Admin-Token": "test-admin-secret"})
    assert issued.status_code == 200
    key = issued.json()["api_key"]
    response = client.post("/v1/chat/completions", headers={"X-API-Key": key}, json={"prompt": "hello"})
    assert response.status_code == 200


def test_key_issuance_disabled_without_secret(monkeypatch):
    monkeypatch.delenv("KAYKAY_ADMIN_TOKEN", raising=False)
    assert TestClient(app).post("/v1/keys").status_code == 503
