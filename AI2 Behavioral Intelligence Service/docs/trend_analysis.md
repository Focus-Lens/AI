# Trend Analysis — `trend_analysis.py`

## Purpose

Extracts **temporal signals** from the window history that the Backend supplies with each real-time request.

These signals allow the pipeline to distinguish between:

* A learner having **one bad window** (which may simply be a difficult section) → **no escalation needed**.
* A learner **spiralling across 3 consecutive windows** (persistent issue) → escalate to `SUGGEST_BREAK`.

Without this module, `adaptive_decision.py` would only see the current window and would not be able to implement its escalation rules.

---

## Where It Sits in the Pipeline

```text
Backend request
(history: [...])
      ↓
trend_analysis.compute_trend()
      ↓
"IMPROVING" / "STABLE" / "DECLINING"
      ↓
trend_analysis.consecutive_state_count()
      ↓
int
      ↓
trend_analysis.consecutive_low_score_count()
      ↓
int
      ↓
adaptive_decision.get_recommended_action(
    state,
    focus_score,
    consecutive_same_state=...,
    consecutive_low_score=...,
    trend=...,
)
      ↓
Escalated action
```

`trend_analysis.py` is **pure**. It never mutates its inputs and never touches global state.

**Same history → same output.**

---

## API

### `compute_trend(scores: list[int]) -> str`

Determines the overall trend based on the most recent scores.

Returns one of:

| Value         | Meaning                                                      |
| ------------- | ------------------------------------------------------------ |
| `"IMPROVING"` | Last score is ≥ 8 points above the first score of the last 3 |
| `"DECLINING"` | Last score is ≤ 8 points below the first score of the last 3 |
| `"STABLE"`    | Anything else, or fewer than 2 scores                        |

### Window of Interest

Only the **last up to 3 scores** are considered.

This includes the current window's score, which the caller appends before calling `compute_trend()`.

### Why 3 Windows?

Three windows are long enough to smooth over a single bad MCQ, while still allowing the system to react quickly.

A 5-window window would introduce too much delay for a system operating at a 5-minute cadence.

### Why ±8?

Changes smaller than 8 points are considered to be within expected noise.

Although a single wrong MCQ can significantly affect a section score, the overall window score averages multiple signals. A threshold of 8 is approximately one **half-tier** on the focus-score scale.

---

## `consecutive_state_count()`

```python
consecutive_state_count(
    history: list,
    current_state: str
) -> int
```

Walks through `history` **backwards** while:

```python
item.state == current_state
```

and counts the matching states.

The counter starts at **1** to account for the current window, which is not included in `history` yet.

### Example

```text
history = [
    NORMAL,
    DISTRACTION,
    DISTRACTION
]

current_state = DISTRACTION

→ 3
```

The result is:

```text
2 matching states from history
+ 1 current state
= 3 consecutive windows
```

---

## `consecutive_low_score_count()`

```python
consecutive_low_score_count(
    history,
    current_score,
    threshold=50
) -> int
```

Uses the same backwards-counting approach as `consecutive_state_count()`, but operates on focus scores.

If:

```python
current_score >= threshold
```

the function immediately returns:

```text
0
```

Otherwise, it counts the consecutive low-score windows, including the current window.

---

## Design Decisions

### Why Not Use NumPy / Statistics?

The lists involved typically contain only **2–5 items**.

A simple loop is:

* Easier to understand
* Easier to test
* Easier to maintain
* Dependency-free

Performance is not a concern at this scale.

---

### Why Not Put This in `focus_score.py`?

This is a separation-of-concerns decision.

`focus_score.py` handles **per-section / per-window mathematical calculations**.

`trend_analysis.py` handles **cross-window temporal logic**.

Keeping them separate means:

* `focus_score.py` can be unit-tested with a single dictionary/window.
* `trend_analysis.py` can be unit-tested with a small list of integers or history objects.
* Changes to scoring logic do not directly affect trend logic.

---

### Why Pass `current_state` Instead of Computing It Here?

`consecutive_state_count()` is intentionally a **simple counter**.

The caller (`pipeline.py`) already knows the current window's dominant state from `analyze_window()`.

Recalculating the current state inside `trend_analysis.py` would duplicate logic and could eventually cause the two implementations to drift apart.

---

## Edge Cases

| Case                                            | Behaviour                                                |
| ----------------------------------------------- | -------------------------------------------------------- |
| `history=[]`, `scores=[70]`                     | `compute_trend()` → `"STABLE"`                           |
| `history=[]`, `current_state="X"`               | `consecutive_state_count()` → `1`                        |
| `current_score >= threshold`                    | `consecutive_low_score_count()` → `0`                    |
| `scores` has 2 items with delta = 7             | `"STABLE"`                                               |
| `scores` has 2 items with delta = 8             | `"IMPROVING"`                                            |
| `scores` has 5 items, all declining by 1        | `"STABLE"` because only the last 3 scores are considered |
| `history` has mixed states and latest ≠ current | Count stops immediately at `1`                           |

---

## Relationship to Focus Score Graph (UI)

The Frontend's **"Focus quality"** line chart plots one point per window.

The **trend label** displayed as a badge (for example, `"Stable"` or `"Improving"`) should be produced by:

```python
compute_trend()
```

using the same scores plotted on the chart.

Keeping `compute_trend()` as the single source of truth ensures that the trend badge and the focus-score graph remain consistent and cannot disagree.

---

## Testing

See:

```text
test_window_scenarios.py
```

### Section B — `trend_analysis`

Tests cover:

* Single score → `STABLE`
* Clear improvement
* Clear decline
* Last-3-only semantics
* Older scores being ignored
* Consecutive state counting
* Correct backwards traversal
* Stopping at a state mismatch
* Consecutive low-score counting
* Current score above threshold → `0`
* All consecutive scores below threshold → correct count

---

## Open Points

### 1. Threshold Tuning

The current values:

```text
±8
3-window history
```

are initial assumptions.

Once real learner data becomes available, these thresholds should be evaluated and potentially re-fitted.

For example, a learner who naturally oscillates by ±10 points could currently trigger false `IMPROVING` / `DECLINING` signals.

---

### 2. Weighted Trend

Currently, every window has equal weight.

If windows can have significantly different durations, such as:

```text
30 seconds
vs.
5 minutes
```

future versions may want to weight each score according to:

```text
window_end - window_start
```

This would make the trend calculation more representative of the actual time spent in each window.

---

### 3. Per-Feature Trends

The current API calculates a trend only for the **aggregate focus score**.

A future version could calculate trends for individual features, such as:

```text
mcq_accuracy trending down
scroll_rate improving
idle_time increasing
```

This could provide richer explanations for the recommendations generated by the adaptive decision layer.
