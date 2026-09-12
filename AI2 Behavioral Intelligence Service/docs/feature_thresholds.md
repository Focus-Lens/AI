# Behavioral Intelligence — Feature Classification & Thresholds

**Version:** 0.1 (Draft — MVP, Static Thresholds)
**Owner:** Hossam — AI Engineer
**Purpose:** Defines how each raw signal (from Data Dictionary) is converted into a categorical classification. This is the direct source of truth for implementation — every rule below should map to one function in code.

**Methodology note:** All thresholds are rule-based (if/else on numeric ranges), not ML/LLM-based. This guarantees explainability and reproducibility as required by section 2.4 of the spec. Thresholds are initial estimates and MUST be revisited once real usage data is available.

---

## 0. General Principles

1. **Rate-based signals must be normalized by time.** Never compare a raw count (e.g. `interaction_count`) across sections of different duration directly — always convert to a per-minute rate first.
2. **Every classification function takes raw signal(s) in, and returns one category label out.** No side effects, no external calls — pure functions, easy to unit test.
3. **Language-sensitive signals** (currently: reading speed) must receive a `content_language` parameter (`"ar"`, `"en"`, or `"mixed"`). If missing/unknown, default to `"mixed"` thresholds.

---

## 1. Reading Speed — `classify_reading_speed(wpm)`

Input: `reading_speed_wpm` (float)
Content is confirmed to be **English only** — no language branching needed.

| Range (WPM) | Category |
|---|---|
| < 100 | `VERY_SLOW` |
| 100 – 250 | `NORMAL` |
| 250 – 400 | `FAST` |
| > 400 | `VERY_FAST` |

> Note: if the product later introduces non-English or mixed content, this function will need a `content_language` parameter again — see project history for the Arabic/mixed threshold values that were drafted and then dropped.

---

## 2. Scroll Speed — `classify_scroll_speed(px_per_sec)`

Input: `scroll_speed_avg_px_per_sec` (float)
**Status: PLACEHOLDER** — pending confirmation from Frontend on unit (raw px vs. density-independent dp). Do not finalize until Data Dictionary Open Point #4 is resolved.

| Range (px/sec) | Category |
|---|---|
| < 100 | `SLOW` |
| 100 – 400 | `NORMAL` |
| > 400 | `FAST` |

---

## 3. Scroll Pattern — `classify_scroll_pattern(direction_changes, time_spent_seconds)`

Derived rate:
```
direction_change_rate = direction_changes / (time_spent_seconds / 60)
```

| Rate (changes/min) | Category | Interpretation |
|---|---|---|
| 0 – 2 | `STABLE` | Continuous forward reading |
| 2 – 6 | `MODERATE` | Mild hesitation, expected |
| > 6 | `ERRATIC` | Frequent back-and-forth — possible confusion or search behavior |

---

## 4. Content Progression — `classify_progression(progression_pct)`

Input: `content_progression_pct` (float, 0–100)

| Range | Category |
|---|---|
| < 50% | `INCOMPLETE` |
| 50 – 90% | `PARTIAL` |
| > 90% | `COMPLETE` |

---

## 5. Section Revisit — `classify_revisit(revisit_count)`

Input: `section_revisit_count` (int)

| Count | Category |
|---|---|
| 0 | `NONE` |
| 1 | `LOW` |
| 2 – 3 | `MODERATE` |
| > 3 | `HIGH` |

---

## 6. Interaction Rate — `classify_interaction(interaction_count, time_spent_seconds)`

Derived rate:
```
interaction_rate = interaction_count / (time_spent_seconds / 60)
```

| Rate (interactions/min) | Category |
|---|---|
| 0 | `NONE` |
| 0 – 1 | `LOW` |
| 1 – 3 | `NORMAL` |
| > 3 | `HIGH` |

---

## 7. Micro-Challenge Accuracy — `classify_mcq_accuracy(correct_count, total_count)`

Derived rate:
```
mcq_accuracy = correct_count / total_count   (skip if total_count == 0)
```

| Accuracy | Category |
|---|---|
| < 40% | `LOW` |
| 40 – 70% | `MEDIUM` |
| > 70% | `HIGH` |

---

## 8. Micro-Challenge Response Time — `classify_response_time(response_time_seconds)`

Input: `response_time_seconds` (float, per question — average if multiple)

| Range | Category | Interpretation |
|---|---|---|
| < 3s | `TOO_FAST` | Likely guessing / random tap |
| 3 – 20s | `NORMAL` | Reasonable deliberation |
| > 20s | `SLOW` | Hesitation or difficulty |

---

## 9. Background / Distraction — `classify_disengagement(background_count, total_background_seconds)`

| Condition | Category |
|---|---|
| `background_count == 0` | `FOCUSED` |
| `background_count` 1–2 AND `total_background_seconds < 30` | `MILD_DISTRACTION` |
| `background_count > 2` OR `total_background_seconds >= 30` | `SIGNIFICANT_DISTRACTION` |

---

## 10. Output of This Layer (Feature Vector)

Once every signal is classified, the output for one section should look like this — this is what feeds into the **Learning-State Detection** layer (next step):

```json
{
  "section_id": "S003",
  "concept_id": "C008",
  "features": {
    "reading_speed": "FAST",
    "scroll_speed": "NORMAL",
    "scroll_pattern": "MODERATE",
    "progression": "COMPLETE",
    "revisit": "MODERATE",
    "interaction": "LOW",
    "mcq_accuracy": "LOW",
    "mcq_response_time": "NORMAL",
    "disengagement": "FOCUSED"
  }
}
```

---

## 11. Open Points

- [ ] Scroll speed thresholds are placeholders pending unit confirmation (px vs dp) from Frontend.
- [ ] All numeric thresholds above are initial estimates — must be recalibrated after collecting a baseline of real session data (recommend revisiting after first 2–4 weeks of production data).

---

*This document feeds directly into the Learning-State Detection logic (next stage). Any threshold change here should be re-validated against the test scenarios defined in the final deliverables.*