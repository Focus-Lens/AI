import pytest
from conftest import FakeLLM
from fastapi.testclient import TestClient
from google.genai import errors

import api
from prompts import REPLIES


@pytest.fixture
def client():
    fake = FakeLLM()
    api.app.dependency_overrides[api.get_llm] = lambda: fake
    yield TestClient(api.app), fake
    api.app.dependency_overrides.clear()


def test_health(client):
    c, _ = client
    assert c.get("/health").json() == {"status": "ok"}


def test_welcome(client):
    c, _ = client
    assert c.get("/chat/welcome").json() == {"reply": REPLIES["welcome"]}


def test_chat_message(client):
    c, fake = client
    res = c.post("/chat/message", json={"message": "اشرحلي الضوء", "subject": "Physics"})
    assert res.status_code == 200
    body = res.json()
    assert body["blocked"] is False and body["category"] == "study" and body["usage"]["total"] == 2250
    assert len(fake.calls) == 1


def test_missing_message_is_422(client):
    c, _ = client
    assert c.post("/chat/message", json={}).status_code == 422


def test_service_key_required_when_auth_enabled(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv("CHAT_AUTH_DISABLED", "false")
    monkeypatch.setenv("CHAT_SERVICE_KEY", "s3cret")
    assert c.post("/chat/message", json={"message": "hi"}).status_code == 401
    assert c.post("/chat/message", json={"message": "hi"}, headers={"X-Service-Key": "wrong"}).status_code == 401
    assert c.post("/chat/message", json={"message": "hi"}, headers={"X-Service-Key": "s3cret"}).status_code == 200


def test_gemini_quota_maps_to_429(client):
    c, fake = client

    def boom(*a, **k):
        raise errors.APIError(429, {"error": {"message": "per day limit"}})

    fake.json = boom
    assert c.post("/chat/message", json={"message": "hi"}).status_code == 429
