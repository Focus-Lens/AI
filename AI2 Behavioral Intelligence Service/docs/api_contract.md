# Behavioral Intelligence — AI2 Output Schema & Backend API Contract

**Version:** 0.2 (Draft — adds real-time window endpoint)
**Owner:** Hossam — AI Engineer
**Depends on:** all prior documents (`data_dictionary`, `feature_thresholds`, `state_detection`, `focus_score`, `adaptive_decision`, `trend_analysis`, `debounce`)
**Output granularity:** **Dual.**

* `POST /ai2/analyze-session` — **per-section** results, one batch at end of session.
* `POST /ai2/analyze-window` — **per-window** result, one call every ~5 minutes during the session.

---

## 0. Where This Fits in the Flow

### End-of-session path (unchanged)

```text
Backend sends SessionPayload (data_dictionary.md)
        ↓
AI2 Service processes EACH section in `sections[]` independently
        ↓
AI2 returns an ARRAY of per-section results back to Backend
```

### Real-time path (new in v0.2)

```text
During the session, Backend periodically (every ~5 min) sends an
AnalysisWindow payload with:

- the sections observed since the last window
- the history of previous window summaries (score + state)
- an `is_final` flag (true if the student just closed the session)

        ↓

AI2 Service:

1. Analyzes each section in the window (per-section pipeline)
2. Computes a duration-weighted window focus score
3. Picks the dominant state (most frequent, severity tie-break)
4. Applies history-aware escalation (adaptive_decision.md §2)
5. Passes the action through debounce (debounce.md)

        ↓

AI2 returns a SINGLE window result:

- `window_focus_score`
- `window_state`
- `recommended_action` (or `"SUPPRESSED"`)
- `raw_action` (for observability)
- `trend` (IMPROVING / STABLE / DECLINING)
- `action_emitted` (bool)
```

**The AI2 service remains stateless across requests for session data.** Backend holds the session history and supplies it on every window call. The ONLY piece of cross-request state inside AI2 is the debounce store (in-memory, TTL 1h, see `debounce.md`).

---

## 1. End-of-Session Request (Backend → AI2)

Same shape as `SessionPayload` defined in `data_dictionary.md`. No changes.

```http
POST /ai2/analyze-session
Content-Type: application/json

Body: SessionPayload (see data_dictionary.md)
```

---

## 2. End-of-Session Response (AI2 → Backend)

```json
{
  "session_id": "sess_88392",
  "user_id": "usr_10293",
  "results": [
    {
      "section_id": "S003",
      "concept_id": "C008",
      "state": "SKIMMING",
      "confidence": 0.8,
      "focusScore": 68,
      "recommendedAction": "SHOW_EXPLANATION",
      "features_used": {
        "scroll_speed": "NORMAL",
        "scroll_pattern": "STABLE",
        "progression": "COMPLETE",
        "revisit": "NONE",
        "interaction": "NORMAL",
        "mcq_accuracy": "LOW",
        "mcq_response_time": "TOO_FAST",
        "disengagement": "FOCUSED"
      },
      "mcq_data_available": true
    }
  ]
}
```

### 2.1 Field Reference

| Field                          | Type            | Description                                                                                                       |
| ------------------------------ | --------------- | ----------------------------------------------------------------------------------------------------------------- |
| `session_id`                   | string          | Echoed from request, for traceability                                                                             |
| `user_id`                      | string          | Echoed from request                                                                                               |
| `results`                      | array           | One entry per section, same order as input `sections[]`                                                           |
| `results[].section_id`         | string          | Echoed from input                                                                                                 |
| `results[].concept_id`         | string          | Echoed from input                                                                                                 |
| `results[].state`              | enum            | One of: `CONTENT_DIFFICULTY`, `SKIMMING`, `WEAK_UNDERSTANDING`, `DISTRACTION_DISENGAGEMENT`, `NORMAL_FOCUSED`     |
| `results[].confidence`         | float (0–1)     | From `state_detection.md`                                                                                         |
| `results[].focusScore`         | integer (0–100) | From `focus_score.md`                                                                                             |
| `results[].recommendedAction`  | enum            | One of: `CONTINUE`, `SLOW_PACE`, `SHOW_EXPLANATION`, `INCREASE_ASSESSMENT_FREQUENCY`, `REASSESS`, `SUGGEST_BREAK` |
| `results[].features_used`      | object          | Classified feature vector for explainability/debugging                                                            |
| `results[].mcq_data_available` | boolean         | Whether MCQ-dependent conditions were included                                                                    |

