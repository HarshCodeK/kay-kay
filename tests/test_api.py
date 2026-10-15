from fastapi.testclient import TestClient
from kaykay.app import app


def test_health():
    assert TestClient(app).get("/health").json()["ok"] is True


def test_chat_requires_an_issued_key():
    response = TestClient(app).post("/v1/chat/completions", json={"prompt": "hello"})
    assert response.status_code == 401


def test_key_issuance_disabled_without_admin_token(monkeypatch):
    monkeypatch.delenv("KAYKAY_ADMIN_TOKEN", raising=False)
    response = TestClient(app).post("/v1/keys")
    assert response.status_code == 503


def test_issued_key_allows_chat(monkeypatch):
    monkeypatch.setenv("KAYKAY_ADMIN_TOKEN", "test-admin-token")
    client = TestClient(app)
    key_response = client.post("/v1/keys", headers={"X-Admin-Token": "test-admin-token"})
    assert key_response.status_code == 200
    key = key_response.json()["api_key"]
    response = client.post("/v1/chat/completions", headers={"X-API-Key": key}, json={"prompt": "hello"})
    assert response.status_code == 200
    assert response.json()["provider"] == "primary"


def test_homepage_has_a_working_demo_entrypoint():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "KAY-KAY" in response.text
