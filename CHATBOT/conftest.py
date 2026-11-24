"""Run chatbot tests against an isolated Redis-compatible store."""

import fakeredis
import pytest

from study_chatbot import sessions


@pytest.fixture
def redis_server():
    return fakeredis.FakeServer()


@pytest.fixture(autouse=True)
def redis_client(monkeypatch, redis_server):
    client = fakeredis.FakeRedis(server=redis_server, decode_responses=True)
    monkeypatch.setattr(sessions, "get_redis", lambda: client)
    monkeypatch.setenv("CHAT_AUTH_DISABLED", "true")
    with client:
        yield client