> **Why include `features_used`?** Debuggability/explainability. If Product or QA asks "why did this section get `SKIMMING`?", the answer is right there without re-running the pipeline. Confirm with Backend whether it should be persisted or is log-only.

> **Note:** `reading_speed` is deliberately **not** in `features_used` — it was removed from the project (English-only content, no language branching).

---

## 3. Real-Time Request (Backend → AI2)

```http
POST /ai2/analyze-window
Content-Type: application/json

Body: AnalysisWindow
```

```json
{
  "user_id": "usr_10293",
  "session_id": "sess_88392",
  "window_index": 3,
  "window_start": 1694123300000,
  "window_end": 1694123600000,
  "is_final": false,
  "sections": [
    {
      "section_id": "S003",
      "concept_id": "C008",
      "section_start_time": 1694123456789,
      "section_end_time": 1694123501789,
      "time_spent_seconds": 45.0,
      "scroll_speed_avg_px_per_sec": 220.0,
      "scroll_direction_changes": 3,
      "content_progression_pct": 90.0,
      "section_revisit_count": 2,
      "interaction_count": 5,
      "micro_challenges": [
        {
          "question_id": "Q12",
          "response_time_seconds": 12.0,
          "is_correct": false
        }
      ],
      "background_count": 1,
      "total_background_seconds": 8.0,
      "tab_hidden_count": 0
    }
  ],
  "history": [
    {
      "window_index": 1,
      "focus_score": 72,
      "state": "NORMAL_FOCUSED",
      "dominant_action": "CONTINUE"
    },
    {
      "window_index": 2,
      "focus_score": 58,
      "state": "CONTENT_DIFFICULTY",
      "dominant_action": "SHOW_EXPLANATION"
    }
  ]
}
```

### 3.1 `AnalysisWindow` Field Reference

| Field          | Type                         | Required             | Description                                                                                                                    |
| -------------- | ---------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `user_id`      | string                       | Yes                  | Echoed from session                                                                                                            |
| `session_id`   | string                       | Yes                  | Echoed from session                                                                                                            |
| `window_index` | integer (≥ 1)                | Yes                  | 1-based index of this window within the session                                                                                |
| `window_start` | integer (unix ms)            | Yes                  | Window start timestamp                                                                                                         |
| `window_end`   | integer (unix ms)            | Yes                  | Window end timestamp. If the student closed early, this is `min(planned_end, actual_close_time)`.                              |
| `is_final`     | boolean                      | No (default `false`) | `true` if this is the last window of the session (student closed or planned end reached). **Triggers debounce state cleanup.** |
| `sections`     | array of `Section`           | Yes (may be `[]`)    | Sections observed during this window. Same shape as `data_dictionary.md` §2.                                                   |
| `history`      | array of `WindowHistoryItem` | Yes (may be `[]`)    | Summaries of all previous windows in this session, in order. **Backend owns this list.**                                       |

### 3.2 `WindowHistoryItem` Field Reference

| Field             | Type            | Description                                                                                               |
| ----------------- | --------------- | --------------------------------------------------------------------------------------------------------- |
| `window_index`    | integer         | 1-based index of the past window                                                                          |
| `focus_score`     | integer (0–100) | The `window_focus_score` AI2 returned for that window                                                     |
| `state`           | enum            | The `window_state` AI2 returned for that window                                                           |
| `dominant_action` | enum            | The **raw** action AI2 computed (not the debounced one). Backend decides whether to store raw or emitted. |

> **Why does Backend send `history` and not AI2?** AI2 is stateless per request (except debounce). Backend already has a session record; making it the source of truth keeps AI2 horizontally scalable without a shared database.

---

## 4. Real-Time Response (AI2 → Backend)

```json
{
  "session_id": "sess_88392",
  "window_index": 3,
  "window_focus_score": 68,
  "window_state": "CONTENT_DIFFICULTY",
  "recommended_action": "SHOW_EXPLANATION",
  "raw_action": "SHOW_EXPLANATION",
  "action_emitted": true,
  "trend": "DECLINING",
  "is_final": false,
  "sections_analyzed": 1,
  "sections": [
    {
      "section_id": "S003",
      "concept_id": "C008",
      "state": "CONTENT_DIFFICULTY",
      "confidence": 0.8,
      "focusScore": 68,
      "recommendedAction": "SHOW_EXPLANATION",
      "features_used": {
        "...": "..."
      },
      "mcq_data_available": true
    }
  ]
}
```

### 4.1 Response Field Reference

