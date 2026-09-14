# Real-Time Window Test Scenarios — `test_window_scenarios.py`

## Purpose

Regression tests for the **real-time path** introduced alongside
`/ai2/analyze-window`.

These tests cover everything that the original `test_scenarios.md`
(end-of-session tests) does **not** cover:

* `analyze_window()` in `pipeline.py`
* `weighted_window_score()` in `focus_score.py`
* `trend_analysis.py` (all three functions)
* `debounce.py` (all rules and edge cases)
* Escalation rules in `adaptive_decision.py`
* Empty-window handling
* `is_final` handling

The end-of-session tests remain in `test_regression.py` unchanged.

---

## Test Organisation

The file is divided into six sections, mirroring the layers it tests:

| Section                              | What It Tests                               |
| ------------------------------------ | ------------------------------------------- |
| **A. `weighted_window_score`**       | Duration-weighted aggregation mathematics   |
| **B. `trend_analysis`**              | Trend verdict and consecutive counters      |
| **C. Debounce**                      | All emit/suppress rules                     |
| **D. `analyze_window` (happy path)** | Single-section and multi-section windows    |
| **E. `analyze_window` (edge cases)** | Empty window, `is_final`, malformed section |
| **F. `analyze_window` (escalation)** | Escalation rules firing correctly           |

---

## Fixtures & Helpers

### `make_section(**overrides) -> Section`

Builds a valid `Section` with focused defaults:

* 60 seconds duration
* 100% progression
* 2 interactions

This is the same helper used by the end-of-session tests. It is intentionally duplicated so the two test files can evolve independently.

---

### `make_window(**overrides) -> AnalysisWindow`

Builds a valid `AnalysisWindow` with:

* An empty section list
* `is_final=False`
* Empty history

Individual tests can override these defaults as needed.

---

### `make_history_item(window_index, focus_score, state) -> WindowHistoryItem`

Convenience builder for creating history entries.

It keeps the test cases concise and makes the intended history sequence easier to read.

---

### `_clean_debounce` (autouse)

**Critical:** `debounce_store` is a module-level singleton.

Without this fixture, a test that emits:

```text
SLOW_PACE
```

for:

```text
s_test
```

could leak its state into the next test that reuses the same session ID.

The fixture clears:

```python
debounce_store._store
```

after every test to prevent cross-test pollution.

---

## Why the Numbers in Assertions Are Exact

Several tests intentionally assert exact values, such as:

```text
focusScore == 100
weighted == 3
```

This is intentional because:

* The adjustments in `focus_score.py` are fixed constants.
* If someone changes those constants, the tests **should fail**.
* Such a failure signals that the scoring behaviour has changed.
* Floating-point round-off is handled by `round()` inside the pipeline.
* Therefore, exact integer comparison is safe.

If the constants are intentionally changed, the corresponding tests must be updated in the same PR.

This makes scoring changes **explicit and reviewable**.

---

## Section-by-Section Notes

### A. `weighted_window_score`

#### `test_weighted_score_duration_dominates`

Tests the core contract:

> A 290-second section should outweigh a 10-second section.

The expected value of `3` is intentionally low to make the **"long section dominates"** behaviour obvious.

---

#### `test_weighted_score_equal_weights_equals_simple_mean`

Verifies that when section durations are equal:

```text
weighted average == simple mean
```

This provides a sanity check for the weighting formula.

---

#### `test_weighted_score_zero_total_time_falls_back_to_mean`

Tests the zero-total-duration edge case and ensures the implementation safely falls back to the simple mean instead of producing a division-by-zero error.

---

### B. `trend_analysis`

#### `test_compute_trend_uses_last_three_only`

Guarantees that `compute_trend()` considers only the most recent three scores and does not accidentally use the entire history.

---

#### `test_consecutive_state_count`

Verifies:

* The `+1` contribution from the current window.
* Correct backwards traversal.
* Correct stop-at-mismatch behaviour.

---

#### `test_consecutive_low_score_count_current_ok`

Verifies the short-circuit behaviour when the current focus score is already above the low-score threshold.

---

### C. Debounce

#### `test_debounce_same_action_after_window_passes`

Uses:

```python
monkeypatch.setattr(time, "time", ...)
```

to simulate the passage of time.

**Important:** this test relies on `debounce.py` using:

