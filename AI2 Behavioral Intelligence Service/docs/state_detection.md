# Behavioral Intelligence — Learning-State Detection Methodology

**Version:** 0.3 (Draft — `reading_speed` removed, weights rebalanced)
**Owner:** Hossam — AI Engineer
**Depends on:** `feature_thresholds.md` (classified features per section)
**Purpose:** Defines how classified features are combined into a single learning-state decision with a confidence score. This is a pure rule-based system — no ML/LLM — for explainability and reproducibility (per spec 2.3 / 2.4).

**Scope note (v0.3):** The `reading_speed` feature was removed (see `feature_thresholds.md` §10). All scoring rules that previously referenced it have been updated. Maxima have shifted accordingly — see §1–§4 for new values.

---

## 0. Core Principle

No single signal is ever treated as a definitive classification. Each candidate state has a set of weighted conditions; conditions that are true contribute their weight to that state's score. The state with the highest score (above a minimum activation threshold) wins. For activated states, the score contributes to confidence (with an MCQ evidence discount where applicable). For `NORMAL_FOCUSED`, confidence is additionally scaled by observed evidence and is not treated as the inverse of concern alone.

```text id="6kz2ym"
score(state) =
    sum(weight of true conditions)
    /
    sum(weight of all applicable conditions)
```

**Applicable conditions** = all conditions for that state, EXCEPT those depending on MCQ data when no micro-challenge exists for the section (see §7).

---

## 1. State: `CONTENT_DIFFICULTY`

**Interpretation:** user is trying to understand, but the content is hard — repeated re-reading and erratic scrolling pattern.

| Condition                                     | Weight |
| --------------------------------------------- | -----: |
| `revisit in [MODERATE, HIGH]`                 |      3 |
| `scroll_pattern == ERRATIC`                   |      2 |
| `mcq_response_time == SLOW` *(MCQ-dependent)* |      2 |
| **Max score (with MCQ)**                      |  **7** |
| **Max score (no MCQ)**                        |  **5** |

> **Note:** `reading_speed == VERY_SLOW` was previously a weight-3 condition; it has been removed.

---

## 2. State: `SKIMMING`

**Interpretation:** user scrolls fast without real absorption; reflected in poor question performance and fast response time.

| Condition                                         | Weight |
| ------------------------------------------------- | -----: |
| `scroll_speed == FAST`                            |      2 |
| `mcq_accuracy == LOW` *(MCQ-dependent)*           |      3 |
| `mcq_response_time == TOO_FAST` *(MCQ-dependent)* |      2 |
| **Max score (with MCQ)**                          |  **7** |
| **Max score (no MCQ)**                            |  **2** |

**Mandatory evidence gate:** `SKIMMING` requires at least two positive signals among `scroll_speed == FAST`, `mcq_accuracy == LOW`, and `mcq_response_time == TOO_FAST`. MCQ-derived signals count only after `MIN_MCQ_EVIDENCE` observations are available (default: 3). A lone fast-scroll signal is not sufficient to activate `SKIMMING`; without enough corroborating evidence, the detector must consider other supported states or fall back to `NORMAL_FOCUSED`.

> **Note:** `reading_speed in [FAST, VERY_FAST]` was previously a weight-3 condition; it has been removed. The evidence gate is required because scores are normalized over applicable conditions: a single true condition could otherwise score `1.0` when it is the only applicable condition.

---

## 3. State: `WEAK_UNDERSTANDING`

**Interpretation:** reading behavior looks normal (no obvious struggle signal), but comprehension — measured via MCQ — is poor with no revisits.

> **⚠️ Mandatory Gate:** `mcq_accuracy == LOW` is a required gate. Without a confirmed poor assessment result, the score is forced to 0 regardless of the other signals. This prevents false positives on well-performing students.

| Condition                                                                     | Weight |
| ----------------------------------------------------------------------------- | -----: |
| `mcq_accuracy == LOW` — **mandatory gate**; if false or MCQ absent, score = 0 |      3 |
| `revisit in [NONE, LOW]` *(only counted if gate passes)*                      |      2 |
| `progression == COMPLETE` *(only counted if gate passes)*                     |      1 |
| `mcq_response_time == NORMAL` *(only counted if gate passes)*                 |      2 |
| **Max score (with MCQ, gate passed)**                                         |  **8** |
| **Max score (no MCQ, or gate fails)**                                         |  **0** |

