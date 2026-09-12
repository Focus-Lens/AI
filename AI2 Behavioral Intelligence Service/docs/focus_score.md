# Behavioral Intelligence — Focus Score Methodology

**Version:** 0.1 (Draft — MVP, Rule-Based Weighted Scoring)
**Owner:** Hossam — AI 
**Depends on:** `feature_thresholds.md` (classified features), `state_detection.md` (state + confidence)
**Purpose:** Defines how to compute a single 0–100 Focus Score per section/session. Rule-based, explainable, reproducible — no ML/LLM (per spec 2.4).

---

## 0. Core Principle

The Focus Score is computed in **two layers**:

1. **Base Score** — derived directly from classified behavioral features (independent of the detected state). Represents general "behavior quality."
2. **State Penalty** — an additional deduction driven by the detected Learning State (from `state_detection.md`), scaled by that state's confidence. This keeps the Score and the State consistent with each other (e.g. a `DISTRACTION` state should never coexist with a high score).

```
Final Score = clamp(Base Score − State Penalty, 0, 100)
```

---

## 1. Layer 1 — Base Score

Start at 100. Each classified feature applies a fixed point adjustment.

| Feature | Category | Adjustment |
|---|---|---|
| `reading_speed` | VERY_SLOW | −10 |
| | FAST | −5 |
| | VERY_FAST | −15 |
| | NORMAL | 0 |
| `scroll_pattern` | ERRATIC | −10 |
| | MODERATE | −3 |
| | STABLE | 0 |
| `revisit` | HIGH | −10 |
| | MODERATE | −5 |
| | LOW | −2 |
| | NONE | 0 |
| `interaction` | NONE | −10 |
| | LOW | −5 |
| | NORMAL | 0 |
| | HIGH | +5 |
| `mcq_accuracy` *(skip if no MCQ)* | LOW | −15 |
| | MEDIUM | −5 |
| | HIGH | +5 |
| `mcq_response_time` *(skip if no MCQ)* | TOO_FAST | −10 |
| | SLOW | −5 |
| | NORMAL | 0 |
| `disengagement` | SIGNIFICANT_DISTRACTION | −20 |
| | MILD_DISTRACTION | −8 |
| | FOCUSED | 0 |
| `progression` | INCOMPLETE | −10 |
| | PARTIAL | −3 |
| | COMPLETE | +5 |

```python
def base_score(features: dict) -> float:
    score = 100
    score += ADJUSTMENTS["reading_speed"][features["reading_speed"]]
    score += ADJUSTMENTS["scroll_pattern"][features["scroll_pattern"]]
    score += ADJUSTMENTS["revisit"][features["revisit"]]
    score += ADJUSTMENTS["interaction"][features["interaction"]]
    score += ADJUSTMENTS["disengagement"][features["disengagement"]]
    score += ADJUSTMENTS["progression"][features["progression"]]

    if features.get("mcq_accuracy") is not None:
        score += ADJUSTMENTS["mcq_accuracy"][features["mcq_accuracy"]]
        score += ADJUSTMENTS["mcq_response_time"][features["mcq_response_time"]]

    return max(0, min(100, score))
```

---

## 2. Layer 2 — State Penalty

Driven by the output of `state_detection.md` (`state`, `confidence`).

| State | Max Penalty |
|---|---|
| `CONTENT_DIFFICULTY` | −10 |
| `SKIMMING` | −15 |
| `WEAK_UNDERSTANDING` | −15 |
| `DISTRACTION_DISENGAGEMENT` | −20 |
| `NORMAL_FOCUSED` | 0 |

```python
MAX_PENALTY = {
    "CONTENT_DIFFICULTY": 10,
    "SKIMMING": 15,
    "WEAK_UNDERSTANDING": 15,
    "DISTRACTION_DISENGAGEMENT": 20,
    "NORMAL_FOCUSED": 0,
}

def state_penalty(state: str, confidence: float) -> float:
    return MAX_PENALTY[state] * confidence
```

**Rationale for penalty magnitudes:** `DISTRACTION_DISENGAGEMENT` carries the highest penalty because it reflects genuine disengagement (leaving the app). `CONTENT_DIFFICULTY` carries the lowest of the four non-default states because it reflects an active (if struggling) attempt to engage with the content — not a lack of effort.

Multiplying by `confidence` ensures a weakly-detected state doesn't crush the score as hard as a strongly-detected one.

---

## 3. Final Computation

```python
def compute_focus_score(features: dict, state: str, confidence: float) -> int:
    b_score = base_score(features)
    penalty = state_penalty(state, confidence)
    final = max(0, min(100, b_score - penalty))
    return round(final)
```

---

## 4. Worked Example

Input:
```
reading_speed: FAST          → -5
mcq_accuracy: LOW            → -15
(all other features neutral) → 0
State: SKIMMING, confidence: 0.8
```

```
Base Score = 100 - 5 - 15 = 80
State Penalty = 15 × 0.8 = 12
Final Score = 80 - 12 = 68
```

Matches the example in the spec's section 2.6 (`"focusScore": 68`) — confirms the methodology produces sensible, expected output ranges.

---

## 5. Output of This Layer

```json
{
  "section_id": "S003",
  "concept_id": "C008",
  "state": "SKIMMING",
  "confidence": 0.8,
  "focusScore": 68
}
```

This feeds directly into: **Adaptive Decision** (2.5) — next stage.

---

## 6. Open Points

- [ ] Point adjustments in Layer 1 and max penalties in Layer 2 are initial estimates based on domain reasoning — must be recalibrated once real session data is available.
- [ ] Consider whether Focus Score should also be aggregated at the **session level** (average/weighted average across all sections), in addition to per-section — needs confirmation with Backend on what granularity is required in the final API contract (2.6).
- [ ] Consider clamping visibility: should Focus Score ever be shown to the end-user directly, or only used internally for the Adaptive Decision engine? Affects whether extra "friendliness" smoothing is needed (e.g. minimum floor score) — a Product decision, not purely technical.

---

*This document is the direct implementation reference for the Focus Score module. Any adjustment/penalty changes must be re-validated against the test scenarios deliverable.*
