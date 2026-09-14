# Behavioral Intelligence — Feature Classification & Thresholds

**Version:** 0.2 (Draft — MVP, Static Thresholds; `reading_speed` removed)
**Owner:** Hossam — AI Engineer
**Purpose:** Defines how each raw signal (from Data Dictionary) is converted into a categorical classification. This is the direct source of truth for implementation — every rule below should map to one function in code.

**Methodology note:** All thresholds are rule-based (if/else on numeric ranges), not ML/LLM-based. This guarantees explainability and reproducibility as required by section 2.4 of the spec. Thresholds are initial estimates and MUST be revisited once real usage data is available.

**Scope note (v0.2):** The `reading_speed` feature has been **removed** from the pipeline. Content is English-only (per project decision), which removes the need for language-sensitive thresholds. Everything downstream has been adjusted — see §10.

---

## 0. General Principles

1. **Rate-based signals must be normalized by time.** Never compare a raw count (e.g. `interaction_count`) across sections of different duration directly — always convert to a per-minute rate first.
2. **Every classification function takes raw signal(s) in, and returns one category label out.** No side effects, no external calls — pure functions, easy to unit test.
3. **MCQ-dependent classifiers return `None` when not applicable** (no `micro_challenges` in the section). `None` means "not applicable" — it is NOT a category. Downstream code MUST check for `None` and exclude these features from scoring rather than treating `None` as a category.

---

## 1. Scroll Speed — `classify_scroll_speed(px_per_sec)`

Input: `scroll_speed_avg_px_per_sec` (float)

**Status: PLACEHOLDER** — pending confirmation from Frontend on unit (raw px vs. density-independent dp). Do not finalize until Data Dictionary Open Point #4 is resolved.

| Range (px/sec) | Category |
| -------------- | -------- |
| < 100          | `SLOW`   |
| 100 – 400      | `NORMAL` |
| > 400          | `FAST`   |

> **Note:** boundary handling is inclusive on the upper end (`<= 400` → `NORMAL`). See `feature_extraction.py::classify_scroll_speed`.

---

## 2. Scroll Pattern — `classify_scroll_pattern(direction_changes, time_spent_seconds)`

Derived rate:

```text
direction_change_rate = direction_changes / (time_spent_seconds / 60)
```

| Rate (changes/min) | Category   | Interpretation                                                  |
| ------------------ | ---------- | --------------------------------------------------------------- |
| 0 – 2              | `STABLE`   | Continuous forward reading                                      |
| 2 – 6              | `MODERATE` | Mild hesitation, expected                                       |
| > 6                | `ERRATIC`  | Frequent back-and-forth — possible confusion or search behavior |

**Edge case:** if `time_spent_seconds <= 0`, returns `STABLE` (the calmest zero-state) instead of dividing by zero. This matches `test_scenarios.md` Edge Case B.

---

## 3. Content Progression — `classify_progression(progression_pct)`

Input: `content_progression_pct` (float, 0–100)

| Range    | Category     |
| -------- | ------------ |
| < 50%    | `INCOMPLETE` |
| 50 – 90% | `PARTIAL`    |
| > 90%    | `COMPLETE`   |

> **Note:** boundaries are inclusive at the upper end (`<= 90` → `PARTIAL`).

---

## 4. Section Revisit — `classify_revisit(revisit_count)`

Input: `section_revisit_count` (int)

| Count | Category   |
| ----- | ---------- |
| 0     | `NONE`     |
| 1     | `LOW`      |
| 2 – 3 | `MODERATE` |
| > 3   | `HIGH`     |

---

## 5. Interaction Rate — `classify_interaction(interaction_count, time_spent_seconds)`

Derived rate:

```text
interaction_rate = interaction_count / (time_spent_seconds / 60)
```

| Rate (interactions/min) | Category |
| ----------------------- | -------- |
| 0                       | `NONE`   |
| 0 – 1                   | `LOW`    |
| 1 – 3                   | `NORMAL` |
| > 3                     | `HIGH`   |

**Edge case:** if `interaction_count == 0` OR `time_spent_seconds <= 0`, returns `NONE` without dividing. Matches `test_scenarios.md` Edge Case B.

---

## 6. Micro-Challenge Accuracy — `classify_mcq_accuracy(correct_count, total_count)`

Derived rate:

```text
mcq_accuracy = correct_count / total_count
```

Skip if `total_count == 0`.

| Accuracy | Category |
| -------- | -------- |
| < 40%    | `LOW`    |
| 40 – 70% | `MEDIUM` |
| > 70%    | `HIGH`   |

**Returns `None`** when `total_count <= 0` — signals "not applicable". Downstream layers must exclude this feature from scoring rather than treating it as a category.

---

## 7. Micro-Challenge Response Time — `classify_response_time(avg_response_time_seconds)`

Input: average `response_time_seconds` across all questions in the section (or `None` if no MCQs).

| Range   | Category   | Interpretation               |
| ------- | ---------- | ---------------------------- |
| < 3s    | `TOO_FAST` | Likely guessing / random tap |
| 3 – 20s | `NORMAL`   | Reasonable deliberation      |
| > 20s   | `SLOW`     | Hesitation or difficulty     |

**Returns `None`** when input is `None`.

---

## 8. Background / Distraction — `classify_disengagement(background_count, total_background_seconds)`

| Condition                                                  | Category                  |
| ---------------------------------------------------------- | ------------------------- |
| `background_count == 0`                                    | `FOCUSED`                 |
| `background_count` 1–2 AND `total_background_seconds < 30` | `MILD_DISTRACTION`        |
| `background_count > 2` OR `total_background_seconds >= 30` | `SIGNIFICANT_DISTRACTION` |

---

## 9. Output of This Layer (Feature Vector)

Once every signal is classified, the output for one section should look like this — this is what feeds into the **Learning-State Detection** layer:

```json
{
  "section_id": "S003",
  "concept_id": "C008",
  "features": {
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

> **Note:** `reading_speed` is not present — see §10.

---

## 10. Change Log

### v0.2 — `reading_speed` removed

* **What changed:** `classify_reading_speed()` and the `reading_speed` field were removed from the feature vector.
* **Why:** content is English-only per project decision. The original design carried a `content_language` parameter (`"ar"` / `"en"` / `"mixed"`) with language-specific WPM thresholds. With a single language, the feature adds complexity without discriminative value — and it was a source of ambiguity (which WPM band counts as "fast" for Arabic vs English?).
* **Downstream impact:**

  * `state_detection.py` no longer references `reading_speed` in any scoring rule. Rules that previously used it (`CONTENT_DIFFICULTY`, `SKIMMING`, `WEAK_UNDERSTANDING`) have had their weights adjusted so total maxima remain meaningful.
  * `focus_score.py` no longer applies any adjustment for reading speed.
  * `adaptive_decision.py` table is unchanged (it never saw features directly).
* **Test impact:** any test asserting `features_used.reading_speed` must be removed or updated. See `test_scenarios.md` scenario 2 — it previously asserted `reading_speed=VERY_FAST`, which no longer exists.
