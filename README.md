# AI2 — Behavioral Intelligence Service

Analyzes learner session behavior (scroll patterns, micro-challenge performance, app engagement) and returns **two granularities** of output:

* **Per-section** (end of session): detected learning state, focus score (0–100), and recommended adaptive action for each section.
* **Per-window** (real-time, every ~5 min): duration-weighted window focus score, dominant state, trend, and a **debounced** recommended action.

Rule-based / weighted-signal methodology — no ML/LLM. Fully explainable and reproducible.
Owned by: Hossam (AI Engineer).

---

## 1. Quick Start

```bash
# 1. Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate      # on Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the service
uvicorn api:app --reload --port 8000

# 4. Open the interactive API docs in your browser
#    http://localhost:8000/docs
```

---

## 2. Run the Tests

```bash
# All tests (end-of-session + real-time window)
pytest tests/ -v

# Only end-of-session scenarios
pytest tests/test_scenarios.py -v

# Only real-time window scenarios
pytest tests/test_window_scenarios.py -v
```

All scenarios should pass:

* **8 end-of-session cases** (5 learning states + 3 edge cases) in `test_scenarios.py`
* **~25 real-time cases** (weighted score, trend, debounce, escalation, empty window) in `test_window_scenarios.py`

Run both files after any change to a threshold, weight, or scoring rule.

---

## 3. API Overview

### `GET /health`

Liveness check. Returns `{"status": "ok"}` if the service is running.

### `POST /ai2/analyze-session`

**End-of-session batch endpoint.** Backend calls this **once, at the end of a session**, with the full session payload (all sections visited). Returns one result object per section.

**Request body:** see [`docs/AI_Behavioral_Signals_Contract2.md`](./docs/AI_Behavioral_Signals_Contract2.md) for the full field reference.

**Response body:** see [`docs/api_contract.md`](./docs/api_contract.md) §2 for the full field reference, including error handling for partial failures (§5).

**Minimal example:**

```bash
curl -X POST http://localhost:8000/ai2/analyze-session \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "usr_10293",
    "session_id": "sess_88392",
    "session_start": 1694123000000,
    "session_end": 1694124500000,
    "sections": [
      {
        "section_id": "S003",
        "concept_id": "C008",
        "time_spent_seconds": 60,
        "scroll_speed_avg_px_per_sec": 220.0,
        "scroll_direction_changes": 1,
        "content_progression_pct": 95,
        "section_revisit_count": 0,
        "interaction_count": 2,
        "micro_challenges": [
          {
            "question_id": "Q1",
            "response_time_seconds": 2,
            "is_correct": false
          }
        ],
        "background_count": 0,
        "total_background_seconds": 0,
        "tab_hidden_count": 0
      }
    ]
  }'
```

**Response:**

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
      "focusScore": 56,
      "recommendedAction": "SHOW_EXPLANATION",
      "features_used": {
        "...": "..."
      },
      "mcq_data_available": true
    }
  ]
}
```

### `POST /ai2/analyze-window`

**Real-time periodic endpoint (new).** Backend calls this **every ~5 minutes during an active session** (or earlier if the student closes the app). Returns a single window-level result with a debounced recommended action.

**Request body:** `AnalysisWindow` — see [`docs/api_contract.md`](./docs/api_contract.md) §3 for the full field reference.

**Key request fields:**

* `sections[]` — sections observed since the last window (may be empty)
* `history[]` — summaries of all previous windows (Backend owns this list)
* `is_final` — `true` on the last call of a session (triggers debounce cleanup)

**Response body:** see [`docs/api_contract.md`](./docs/api_contract.md) §4.

**Minimal example:**

```bash
curl -X POST http://localhost:8000/ai2/analyze-window \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "usr_10293",
    "session_id": "sess_88392",
    "window_index": 2,
    "window_start": 1694123300000,
    "window_end": 1694123600000,
    "is_final": false,
    "sections": [
      {
        "section_id": "S003",
        "concept_id": "C008",
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
      }
    ]
  }'