```python
import time
```

rather than:

```python
from time import time
```

If the import style changes, the monkeypatch target in this test must be updated accordingly.

---

#### `test_debounce_escalation_always_passes`

This is one of the most important debounce guarantees.

The system must never suppress a higher-severity action because a lower-severity action was recently emitted.

For example:

```text
SLOW_PACE
    ↓
SUGGEST_BREAK
```

The `SUGGEST_BREAK` action must still be emitted.

---

### D. Happy Path

#### `test_window_dominant_state_is_most_frequent`

Verifies the dominant-state selection rule using a **2-vs-1 vote**.

It also verifies the tie-break-by-severity behaviour when applicable.

---

### E. Edge Cases

#### `test_window_empty_sections_does_not_crash`

Represents the case where a student opens and closes a session immediately.

The expected behaviour is:

```text
empty_window
```

rather than a crash.

---

#### `test_window_is_final_clears_debounce`

Verifies the memory-hygiene contract between the pipeline and the debounce store.

When:

```python
window.is_final == True
```

the session's debounce state must be cleared.

---

#### `test_window_malformed_section_is_skipped`

Mirrors the partial-failure test from the end-of-session path, but at the real-time window level.

A malformed section should be skipped rather than causing the entire window analysis to fail.

---

### F. Escalation

#### `test_window_escalation_repeated_distraction_suggests_break`

This is the primary reason `trend_analysis.py` exists.

It verifies that persistent distraction across consecutive windows eventually escalates to:

```text
SUGGEST_BREAK
```

---

#### `test_window_escalation_consecutive_low_scores`

Tests the same escalation concept using consecutive low focus scores instead of repeated state.

---

#### `test_window_declining_trend_upgrades_slow_pace`

Tests the **"upgrade, not replace"** rule.

A:

```text
SLOW_PACE
```

recommendation should be upgraded to:

```text
SHOW_EXPLANATION
```

when the overall trend is:

```text
DECLINING
```

---

## Running the Tests

### All Tests

```bash
pytest tests/ -v
```

### Real-Time Path Only

```bash
pytest tests/test_window_scenarios.py -v
```

### Debounce Tests Only

```bash
pytest tests/test_window_scenarios.py -v -k debounce
```

### Trend Tests Only

```bash
pytest tests/test_window_scenarios.py -v -k trend
```

### Escalation Tests Only

```bash
pytest tests/test_window_scenarios.py -v -k escalation
```

---

## Coupling with Other Modules

Changes in certain modules or constants may require corresponding test updates.

| If You Change...                                         | You Must Update...                                                             |
| -------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `DEBOUNCE_WINDOW_SECONDS`                                | `test_debounce_same_action_after_window_passes`                                |
| `SEVERITY_ORDER`                                         | `test_debounce_escalation_always_passes`, `test_debounce_downgrade_suppressed` |
| `import time` → `from time import time` in `debounce.py` | Monkeypatch targets in debounce tests                                          |
| Any constant in `focus_score.ADJUSTMENTS`                | Expected `focusScore` values in happy-path tests                               |
| `trend_analysis` thresholds (`8 / 3`)                    | `test_compute_trend_improving`, `test_compute_trend_declining`                 |
| `STATE_PRIORITY` order                                   | `test_window_dominant_state_is_most_frequent`                                  |

---

## Open Points

### 1. Time-Based Tests

The debounce expiry test uses `monkeypatch` to simulate time.

If more time-dependent tests are added in the future, consider introducing a proper clock abstraction such as:

```python
now_fn
```

instead of patching:

```python
time.time
```

globally.

---

### 2. Property-Based Tests

A future `hypothesis` test could generate random windows and verify the invariant:

```text
empty input → no crash
```

This would provide additional confidence against unexpected edge cases.

This is currently **out of scope for the MVP**.

---

### 3. Integration Test

The current tests call:

```python
analyze_window()
```

directly rather than testing the HTTP endpoint.

A future `TestClient`-based test for:

```text
/ai2/analyze-window
```

would additionally catch Pydantic validation or API-schema regressions.

This should be added if the request/response schema begins to change frequently.

---

### 4. Flakiness Risk

`test_debounce_same_action_after_window_passes` is currently the only test that manipulates time.

All other tests use real time and complete within microseconds.

This is considered acceptable for the MVP.
