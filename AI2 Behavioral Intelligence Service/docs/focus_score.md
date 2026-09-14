# Behavioral Intelligence — Focus Score Methodology

**Version:** 0.2 (Draft — per-section + weighted window aggregation)
**Owner:** Hossam — AI
**Depends on:** `feature_thresholds.md` (classified features), `state_detection.md` (state + confidence)
**Purpose:** Defines how to compute a single 0–100 Focus Score. Two granularities now exist:

* **Per-section score** (unchanged from v0.1)
* **Per-window score** (new — duration-weighted mean of section scores)

Rule-based, explainable, reproducible — no ML/LLM (per spec 2.4).

---

## 0. Core Principle

### Per-section score

Computed in **two layers**:

1. **Base Score** — derived directly from classified behavioral features (independent of the detected state). Represents general "behavior quality."
2. **State Penalty** — an additional deduction driven by the detected Learning State (from `state_detection.md`), scaled by that state's confidence. This keeps the Score and the State consistent with each other (e.g. a `DISTRACTION` state should never coexist with a high score).

```text
Final Score = clamp(Base Score − State Penalty, 0, 100)
```

### Per-window score

A **duration-weighted mean** of the section scores within the window. See §4.

---

## 1. Layer 1 — Base Score

Start at 100. Each classified feature applies a fixed point adjustment.

| Feature                                | Category                  | Adjustment |
| -------------------------------------- | ------------------------- | ---------: |
| `scroll_pattern`                       | `ERRATIC`                 |        −15 |
|                                        | `MODERATE`                |         −5 |
|                                        | `STABLE`                  |          0 |
| `revisit`                              | `HIGH`                    |        −15 |
|                                        | `MODERATE`                |         −8 |
|                                        | `LOW`                     |         −3 |
|                                        | `NONE`                    |          0 |
| `interaction`                          | `NONE`                    |        −15 |
|                                        | `LOW`                     |         −8 |
|                                        | `NORMAL`                  |          0 |
|                                        | `HIGH`                    |         +5 |
| `mcq_accuracy` *(skip if no MCQ)*      | `LOW`                     |        −20 |
|                                        | `MEDIUM`                  |         −8 |
|                                        | `HIGH`                    |         +5 |
| `mcq_response_time` *(skip if no MCQ)* | `TOO_FAST`                |        −12 |
|                                        | `SLOW`                    |         −5 |
|                                        | `NORMAL`                  |          0 |
| `disengagement`                        | `SIGNIFICANT_DISTRACTION` |        −25 |
|                                        | `MILD_DISTRACTION`        |        −10 |
|                                        | `FOCUSED`                 |          0 |
| `progression`                          | `INCOMPLETE`              |        −15 |
|                                        | `PARTIAL`                 |         −5 |
|                                        | `COMPLETE`                |         +5 |

```python
def base_score(features: dict) -> float:
    score = 100

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

> **Note:** `reading_speed` is no longer a feature (see `feature_thresholds.md` §10). Any prior adjustment for it has been removed.

---

## 2. Layer 2 — State Penalty

Driven by the output of `state_detection.md` (`state`, `confidence`).

| State                       | Max Penalty |
| --------------------------- | ----------: |
| `CONTENT_DIFFICULTY`        |         −10 |
| `SKIMMING`                  |         −15 |
| `WEAK_UNDERSTANDING`        |         −15 |
| `DISTRACTION_DISENGAGEMENT` |         −20 |
| `NORMAL_FOCUSED`            |           0 |

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

## 3. Per-Section Final Computation

```python
def compute_focus_score(
    features: dict,
    state: str,
    confidence: float
) -> int:
    b_score = base_score(features)
    penalty = state_penalty(state, confidence)
    final = max(0, min(100, b_score - penalty))
    return round(final)
```

---

## 4. Per-Window Aggregation

The real-time path (`/ai2/analyze-window`) returns **one** focus score per window, not per section. It is computed as a **duration-weighted mean** of the section scores:

```text
window_score = Σ (section_score_i × time_spent_i) / Σ time_spent_i
```

**Why weighted by duration?** A 10-second glance at a section should not count as much as a 4-minute engagement. A simple mean would let a trivial section dominate the window verdict.

```python
def weighted_window_score(
    section_results: list[dict],
    sections: list
) -> int:
    if not section_results:
        return 0

    total_time = sum(
        s.time_spent_seconds
        for s in sections
    )

    if total_time <= 0:
        # Edge case: all sections had zero duration -> simple mean
        return round(
            sum(r["focusScore"] for r in section_results)
            / len(section_results)
        )

    weighted_sum = sum(
        r["focusScore"] * s.time_spent_seconds
        for r, s in zip(section_results, sections)
    )

    return round(weighted_sum / total_time)
```

**Contract:** `section_results` and `sections` MUST be aligned by index. The pipeline guarantees this by only appending to both lists when a section is successfully processed.

**Edge case:** if `total_time <= 0` (all sections have zero duration — e.g. a student who opened the app and immediately closed it), fall back to a simple mean to avoid dividing by zero.

---

## 5. Worked Example (per-section)

### Input

```text
mcq_accuracy: LOW            → -20
mcq_response_time: TOO_FAST  → -12
(all other features neutral) → 0

State: SKIMMING
confidence: 0.8
```

### Calculation

```text
Base Score = 100 - 20 - 12 = 68
State Penalty = 15 × 0.8 = 12
Final Score = 68 - 12 = 56
```

The exact number is less important than the behaviour: LOW accuracy + TOO_FAST response consistently produces a score in the "needs intervention" range, which then drives `SHOW_EXPLANATION` from the decision table.

---

## 6. Worked Example (per-window)

Window contains two sections:

| Section | Focus Score | Time Spent |
| ------- | ----------: | ---------: |
| A       |          90 |        20s |
| B       |          40 |       280s |

```text
window_score = (90 × 20 + 40 × 280) / 300
             = (1800 + 11200) / 300
             = 13000 / 300
             = 43.33 → 43
```

The short section barely dents the score. This is intentional — the window verdict should reflect where the learner actually spent their time.

---

## 7. Output of This Layer

### Per-section (end-of-session path)

```json
{
  "section_id": "S003",
  "concept_id": "C008",
  "state": "SKIMMING",
  "confidence": 0.8,
  "focusScore": 56
}
```

### Per-window (real-time path)

```json
{
  "window_index": 3,
  "window_focus_score": 43,
  "window_state": "CONTENT_DIFFICULTY",
  "sections_analyzed": 2
}
```
