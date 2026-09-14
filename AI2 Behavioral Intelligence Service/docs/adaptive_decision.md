# Behavioral Intelligence — Adaptive Decision Methodology

**Version:** 0.2 (Real-time windows + cross-window escalation + debounce)
**Owner:** Hossam — AI
**Depends on:** `state_detection.md` (state + confidence), `focus_score.md` (focusScore), `trend_analysis.md` (trend + consecutive counters), `debounce.md` (suppression)
**Purpose:** Maps a detected `(state, focusScore)` pair — plus cross-window history signals — to a concrete recommended action. Uses a rule-based lookup table with escalation rules. **No ML/LLM** (per spec 2.5).

> **Scope note (v0.2):** Two decision paths now exist:
>
> * **End-of-session path** (`analyze_session`): decision is based only on the current section's `(state, focusScore)`. Same behaviour as v0.1.
> * **Real-time path** (`analyze_window`): decision is based on the window's dominant state + duration-weighted window score, then **escalated** using history signals (consecutive state, consecutive low score, trend). This directly implements the "Cross-section repetition" open point from v0.1.

---

## 0. Core Principle

Each Learning State has one or more Focus Score **bands**. As the score drops within a state, the recommended action escalates in severity.

This is a direct lookup, not a weighted calculation — the hard reasoning already happened in the **State Detection** and **Focus Score** layers.

On top of the lookup, the real-time path applies **escalation rules**. If the learner is stuck in a state or experiencing low scores across multiple windows, or if the trend is declining, the action escalates even when the current score does not yet justify it.

This prevents the system from under-reacting to a slow downward spiral.

Finally, the chosen action passes through **debounce** before being emitted. See `debounce.md`.

The pipeline always reports both:

* The **raw action**
* The **final action**, which may be suppressed by debounce

---

## 1. Decision Table

### `CONTENT_DIFFICULTY`

| Focus Score | Action             | Rationale                                                      |
| ----------- | ------------------ | -------------------------------------------------------------- |
| ≥ 70        | `SLOW_PACE`        | Mild difficulty — slowing down is enough                       |
| 40–69       | `SHOW_EXPLANATION` | Clear difficulty — needs actual extra explanation              |
| < 40        | `REASSESS`         | Severe difficulty — need to confirm foundational understanding |

### `SKIMMING`

| Focus Score | Action                          | Rationale                                                              |
| ----------- | ------------------------------- | ---------------------------------------------------------------------- |
| ≥ 70        | `INCREASE_ASSESSMENT_FREQUENCY` | Light skimming — more questions can re-engage attention                |
| 40–69       | `SHOW_EXPLANATION`              | Clear skimming with a comprehension gap — needs re-exposure to content |
| < 40        | `REASSESS`                      | Severe skimming — content is not being absorbed adequately             |

### `WEAK_UNDERSTANDING`

| Focus Score | Action             | Rationale                                                           |
| ----------- | ------------------ | ------------------------------------------------------------------- |
| ≥ 60        | `SHOW_EXPLANATION` | Mild comprehension gap — extra explanation is sufficient            |
| < 60        | `REASSESS`         | Clear comprehension gap — needs deeper evaluation before continuing |

> **Why no `SLOW_PACE` option?**
>
> Reading speed is already normal, so pacing is not the issue. The problem is comprehension, requiring direct intervention.

### `DISTRACTION_DISENGAGEMENT`

| Focus Score | Action          | Rationale                                                |
| ----------- | --------------- | -------------------------------------------------------- |
| ≥ 50        | `SLOW_PACE`     | Mild distraction — slowing down may help refocus         |
| < 50        | `SUGGEST_BREAK` | Severe distraction — better to rest than continue poorly |

### `NORMAL_FOCUSED`

| Focus Score | Action     |
| ----------- | ---------- |
| Any         | `CONTINUE` |

---

## 2. Escalation Rules

These rules apply to the **real-time path only**.

They are applied **after the base lookup**, in the order shown below.

> **First match wins.**

|  # | Condition                                                                                      | Escalated Action   | Rationale                                                                                                 |
| -: | ---------------------------------------------------------------------------------------------- | ------------------ | --------------------------------------------------------------------------------------------------------- |
|  1 | `state == DISTRACTION_DISENGAGEMENT` AND `consecutive_same_state >= 2`                         | `SUGGEST_BREAK`    | Repeated distraction is a stronger signal than one bad window. Do not wait for the score to drop further. |
|  2 | `consecutive_low_score >= 2` (2+ windows with score < 50, including current)                   | `SUGGEST_BREAK`    | Sustained low engagement regardless of detected state.                                                    |
|  3 | `trend == DECLINING` AND `state != NORMAL_FOCUSED` AND base action ∈ {`CONTINUE`, `SLOW_PACE`} | `SHOW_EXPLANATION` | The learner is sliding — add support before the situation becomes break-worthy.                           |

