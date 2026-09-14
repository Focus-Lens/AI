# Behavioral Intelligence — Test Scenarios (End-of-Session)

**Version:** 0.3 (`reading_speed` removed; real-time scenarios moved to `test_window_scenarios.md`)
**Owner:** Hossam — AI Engineer
**Purpose:** Input/output test cases covering every Learning State + key edge cases for the **end-of-session path** (`/ai2/analyze-session`). Real-time window tests live in `test_window_scenarios.md`.

**How to use this file:** Each scenario below has a matching function in `tests/test_scenarios.py`. If you change a threshold or weight in any methodology doc, run the test suite — if a scenario here starts failing, decide whether the scenario's expectation or the methodology needs to change, and update both together.

**Version note (v0.3):** All `reading_speed` assertions removed (feature deleted — see `feature_thresholds.md` §10). Scenario 2's expected `features_used.reading_speed` assertion is gone. Scenario 5's `focusScore=100` may shift if any adjustment constants changed — verify against current `focus_score.py`.

---

## Scenario 1 — `CONTENT_DIFFICULTY`

**Story:** User reads very slowly and keeps re-entering the section, trying hard to understand.

```json
{
  "time_spent_seconds": 120,
  "scroll_speed_avg_px_per_sec": 150,
  "scroll_direction_changes": 8,
  "content_progression_pct": 95,
  "section_revisit_count": 3,
  "interaction_count": 3,
  "micro_challenges": [
    {
      "question_id": "Q1",
      "response_time_seconds": 25,
      "is_correct": true
    }
  ],
  "background_count": 0,
  "total_background_seconds": 0
}
```

**Expected:** `state=CONTENT_DIFFICULTY`, `features_used.revisit == "MODERATE"`, `recommendedAction` one of `SLOW_PACE` / `SHOW_EXPLANATION` / `REASSESS` depending on final score.

---

## Scenario 2 — `SKIMMING`

**Story:** User scrolls fast, finishes quickly, but gets the questions wrong.

```json
{
  "time_spent_seconds": 20,
  "scroll_speed_avg_px_per_sec": 500,
  "scroll_direction_changes": 0,
  "content_progression_pct": 100,
  "section_revisit_count": 0,
  "interaction_count": 0,
  "micro_challenges": [
    {
      "question_id": "Q1",
      "response_time_seconds": 2,
      "is_correct": false
    }
  ],
  "background_count": 0,
  "total_background_seconds": 0
}
```

**Expected:** `state=SKIMMING`, `features_used.mcq_accuracy == "LOW"`.

> **Note:** Previously also asserted `features_used.reading_speed == "VERY_FAST"` — removed in v0.3.

---

## Scenario 3 — `WEAK_UNDERSTANDING`

**Story:** Reading looks completely normal, no revisits, but comprehension check fails.

```json
{
  "time_spent_seconds": 90,
  "scroll_speed_avg_px_per_sec": 200,
  "scroll_direction_changes": 1,
  "content_progression_pct": 100,
  "section_revisit_count": 0,
  "interaction_count": 2,
  "micro_challenges": [
    {
      "question_id": "Q1",
      "response_time_seconds": 10,
      "is_correct": false
    }
  ],
  "background_count": 0,
  "total_background_seconds": 0
}
```

**Expected:** `state=WEAK_UNDERSTANDING`, `confidence=1.0`, `recommendedAction=SHOW_EXPLANATION`.

---

## Scenario 4 — `DISTRACTION_DISENGAGEMENT` (boundary test)

**Story:** User leaves the app repeatedly and barely interacts.

```json
{
  "time_spent_seconds": 180,
  "scroll_speed_avg_px_per_sec": 150,
  "scroll_direction_changes": 1,
  "content_progression_pct": 30,
  "section_revisit_count": 0,
  "interaction_count": 0,
  "micro_challenges": [],
  "background_count": 4,
  "total_background_seconds": 60
}
```

**Expected:** `state=DISTRACTION_DISENGAGEMENT`, `mcq_data_available=false`, `recommendedAction` one of `SLOW_PACE` / `SUGGEST_BREAK`.

This case sits near the `focus_score.md` 50-point action boundary — good regression guard for that boundary specifically.

---

## Scenario 5 — `NORMAL_FOCUSED` (default/fallback)

**Story:** Everything about the session looks unremarkable — a well-performing student.

```json
{
  "time_spent_seconds": 100,
  "scroll_speed_avg_px_per_sec": 200,
  "scroll_direction_changes": 1,
  "content_progression_pct": 100,
  "section_revisit_count": 0,
  "interaction_count": 3,
  "micro_challenges": [
    {
      "question_id": "Q1",
      "response_time_seconds": 8,
      "is_correct": true
    }
  ],
  "background_count": 0,
  "total_background_seconds": 0
}
```

**Expected:** `state=NORMAL_FOCUSED`, `recommendedAction=CONTINUE`, `focusScore=100`.

> ⚠️ This is the exact scenario that caught the `WEAK_UNDERSTANDING` gating bug described in `state_detection.md` §3 — a passing student was originally misclassified. Keep this in the permanent regression suite specifically to guard against that bug reappearing.
>
> ⚠️ **v0.3 note:** the `focusScore=100` assertion is sensitive to any change in `ADJUSTMENTS` constants. If you retune `focus_score.py`, this scenario is the first to break — decide whether the retune or the expectation should change.

---

## Edge Case A — No Micro-Challenges in Section

Same as Scenario 1 but with `"micro_challenges": []`.

**Expected:** `mcq_data_available=false`, `features_used.mcq_accuracy=None`, `features_used.mcq_response_time=None`, no crash, `focusScore` still a valid int.

---

## Edge Case B — Zero Time Spent

`time_spent_seconds=0`, `interaction_count=0`, `scroll_direction_changes=0`.

**Expected:** no `ZeroDivisionError`; `scroll_pattern=STABLE`, `interaction=NONE` (see zero-duration handling in `feature_extraction.py`).

---

## Edge Case C — Tied Scores Between Two States

**Expected:** deterministic outcome via `STATE_PRIORITY` order in `state_detection.py` / `state_detection.md` §6 — not left to incidental dict ordering.

No automated test for exact tie construction yet (hard to force via realistic inputs); tie-break order is verified by code review of `STATE_PRIORITY` instead.

---

## Edge Case D — Malformed Section (missing required field)

A session with one well-formed section and one section missing a required field.

**Expected:** the malformed section is excluded from `results[]` and reported in `errors[]`; the well-formed section still processes normally (see `api_contract.md` §5.1).

---

## Coverage Checklist

| Area                              | Covered by                                           |
| --------------------------------- | ---------------------------------------------------- |
| Each of the 5 states individually | Scenarios 1–5                                        |
| Missing MCQ handling              | Edge Case A                                          |
| Division-by-zero / zero duration  | Edge Case B                                          |
| Tie-breaking determinism          | Edge Case C (code review, not yet an automated test) |
| Malformed input / partial failure | Edge Case D                                          |
| Focus Score boundary behavior     | Scenario 4                                           |
| **Real-time window path**         | **See `test_window_scenarios.md`**                   |
