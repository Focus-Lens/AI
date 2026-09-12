# Behavioral Intelligence — AI2 Output Schema & Backend API Contract

**Version:** 0.1 (Draft)
**Owner:** Hossam — AI Engineer
**Depends on:** all prior documents (data_dictionary, feature_thresholds, state_detection, focus_score, adaptive_decision)
**Output granularity:** **Per-section** — one result object is produced for every section in the session payload, not one aggregate per session.

---

## 0. Where This Fits in the Flow

```
Backend sends SessionPayload (see data_dictionary.md) to AI2 Service
        ↓
AI2 Service processes EACH section in `sections[]` independently
        ↓
AI2 returns an ARRAY of per-section results back to Backend
```

The AI2 service is **stateless per request** — it receives the full session payload once (batch, per `data_dictionary.md` §1), processes every section, and returns all results together in a single response. It does not need to be called once per section.

---

## 1. Request (Backend → AI2 Service)

Same shape as `SessionPayload` defined in `data_dictionary.md`. No changes needed here — this document only defines the **response**.

```
POST /ai2/analyze-session
Content-Type: application/json

Body: SessionPayload  (see data_dictionary.md)
```

---

## 2. Response (AI2 Service → Backend)

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
        "reading_speed": "FAST",
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

| Field | Type | Description |
|---|---|---|
| `session_id` | string | Echoed from request, for traceability |
| `user_id` | string | Echoed from request |
| `results` | array | One entry per section, same order as input `sections[]` |
| `results[].section_id` | string | Echoed from input |
| `results[].concept_id` | string | Echoed from input |
| `results[].state` | enum | One of: `CONTENT_DIFFICULTY`, `SKIMMING`, `WEAK_UNDERSTANDING`, `DISTRACTION_DISENGAGEMENT`, `NORMAL_FOCUSED` |
| `results[].confidence` | float (0–1) | From `state_detection.md` — how strongly the state was detected |
| `results[].focusScore` | integer (0–100) | From `focus_score.md` |
| `results[].recommendedAction` | enum | One of: `CONTINUE`, `SLOW_PACE`, `SHOW_EXPLANATION`, `INCREASE_ASSESSMENT_FREQUENCY`, `REASSESS`, `SUGGEST_BREAK` |
| `results[].features_used` | object | The classified feature vector that led to this decision — included for **debuggability/explainability**, not required for Backend logic |
| `results[].mcq_data_available` | boolean | Whether MCQ-dependent conditions were included in scoring — useful for Backend/Product to flag low-reliability results |

> **Why include `features_used`?** It's not strictly required for Backend to function, but it makes the system auditable — if Product or QA asks "why did this section get `SKIMMING`?", the answer is right there without re-running the pipeline. Recommend keeping it, but confirm with Backend whether it should be persisted or just logged.

---

## 3. Error Handling

| Scenario | Behavior |
|---|---|
| A section has no `micro_challenges` | Not an error — processed normally, `mcq_data_available: false`, MCQ-dependent conditions excluded (see `state_detection.md` §7) |
| A section is missing a required raw field (e.g. `time_spent_seconds`) | That section is skipped from `results[]`; an `errors[]` array is added to the response (see §3.1) — do NOT fail the entire request for one bad section |
| Entire payload is malformed (missing `session_id`, `sections` not an array, etc.) | HTTP 400, no `results` returned |
| `time_spent_seconds == 0` for a section (division-by-zero risk in rate calculations) | Treat rate-based features (`scroll_pattern`, `interaction`) as `NONE`/`STABLE` (their zero-state) rather than crashing |

### 3.1 Partial Failure Response Shape

```json
{
  "session_id": "sess_88392",
  "user_id": "usr_10293",
  "results": [ /* successfully processed sections */ ],
  "errors": [
    {
      "section_id": "S007",
      "reason": "missing_required_field",
      "field": "time_spent_seconds"
    }
  ]
}
```

---

## 4. Open Points (to finalize with Backend)

- [ ] Confirm the actual HTTP endpoint path/naming convention used by Backend's service registry.
- [ ] Confirm whether `features_used` should be persisted in Backend's DB or is log-only/debug-only.
- [ ] Confirm authentication/service-to-service auth mechanism (API key, internal token, etc.) — not an AI2-owned decision.
- [ ] Confirm retry/timeout behavior expected by Backend if AI2 service is slow or down.
- [ ] Decide whether a session-level aggregate (e.g. average focusScore across all sections) is needed anywhere downstream (e.g. for a student dashboard) — if yes, decide whether that aggregation happens in AI2 or in Backend. Current recommendation: **Backend aggregates**, since AI2's job is per-section analysis, not session-level UI logic.

---

*This is the final contract document tying together data_dictionary.md → feature_thresholds.md → state_detection.md → focus_score.md → adaptive_decision.md into one deliverable. Once confirmed with Backend, this becomes the source of truth for the AI2 service's public interface.*
