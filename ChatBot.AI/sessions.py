"""Study sessions kept in memory: the lecture (already chunked) + the chat history.

The backend sends the lecture ONCE (POST /chat/session); each question then only needs the
session_id. Sessions live in this process's memory: if the service restarts or a session expires,
/chat/message answers 409 and the backend just calls /chat/session again with the same text.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import config
from retrieval import LectureIndex


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

    def expires_at(self) -> str:
        return datetime.fromtimestamp(self.last_used + config.SESSION_TTL_SECONDS, timezone.utc).isoformat()

    def add_turn(self, question: str, reply: str) -> None:
        self.history += [{"role": "user", "text": question}, {"role": "assistant", "text": reply}]
        self.history = self.history[-config.MAX_HISTORY_TURNS:]


class SessionStore:
    def __init__(self, ttl_seconds: int = config.SESSION_TTL_SECONDS, max_sessions: int = config.MAX_SESSIONS):
        self.ttl = ttl_seconds
        self.max = max_sessions
        self._items: dict[str, Session] = {}
        self._lock = threading.Lock()

    def _drop_expired(self, now: float) -> None:
        for sid in [s for s, v in self._items.items() if now - v.last_used > self.ttl]:
            del self._items[sid]

    def put(self, session: Session) -> Session:
        with self._lock:
            now = time.time()
            self._drop_expired(now)
            self._items.pop(session.id, None)
            while len(self._items) >= self.max:  # full: drop the least recently used
                oldest = min(self._items.values(), key=lambda s: s.last_used)
                del self._items[oldest.id]
            session.last_used = now
            self._items[session.id] = session
            return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            now = time.time()
            s = self._items.get(session_id)
            if s is None or now - s.last_used > self.ttl:
                self._items.pop(session_id, None)
                return None
            s.last_used = now  # each question keeps the session alive
            return s

    def end(self, session_id: str) -> bool:
        with self._lock:
            return self._items.pop(session_id, None) is not None

    def __len__(self) -> int:
        return len(self._items)


store = SessionStore()