```

**Response:**

```json
{
  "session_id": "sess_88392",
  "window_index": 2,
  "window_focus_score": 58,
  "window_state": "CONTENT_DIFFICULTY",
  "recommended_action": "SHOW_EXPLANATION",
  "raw_action": "SHOW_EXPLANATION",
  "action_emitted": true,
  "trend": "DECLINING",
  "is_final": false,
  "sections_analyzed": 1,
  "sections": [
    {
      "...": "..."
    }
  ]
}
```

### 3.1 Debounce — Important for Backend Integration

`recommended_action` is **post-debounce**. Backend MUST honour the `action_emitted` flag:

* `action_emitted == true` → show `recommended_action` to the learner.
* `action_emitted == false` → **do not show anything**. `recommended_action` will literally be the string `"SUPPRESSED"`. Use `raw_action` for logging/analytics only.

See [`docs/debounce.md`](./docs/debounce.md) for the full rule set (2-minute window, severity ordering, TTL cleanup).

### 3.2 Session Lifecycle (Backend's Responsibility)

AI2 does not enforce a cadence. Backend is expected to:

1. Call `/ai2/analyze-window` every ~5 min during an active session.
2. On early session end (student closes app), call once more with the partial sections and `is_final: true`.
3. Include all previous window summaries in `history` on every call.
4. Not call again for the same session after `is_final: true`.
5. Optionally call `/ai2/analyze-session` at the very end for the per-section breakdown (e.g. for the report UI).

---

## 4. Project Structure

```text
AI2/
├── docs/                          # Full methodology documentation
│   ├── adaptive_decision.md
│   ├── AI_Behavioral_Signals_Contract2.md
│   ├── api_contract.md
│   ├── debounce.md                # NEW — debounce rules & lifecycle
│   ├── feature_thresholds.md
│   ├── focus_score.md
│   ├── state_detection.md
│   ├── test_scenarios.md          # End-of-session test reference
│   ├── test_window_scenarios.md   # NEW — real-time test reference
│   └── trend_analysis.md          # NEW — trend & escalation signals
├── tests/
│   ├── test_scenarios.py          # End-of-session regression tests (8)
│   └── test_window_scenarios.py   # NEW — real-time regression tests (~25)
├── adaptive_decision.py           # UPDATED — escalation rules
├── api.py                         # FastAPI HTTP layer (2 endpoints)
├── data_models.py                 # UPDATED — AnalysisWindow, WindowHistoryItem
├── debounce.py                    # NEW — in-memory debounce store
├── feature_extraction.py          # UPDATED — reading_speed removed
├── focus_score.py                 # UPDATED — weighted_window_score()
├── pipeline.py                    # UPDATED — analyze_window()
├── state_detection.py             # UPDATED — reading_speed removed
├── trend_analysis.py              # NEW — compute_trend + consecutive counters
├── .gitignore
├── README.md
└── requirements.txt
```

---

## 5. Methodology Documentation

Each stage of the pipeline has a corresponding design doc in [`docs/`](./docs) — read these for the *why* behind every threshold, weight, and decision rule:

| Doc                                       | Covers                                                      |
| ----------------------------------------- | ----------------------------------------------------------- |
| `docs/AI_Behavioral_Signals_Contract2.md` | Input payload schema (what Backend/Frontend must send)      |
| `docs/feature_thresholds.md`              | How raw signals are classified into categories              |
| `docs/state_detection.md`                 | How classified features combine into a learning state       |
| `docs/focus_score.md`                     | Per-section score + duration-weighted window score          |
| `docs/adaptive_decision.md`               | (state, score) → action, plus cross-window escalation rules |
| `docs/trend_analysis.md`                  | Trend verdicts + consecutive counters over window history   |
| `docs/debounce.md`                        | Suppression rules for repeated actions                      |
| `docs/api_contract.md`                    | Full request/response schema for both endpoints             |
| `docs/test_scenarios.md`                  | End-of-session test reference (input → expected output)     |
| `docs/test_window_scenarios.md`           | Real-time window test reference                             |

### Pipeline Overview

```text
                    ┌─────────────────────────────────────────┐
                    │        End-of-Session Path              │
                    │  POST /ai2/analyze-session              │
                    └─────────────────────────────────────────┘
