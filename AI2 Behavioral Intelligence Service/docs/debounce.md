# Debounce Mechanism — `debounce.py`

## Purpose

The debounce mechanism prevents the same recommended action from being pushed to the student twice in quick succession.

Without debounce, a learner who stays in `DISTRACTION_DISENGAGEMENT` for three consecutive windows could receive a **"take a break"** notification every 5 minutes. This is annoying and may train the learner to ignore the system.

This module is the **only stateful component** in the service. Everything else (`feature_extraction`, `state_detection`, `focus_score`, and `adaptive_decision`) is pure.

Debounce is intentionally isolated so its state can be replaced with Redis later without changing the rest of the pipeline.

---

## Where It Sits in the Pipeline

```text
analyze_window()
      ↓
feature_extraction
      ↓
state_detection
      ↓
focus_score
      ↓
adaptive_decision
      ↓
raw_action (e.g. "SUGGEST_BREAK")
      ↓
debounce_store.should_emit(session_id, raw_action)
      ↓
   ┌──┴──┐
   ↓     ↓
 True   False
   ↓     ↓
Emit   "SUPPRESSED"
raw_action
   ↓
Backend
```

The pipeline always returns the `raw_action` alongside the final `recommended_action`, allowing the Backend to log and inspect actions that were suppressed.

---

## Rules

The debounce mechanism follows these rules:

1. **First action for a session** → always emit.
2. **Same action within `DEBOUNCE_WINDOW_SECONDS`** → suppress.
3. **Different action with equal-or-higher severity** → always emit.
   This is an escalation — we never hide a more important action behind a less severe one.
4. **Different action with lower severity within the window** → suppress.
   This prevents the system from downgrading a serious action shortly after it was emitted.
5. **Same action after the debounce window expires** → emit again.
6. **`is_final=True` on a window** → immediately clear the session's debounce state for memory hygiene.

---

## Constants

| Constant                  |     Value | Meaning                                                           |
| ------------------------- | --------: | ----------------------------------------------------------------- |
| `DEBOUNCE_WINDOW_SECONDS` |     `120` | Minimum gap between two identical actions                         |
| `SEVERITY_ORDER`          | See below | Determines whether an action change is an escalation or downgrade |

### Severity Order

```python
SEVERITY_ORDER = {
    "CONTINUE": 0,
    "INCREASE_ASSESSMENT_FREQUENCY": 1,
    "SLOW_PACE": 2,
    "SHOW_EXPLANATION": 3,
    "REASSESS": 4,
    "SUGGEST_BREAK": 5,
}
```

### Design Rationale

The severity order is based on the **cost of inaction if an action is suppressed**.

Missing a `SUGGEST_BREAK` action is considered more harmful than missing a `CONTINUE` action. Therefore, when in doubt, the system allows the **higher-severity action** to pass through.

---

## API

### `DebounceStore.should_emit()`

```python
DebounceStore.should_emit(
    session_id: str,
    action: str
) -> bool
```

Returns:

* `True` → the action should be shown to the learner.
* `False` → the action should be suppressed.

The internal state is updated whenever the method returns `True`.

---

### `DebounceStore.clear()`

```python
DebounceStore.clear(session_id: str) -> None
```

Removes all debounce state associated with a session.

It is called automatically by the pipeline when:

```python
window.is_final == True
```

It can also be called manually by an admin or cleanup job.

---

### Module-Level Singleton

The module exposes a module-level singleton:

```python
debounce_store
```

This is the instance imported and used by `pipeline.py`.

The store is thread-safe through an internal `threading.Lock`.

---

## State & Lifecycle

Debounce state is stored in memory and keyed by `session_id`.

Each session entry contains:

```python
class _SessionDebounceState:
    last_action: str | None
    last_action_time: float
    last_emitted_at: float
```

### Fields

| Field              | Description                                           |
| ------------------ | ----------------------------------------------------- |
| `last_action`      | The last action that was actually emitted             |
| `last_action_time` | Epoch timestamp of the last emitted action            |
| `last_emitted_at`  | Epoch timestamp used for TTL-based garbage collection |

---

## TTL / Garbage Collection

