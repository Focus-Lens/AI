"""Redis connection and session keys for Study Chatbot."""

import hashlib
import os
from functools import lru_cache

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry


class RedisNotConfigured(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        raise RedisNotConfigured("REDIS_URL is required for session state")
    try:
        return Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
            retry=Retry(NoBackoff(), 0),
        )
    except ValueError:
        raise RedisNotConfigured("REDIS_URL is invalid") from None


def state_key(service: str, session_id: str) -> str:
    prefix = os.getenv("REDIS_KEY_PREFIX", "focuslens")
    session_hash = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return f"{prefix}:{service}:v1:{session_hash}"