Raw Signals → Features → State → Focus Score (per section) → Action (per section)
                    │
                    ▼
                    ┌─────────────────────────────────────────┐
                    │        Real-Time Path (every ~5 min)    │
                    │  POST /ai2/analyze-window               │
                    └─────────────────────────────────────────┘
Raw Signals → Features → State → Focus Score (per section)
                                       │
                                       ▼
                          Duration-weighted window score
                                       │
                                       ▼
                          Dominant state + history signals
                                       │
                                       ▼
                          Base action + escalation rules
                                       │
                                       ▼
                          Debounce → emitted action
```

---

## 6. Open Points — Needs Confirmation with Backend/Frontend

These are tracked in detail inside each doc above, summarized here for convenience:

### Input / Data Shape

1. How repeated visits to the same section are represented (merged vs. multiple entries) — assumed **merged** for now.
2. Unit for `scroll_speed_avg_px_per_sec` (raw px vs. density-independent dp) — thresholds are placeholders until confirmed.
3. Null/missing field convention from Frontend (0 vs. `null`).
4. Whether `reading_speed_wpm` is fully removed from Backend/Frontend payloads too — **confirmed removed on the AI2 side**; Backend must not send it.

### Real-Time Path (new)

5. Confirm the actual HTTP endpoint path for `/ai2/analyze-window` with Backend's service registry.
6. Confirm `window_index` is 1-based (current assumption) vs 0-based.
7. Confirm the ~5-minute cadence is Backend's responsibility and AI2 does not need to enforce it.
8. Confirm whether `history[].dominant_action` should store the **raw** action or the **emitted** (post-debounce) action. Currently documented as raw.
9. Confirm Backend will honour `action_emitted == false` by not showing any notification.
10. Confirm session-level aggregation (e.g. the final report `focusScore`) is Backend's job. Current recommendation: **Backend aggregates** by taking a duration-weighted mean of the `window_focus_score` values it already has.

### Service Integration

11. Final HTTP path/naming convention for `/ai2/analyze-session` (`/ai2/analyze-session` is a proposal).
12. Service-to-service auth mechanism.
13. Retry/timeout behavior expected if this service is slow or down. **Especially important for `/ai2/analyze-window`**: a missed window means a missed notification, not a corrupted session.

### Conventions

14. Naming convention consistency: most fields are `snake_case`, but `focusScore`/`recommendedAction` are `camelCase` (matching the original spec example). New real-time response fields use `snake_case` (`window_focus_score`, `recommended_action`, `action_emitted`). Confirm whether Backend wants full consistency in either direction before finalizing.

---

## 7. Status

* ☑ **Core logic implemented and unit-tested (8/8 end-of-session passing)**
* ☑ **Real-time window path implemented (weighted scoring, trend, escalation, debounce)**
* ☑ **Real-time unit tests written (~25 cases in `test_window_scenarios.py`)**
* ☑ **`reading_speed` feature removed; all downstream modules updated**
* ☑ **HTTP API implemented (FastAPI + Pydantic validation, 2 endpoints)**
* □ **Confirm real-time test suite passes end-to-end (`pytest tests/ -v`)**
* □ **Deployment configuration (Docker, hosting)** — not yet addressed, pending Backend/DevOps input
* □ **Open Points above confirmed with Backend/Frontend**

---

## 8. Local Development Tips

### Run with auto-reload

```bash
uvicorn api:app --reload --port 8000
```

### Interactive API docs

Open `http://localhost:8000/docs` — FastAPI auto-generates a Swagger UI. Both `/ai2/analyze-session` and `/ai2/analyze-window` are testable directly from the browser.

### Reset debounce state between manual tests

The debounce store is in-memory and per-session. If you're manually testing `/ai2/analyze-window` and want a clean slate without restarting the server, either:

* Use a different `session_id`, or
* Send a request with `is_final: true` (which triggers cleanup), or
* Restart the server.

### Logging

Both endpoints return `raw_action` alongside `recommended_action`. When debugging "why didn't the learner get a notification?", check `action_emitted` first — if `false`, the debounce layer suppressed it (which is normal for repeated actions within 2 minutes).