The debounce store uses a **1-hour TTL**.

Any session whose `last_emitted_at` is older than one hour is silently removed during the next `should_emit()` call.

### Why TTL Is Needed

If a learner closes the application in the middle of a session and never sends:

```python
is_final=True
```

the service could otherwise retain one dictionary entry for every abandoned session indefinitely.

The TTL makes this memory leak **self-healing**.

### Trade-off

A learner who legitimately pauses for more than one hour will lose their debounce state. As a result, the system may emit a duplicate action when the learner resumes.

This is considered acceptable for the MVP. Persistent state using Redis is intentionally out of scope for the current version.

---

## Thread Safety

Both `should_emit()` and `clear()` acquire:

```python
self._lock
```

before accessing:

```python
self._store
```

FastAPI runs synchronous endpoints in a thread pool, meaning concurrent requests from different sessions can access the debounce store at the same time.

The current implementation uses a **coarse-grained lock** covering the entire store.

This is acceptable at MVP scale.

If throughput becomes a bottleneck in the future, the store can be optimized by **sharding the lock based on the `session_id` hash**.

---

## Edge Cases

| Case                                                   | Behaviour                                                                                                        |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| First action ever for a session                        | Emit — there is no prior state                                                                                   |
| `clear()` called on an unknown session                 | No-op                                                                                                            |
| Action not present in `SEVERITY_ORDER`                 | Treated as severity `0`                                                                                          |
| Two requests for different sessions at once            | Independent — no interference                                                                                    |
| Same request retried by Backend                        | Second call is suppressed if the same action is within the debounce window                                       |
| Clock jumps backwards (`time.time()` is non-monotonic) | Elapsed time may become negative, which is treated as being within the debounce window; the action is suppressed |

The clock-jump behaviour is considered acceptable for the MVP.

---

## Why Not Persist to Redis Yet?

The Backend already stores session history and supplies it with each window request.

Debounce is the only piece of information that this service needs to remember between requests, and it is inexpensive to maintain in memory.

A single in-memory store with TTL is sufficient to handle the MVP's main failure modes, including:

* Application termination
* Network interruptions
* Abandoned sessions
* Missing `is_final=True` requests

If the service is later scaled horizontally across multiple workers or instances, **Redis will become necessary** to maintain shared debounce state.

The `DebounceStore` API is intentionally small, making a future Redis implementation a straightforward drop-in replacement.

---

## Testing

Debounce tests are located in:

```text
test_window_scenarios.py
```

### Section C — Debounce

The tests cover:

* First-action-emits invariant
* Same-action suppression within the debounce window
* Escalation always passing
* Downgrade suppression
* Session independence
* `clear()` releasing state
* Window expiry allowing the action through again

The `_clean_debounce` autouse fixture clears the singleton between tests to prevent cross-test pollution.

---

## Open Points

### 1. Per-User vs. Per-Session Debounce

The debounce state is currently keyed by:

```text
session_id
```

If a learner starts two sessions back-to-back, the system may emit the same action once in each session.

This is acceptable for the MVP and can be revisited if user feedback indicates a need for per-user debounce.

---

### 2. Adaptive Debounce Window

Currently, the debounce window is fixed:

```python
DEBOUNCE_WINDOW_SECONDS = 120
```

A future version could use different windows depending on the action type.

For example:

* Longer debounce window for `CONTINUE`
* Shorter debounce window for `SUGGEST_BREAK`

This could make the system more adaptive to the importance and frequency of different recommendations.

---

### 3. Observability

The current implementation does not track suppression counts.

Adding metrics such as:

```text
(session_id, action) → suppression_count
```

could help monitor system behaviour and tune the debounce window based on real usage data.

---

## Summary

The `debounce.py` module provides a small, isolated, and thread-safe stateful layer that prevents repetitive recommendations while allowing important escalations to pass through.

Its main characteristics are:

* **In-memory state**
* **120-second debounce window**
* **Severity-aware escalation**
* **1-hour TTL garbage collection**
* **Session-level isolation**
* **Thread-safe access**
* **Automatic cleanup on final windows**
* **Redis-ready design for future scaling**
