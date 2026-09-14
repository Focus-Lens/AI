"""
Debounce mechanism for recommended actions.

Prevents the SAME action from being suggested twice in quick succession.
Rules:
  1. First action for a session -> always emit.
  2. Same action within DEBOUNCE_WINDOW_SECONDS -> suppress.
  3. Different action with >= severity -> always emit (escalation).
  4. Different action with < severity within window -> suppress.
  5. is_final=True -> clear session state (memory hygiene).

State is in-memory, thread-safe, with TTL-based GC for abandoned sessions.
"""

import time
from threading import Lock


DEBOUNCE_WINDOW_SECONDS = 120  # 2 minutes between identical actions

SEVERITY_ORDER = {
    "CONTINUE": 0,
    "INCREASE_ASSESSMENT_FREQUENCY": 1,
    "SLOW_PACE": 2,
    "SHOW_EXPLANATION": 3,
    "REASSESS": 4,
    "SUGGEST_BREAK": 5,
}


class _SessionDebounceState:
    __slots__ = ("last_action", "last_action_time", "last_emitted_at")

    def __init__(self):
        self.last_action: str | None = None
        self.last_action_time: float = 0.0
        self.last_emitted_at: float = 0.0


class DebounceStore:
    """Thread-safe, in-memory, per-session debounce tracker."""

    def __init__(self, ttl_seconds: int = 3600):
        self._store: dict[str, _SessionDebounceState] = {}
        self._lock = Lock()
        self._ttl = ttl_seconds

    def should_emit(self, session_id: str, action: str) -> bool:
        """
        Returns True if `action` should be emitted now, False if suppressed.
        Updates internal state whenever returning True.
        """
        now = time.time()
        with self._lock:
            self._gc(now)
            state = self._store.get(session_id)
            if state is None:
                state = _SessionDebounceState()
                self._store[session_id] = state

            # First action ever for this session -> emit
            if state.last_action is None:
                self._record(state, action, now)
                return True

            elapsed = now - state.last_action_time

            if action != state.last_action:
                prev_sev = SEVERITY_ORDER.get(state.last_action, 0)
                curr_sev = SEVERITY_ORDER.get(action, 0)
                if curr_sev >= prev_sev:
                    self._record(state, action, now)
                    return True
                # Downgrade within debounce window -> suppress
                if elapsed < DEBOUNCE_WINDOW_SECONDS:
                    return False
                self._record(state, action, now)
                return True

            # Same action within window -> suppress
            if elapsed < DEBOUNCE_WINDOW_SECONDS:
                return False

            self._record(state, action, now)
            return True

    def clear(self, session_id: str) -> None:
        """Called on is_final=True to release memory."""
        with self._lock:
            self._store.pop(session_id, None)

    @staticmethod
    def _record(state: "_SessionDebounceState", action: str, now: float) -> None:
        state.last_action = action
        state.last_action_time = now
        state.last_emitted_at = now

    def _gc(self, now: float) -> None:
        stale = [
            sid for sid, st in self._store.items()
            if (now - st.last_emitted_at) > self._ttl
        ]
        for sid in stale:
            del self._store[sid]


# Singleton — imported by pipeline.py
debounce_store = DebounceStore(ttl_seconds=3600)