| Field                | Type                      | Description                                                                                                                   |
| -------------------- | ------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `session_id`         | string                    | Echoed from request                                                                                                           |
| `window_index`       | integer                   | Echoed from request                                                                                                           |
| `window_focus_score` | integer (0–100) OR `null` | Duration-weighted mean of per-section focus scores in this window. `null` if no sections were analysable (see §4.2).          |
| `window_state`       | enum                      | Dominant state of the window (most frequent, severity tie-break).                                                             |
| `recommended_action` | enum OR `"SUPPRESSED"`    | The action after debounce. If `action_emitted == false`, this is `"SUPPRESSED"` — Backend should **not** show a notification. |
| `raw_action`         | enum                      | What the decision layer computed before debounce. Always a real action. For observability only.                               |
| `action_emitted`     | boolean                   | `true` if the action passed debounce and should be shown.                                                                     |
| `trend`              | enum                      | `IMPROVING` / `STABLE` / `DECLINING` (from `trend_analysis.md`).                                                              |
| `is_final`           | boolean                   | Echoed from request. Useful for Backend to finalize session record.                                                           |
| `sections_analyzed`  | integer                   | How many sections in the window were successfully processed.                                                                  |
| `sections`           | array                     | Per-section detail, same shape as §2.1. Included for debugging/aggregation.                                                   |

### 4.2 Empty Window Response

If `sections == []` (student closed the app immediately after the previous window), AI2 returns:

```json
{
  "session_id": "sess_88392",
  "window_index": 4,
  "window_focus_score": null,
  "window_state": "NORMAL_FOCUSED",
  "recommended_action": "CONTINUE",
  "raw_action": "CONTINUE",
  "action_emitted": false,
  "trend": "STABLE",
  "is_final": true,
  "sections_analyzed": 0,
  "note": "empty_window",
  "sections": []
}
```

This is **not an error** — it's a normal outcome. Backend should treat it as "no behavioural data for this window, session ended."

---

## 5. Error Handling

| Scenario                                                                                              | Behavior                                                                                                                                                                                     |
| ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A section has no `micro_challenges`                                                                   | Not an error — processed normally, `mcq_data_available: false`, MCQ-dependent conditions excluded (see `state_detection.md` §7)                                                              |
| A section is missing a required raw field (e.g. `time_spent_seconds`)                                 | That section is skipped. In `/analyze-session` it goes into `errors[]`. In `/analyze-window` it's silently skipped (the window still returns with `sections_analyzed` reflecting the count). |
| All sections in a window are malformed                                                                | `sections_analyzed == 0` → treated as an empty window (see §4.2)                                                                                                                             |
| Entire payload is malformed (missing `session_id`, `sections` not an array, `window_index < 1`, etc.) | HTTP 400 via Pydantic validation, no result returned                                                                                                                                         |
| `time_spent_seconds == 0` for a section                                                               | Rate-based features use their zero-state (`scroll_pattern=STABLE`, `interaction=NONE`) — no crash                                                                                            |
| Window's `sections` empty but history shows a serious issue                                           | Still returns `CONTINUE` — no escalation without current-window evidence. This is intentional: we don't punish a learner for a window where we have no data.                                 |

### 5.1 Partial Failure Response Shape (`/analyze-session` only)

```json
{
  "session_id": "sess_88392",
  "user_id": "usr_10293",
  "results": [
    /* successfully processed sections */
  ],
  "errors": [
    {
      "section_id": "S007",
      "reason": "missing_required_field",
      "detail": "time_spent_seconds"
    }
  ]
}
```

---

## 6. Debounce Semantics (important for Backend)

Backend MUST honour the `action_emitted` flag:

* `action_emitted == true` → show `recommended_action` to the learner.
* `action_emitted == false` → **do not** show anything. The `raw_action` field is available for logging/analytics, not for display.

If Backend ignores `action_emitted` and shows `recommended_action` anyway, the learner may see `"SUPPRESSED"` as a literal string — clearly wrong, but a useful tripwire during integration.

See `debounce.md` for the full rule set (severity ordering, 2-minute window, TTL cleanup).

---

## 7. Timing / Cadence (Backend's Responsibility)

AI2 does not enforce a cadence. Backend is expected to:

* Call `/ai2/analyze-window` every ~5 minutes during an active session.
* On early session end (student closes the app), call once more with the partial sections and `is_final: true`.
* Include all previous window summaries in `history` on every call.
* Not call again for the same session after `is_final: true`.

**If Backend deviates from 5 minutes:** the scoring still works, but the `trend` analysis (`compute_trend`) assumes roughly-equal spacing. Very irregular windows may produce noisier trends.