### Why Escalation Is Bounded to One Tier

Escalating more than one tier at a time, for example:

```text
CONTINUE → SUGGEST_BREAK
```

would feel too abrupt to the learner and cannot be fully justified by a single 5-minute window.

The system therefore escalates **one step at a time** and re-evaluates the learner during the next window.

### Why These Rules Live Here

The escalation rules belong in `adaptive_decision.py`, not `trend_analysis.py`.

`trend_analysis.py` is responsible only for **pure signal extraction**:

```text
numbers → labels / counters
```

It does not know whether an action is good, bad, mild, or severe.

The escalation policy is a **decision concern**, so it belongs in the adaptive decision layer.

---

## 3. Implementation

```python
DECISION_TABLE = {
    "CONTENT_DIFFICULTY": [
        (70, 100, "SLOW_PACE"),
        (40, 69,  "SHOW_EXPLANATION"),
        (0,  39,  "REASSESS"),
    ],
    "SKIMMING": [
        (70, 100, "INCREASE_ASSESSMENT_FREQUENCY"),
        (40, 69,  "SHOW_EXPLANATION"),
        (0,  39,  "REASSESS"),
    ],
    "WEAK_UNDERSTANDING": [
        (60, 100, "SHOW_EXPLANATION"),
        (0,  59,  "REASSESS"),
    ],
    "DISTRACTION_DISENGAGEMENT": [
        (50, 100, "SLOW_PACE"),
        (0,  49,  "SUGGEST_BREAK"),
    ],
    "NORMAL_FOCUSED": [
        (0, 100, "CONTINUE"),
    ],
}


def _lookup_base_action(state: str, focus_score: int) -> str:
    for low, high, action in DECISION_TABLE[state]:
        if low <= focus_score <= high:
            return action

    return "CONTINUE"  # fallback safety net


def get_recommended_action(
    state: str,
    focus_score: int,
    consecutive_same_state: int = 1,
    consecutive_low_score: int = 0,
    trend: str = "STABLE",
) -> str:
    """
    Base action from lookup table, then escalation rules:

      - Repeated DISTRACTION_DISENGAGEMENT across windows -> break.
      - Sustained low score (2+ windows below 50) -> break.
      - DECLINING trend on a non-normal state -> upgrade support.
    """

    base_action = _lookup_base_action(state, focus_score)

    if state == "DISTRACTION_DISENGAGEMENT" and consecutive_same_state >= 2:
        return "SUGGEST_BREAK"

    if consecutive_low_score >= 2:
        return "SUGGEST_BREAK"

    if trend == "DECLINING" and state != "NORMAL_FOCUSED":
        if base_action in ("CONTINUE", "SLOW_PACE"):
            return "SHOW_EXPLANATION"

    return base_action
```

### Backward Compatibility

The new keyword arguments all have defaults:

```python
consecutive_same_state=1
consecutive_low_score=0
trend="STABLE"
```

Therefore, existing callers such as `analyze_section()` in `pipeline.py` continue to work unchanged and retain the **v0.1 behaviour**.

---

## 4. Full Pipeline Recap

This section shows how the different AI modules connect together.

### End-of-Session Path

```text
Raw Events / Signals
(data_dictionary.md)
        ↓
Classified Features
(feature_thresholds.md)
        ↓
Learning State + Confidence
(state_detection.md)
        ↓
Focus Score per Section
(focus_score.md)
        ↓
Recommended Action per Section
(this document — no escalation)
        ↓
Final Structured Output
(api_contract.md §2)
        ↓
Backend
```

### Real-Time Path

```text
Raw Events / Signals
(data_dictionary.md)
        ↓
Per-section signals within a 5-minute window
        ↓
Classified Features
(feature_thresholds.md)
        ↓
Learning State + Confidence
(state_detection.md)
        ↓
Focus Score per Section
(focus_score.md)
        ↓
Weighted Window Score + Dominant State
(focus_score.weighted_window_score)
        ↓
History Signals
(trend_analysis.md)
        ↓
Base Action + Escalation
(this document)
        ↓
Debounce
(debounce.md)
        ↓
Final Emitted Action
        ↓
Final Structured Output
(api_contract.md §5)
        ↓
Backend
```

---
