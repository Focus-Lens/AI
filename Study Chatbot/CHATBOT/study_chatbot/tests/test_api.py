import base64

import pytest
from .conftest import FakeLLM
from fastapi.testclient import TestClient
from google.genai import errors

from app import app
from study_chatbot import api
from study_chatbot.prompts import REPLIES


@pytest.fixture
def client():
    fake = FakeLLM()
    app.dependency_overrides[api.get_llm] = lambda: fake
    yield TestClient(app), fake
    app.dependency_overrides.clear()


def test_health(client):
    c, _ = client
    assert c.get("/health").json() == {"status": "ok"}


def test_standalone_openapi(client):
    c, _ = client
    assert set(c.get("/openapi.json").json()["paths"]) == {
        "/health", "/chat/welcome", "/chat/session", "/chat/message", "/chat/session/end", "/ocr"
    }


def test_missing_gemini_key_reports_configuration_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(app) as c:
        res = c.post("/chat/message", json={"message": "Explain a primary key."})
    assert res.status_code == 503
    assert res.json() == {"detail": "gemini_api_key_not_configured"}


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


def test_ocr_extracts_pdf_without_a_session(client):
    c, fake = client
    pdf = b"%PDF-1.7"

    def transcribe(data, mime_type):
        assert data == pdf
        assert mime_type == "application/pdf"
        return "--- Page 1 ---\nنص المحاضرة"

    fake.transcribe = transcribe
    res = c.post("/ocr", json={"mime_type": "application/pdf", "data": base64.b64encode(pdf).decode()})
    assert res.status_code == 200
    assert res.json() == {"text": "--- Page 1 ---\nنص المحاضرة"}
    assert not fake.calls


@pytest.mark.parametrize("mime_type,data", [
    ("image/png", "%%%"), ("image/png", "aGVsbG8="), ("text/plain", "aGVsbG8="),
])
def test_ocr_rejects_invalid_attachments(client, mime_type, data):
    c, _ = client
    assert c.post("/ocr", json={"mime_type": mime_type, "data": data}).status_code == 422


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
