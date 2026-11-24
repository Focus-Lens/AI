"""Study sessions and their pre-split lecture chunks in Redis."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from redis_state import get_redis, state_key

from . import config
from .retrieval import Chunk, LectureIndex


_SAVE_SESSION = """
local key = KEYS[1]
if ARGV[2] == "1" and redis.call("EXISTS", key) == 1 then
    return 0
end
redis.call("HSET", key, unpack(ARGV, 3))
redis.call("EXPIRE", key, ARGV[1])
return 1
"""

_APPEND_TURN = """
local key = KEYS[1]
if redis.call("HGET", key, "generation") ~= ARGV[1] then
    return 0
end
local history = cjson.decode(redis.call("HGET", key, "history"))
local turn = cjson.decode(ARGV[2])
for _, message in ipairs(turn) do
    table.insert(history, message)
end
local recent = {}
for i = math.max(1, #history - tonumber(ARGV[3]) + 1), #history do
    table.insert(recent, history[i])
end
redis.call("HSET", key, "history", cjson.encode(recent), "last_chunk_ids", ARGV[4])
return 1
"""


@dataclass
class Session:
    id: str
    index: LectureIndex
    subject: str = ""
    lesson_title: str = ""
    grade: str = ""
    history: list[dict] = field(default_factory=list)  # {"role": "user"|"assistant", "text": ...}
    last_chunk_ids: list[int] = field(default_factory=list)
    last_used: float = field(default_factory=time.time)
    generation: str = ""

    def expires_at(self, ttl: int) -> str:
        return datetime.fromtimestamp(self.last_used + ttl, timezone.utc).isoformat()


class SessionStore:
    def __init__(self, ttl_seconds: int = config.SESSION_TTL_SECONDS):
        self.ttl = ttl_seconds

    def put(self, session: Session, *, replace: bool = True) -> bool:
        session.last_used = time.time()
        session.generation = uuid4().hex
        index = session.index
        values = {
            "generation": session.generation,
            "lecture": json.dumps({
                "text": index.text,
                "truncated": index.truncated,
                "chunks": [vars(chunk) for chunk in index.chunks],
            }, ensure_ascii=False),
            "subject": session.subject,
            "lesson_title": session.lesson_title,
            "grade": session.grade,
            "history": json.dumps(session.history, ensure_ascii=False),
            "last_chunk_ids": json.dumps(session.last_chunk_ids),
        }
        fields = [value for pair in values.items() for value in pair]
        return bool(get_redis().eval(
            _SAVE_SESSION, 1, state_key("chat", session.id), self.ttl, int(not replace), *fields
        ))

    def get(self, session_id: str) -> Session | None:
        key = state_key("chat", session_id)
        with get_redis().pipeline() as pipe:
            pipe.hgetall(key)
            pipe.expire(key, self.ttl)
            values, _ = pipe.execute()
        if not values:
            return None
        lecture = json.loads(values["lecture"])
        chunks = [
            Chunk(c["id"], c["text"], c["page"], Counter(c["terms"]))
            for c in lecture["chunks"]
        ]
        index = LectureIndex(lecture["text"], chunks=chunks)
        index.truncated = lecture["truncated"]
        return Session(
            id=session_id,
            index=index,
            subject=values["subject"],
            lesson_title=values["lesson_title"],
            grade=values["grade"],
            history=json.loads(values["history"]),
            last_chunk_ids=json.loads(values["last_chunk_ids"]),
            generation=values["generation"],
        )

    def add_turn(self, session: Session, question: str, reply: str, chunk_ids: list[int]) -> None:
        """Append against the saved history while the same session generation exists."""
        turn = [{"role": "user", "text": question}, {"role": "assistant", "text": reply}]
        get_redis().eval(
            _APPEND_TURN, 1, state_key("chat", session.id),
            session.generation, json.dumps(turn, ensure_ascii=False),
            config.MAX_HISTORY_TURNS, json.dumps(chunk_ids),
        )

    def end(self, session_id: str) -> bool:
        return bool(get_redis().delete(state_key("chat", session_id)))


store = SessionStore()