> **Note:** `reading_speed == NORMAL` was previously a weight-2 condition; it has been removed. The max score is unchanged at 8 (the gate weight 3 + the other three conditions 2+1+2 = 8).
>
> `WEAK_UNDERSTANDING` is by design undetectable when there is no MCQ data — this state fundamentally requires an assessment result as its anchor.

---

## 4. State: `DISTRACTION_DISENGAGEMENT`

**Interpretation:** signals of leaving the app or generally low interaction.

| Condition                                  |                       Weight |
| ------------------------------------------ | ---------------------------: |
| `disengagement == SIGNIFICANT_DISTRACTION` |                            4 |
| `disengagement == MILD_DISTRACTION`        |                            2 |
| `interaction in [NONE, LOW]`               |                            2 |
| `progression == INCOMPLETE`                |                            2 |
| **Max score**                              | **10** *(not MCQ-dependent)* |

---

## 5. State: `NORMAL_FOCUSED` (default / fallback)

No explicit rules — this state is assigned when no other state reaches the minimum activation threshold (see §6).

It represents "nothing concerning detected."

---

## 6. Decision Algorithm

```python id="2zj7z5"
ACTIVATION_THRESHOLD = 0.4  # minimum score to accept a non-default state
MIN_MCQ_EVIDENCE = int(os.environ.get("AI2_MIN_MCQ_EVIDENCE", "3"))

STATE_PRIORITY = [
    "DISTRACTION_DISENGAGEMENT",
    "WEAK_UNDERSTANDING",
    "SKIMMING",
    "CONTENT_DIFFICULTY",
]


def detect_state(features: dict) -> dict:
    has_mcq = (features.get("mcq_count") or 0) >= MIN_MCQ_EVIDENCE

    candidates = {
        "CONTENT_DIFFICULTY": score_content_difficulty(
            features,
            has_mcq
        ),
        "SKIMMING": score_skimming(
            features,
            has_mcq
        ),
        "WEAK_UNDERSTANDING": score_weak_understanding(
            features,
            has_mcq
        ),
        "DISTRACTION_DISENGAGEMENT": score_disengagement(
            features
        ),
    }

    best_score = max(candidates.values())
    best_state = next(
        s for s in STATE_PRIORITY
        if candidates[s] == best_score
    )

    if best_score >= ACTIVATION_THRESHOLD:
        return {
            "state": best_state,
            "confidence": round(best_score, 2)
        }
    else:
        return {
            "state": "NORMAL_FOCUSED",
            "confidence": round((1 - best_score) * normal_evidence_factor(features), 2)
        }
```

`score_skimming` returns `0.0` unless at least two positive support signals are present. MCQ accuracy and response-time signals are counted only when `mcq_count >= MIN_MCQ_EVIDENCE`; with the default threshold, fewer than three observations cannot corroborate a skimming classification. This activation gate is separate from confidence scaling: confidence capping is not used to prevent a weakly supported state from triggering an action.

`normal_evidence_factor` is the fraction of observed signal domains among scrolling, interaction, app/tab focus, and MCQ performance. Missing values do not count. No telemetry yields confidence `0.0`; one observed domain contributes at most `0.25`; two domains at most `0.5`; and all four permit the full inverse-score confidence. This prevents missing data from being reported as certain focus.

---

## 7. Handling Missing MCQ Data

Two different behaviors apply depending on the state:

### General Rule — `CONTENT_DIFFICULTY` and `SKIMMING`

If a section has fewer than `MIN_MCQ_EVIDENCE` observations (3 by default), MCQ-derived conditions are treated as unavailable for state activation. They do not count as positive or negative evidence.

They are **NOT** treated as false/zero.

For `SKIMMING`, this also means that a fast-scroll signal alone cannot pass the two-signal evidence gate. A fast-but-engaged reader must not be classified as skimming without corroborating evidence.

### Special Case — `WEAK_UNDERSTANDING`

This state requires `mcq_accuracy == LOW` as a hard gate.

With no MCQ data, its score is forced to `0.0` — it is never returned without direct evidence of a poor assessment result.

### `DISTRACTION_DISENGAGEMENT`

This state has no MCQ-dependent conditions and is unaffected either way.

---

## 8. Output of This Layer

```json id="5h0q7x"
{
  "section_id": "S003",
  "concept_id": "C008",
  "state": "CONTENT_DIFFICULTY",
  "confidence": 0.8
}
```

This feeds into: **Focus Score calculation** and **Adaptive Decision** — next stages.
