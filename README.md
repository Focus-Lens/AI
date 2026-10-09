# AI2 — Behavioral Intelligence Service

Analyzes learner session behavior (scroll patterns, micro-challenge performance, app engagement) and returns **two granularities** of output:

* **Per-section** (end of session): detected learning state, focus score (0–100), and recommended adaptive action for each section.
* **Per-window** (real-time, every ~5 min): duration-weighted window focus score, dominant state, trend, and a **debounced** recommended action.

Rule-based / weighted-signal methodology — no ML/LLM. Fully explainable and reproducible.
Owned by: Hossam (AI Engineer).

> **Integration naming note:** In the current FocusLens integration, this Python behavioral-analysis service is called **AI 1** to distinguish it from the separate .NET learning-AI project. The existing `/ai2/...` route prefix and `AI2_*` environment variable names are retained for compatibility; do not rename them without coordinating with Backend.

---

## 1. Quick Start

```bash
# Run this from the repository root (AI2/)
cd "AI2 Behavioral Intelligence Service"

# 1. Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate      # on Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure service-to-service authentication.
# Use the SAME secret in the main .NET Backend (AI2_SERVICE_KEY).
export AI2_SERVICE_KEY="replace-with-a-long-random-secret"
# Local-only alternative when testing without the Backend:
# export AI2_AUTH_DISABLED=true
# Never disable authentication in a deployed environment.

# 4. Run the service
uvicorn api:app --reload --port 8000

# 5. Open the interactive API docs in your browser
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

* `test_scenarios.py` — end-of-session state and edge-case scenarios
* `test_p1_fixes.py` — missing telemetry semantics, MCQ evidence, timestamps, and authentication
* `test_p2_fixes.py` — window weighting and boundary validation
* `test_window_scenarios.py` — real-time window scoring, trend, debounce, escalation, and empty-window behavior

Run the complete `pytest tests/ -v` suite after any change to a threshold, weight, or scoring rule (83 tests in the reviewed version).

---

## 3. API Overview

### Service-to-service authentication

Both `/ai2/analyze-session` and `/ai2/analyze-window` require `X-Service-Key`. Configure the same secret as `AI2_SERVICE_KEY` in this service and in the calling .NET Backend. Missing or invalid keys return HTTP 401. `AI2_AUTH_DISABLED=true` is for local development only; never use it in a deployed environment.

### `GET /health`

Liveness check. Returns `{"status": "ok"}` if the service is running.

### `POST /ai2/analyze-session`

**End-of-session batch endpoint.** Backend calls this **once, at the end of a session**, with the full session payload (all sections visited). Returns one result object per section.

**Request body:** see [`docs/AI_Behavioral_Signals_Contract2.md`](./AI2%20Behavioral%20Intelligence%20Service/docs/AI_Behavioral_Signals_Contract2.md) for the full field reference.

**Response body:** see [`docs/api_contract.md`](./AI2%20Behavioral%20Intelligence%20Service/docs/api_contract.md) §2 for the full field reference, including error handling for partial failures (§5).

**Minimal example:**

```bash
curl -X POST http://localhost:8000/ai2/analyze-session \
  -H "Content-Type: application/json" \
  -H "X-Service-Key: $AI2_SERVICE_KEY" \
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
        "scroll_speed_avg_px_per_sec": 500.0,
        "scroll_direction_changes": 1,
        "content_progression_pct": 95,
        "section_revisit_count": 0,
        "interaction_count": 2,
        "micro_challenges": [
          {"question_id": "Q1", "response_time_seconds": 2, "is_correct": false},
          {"question_id": "Q2", "response_time_seconds": 2, "is_correct": false},
          {"question_id": "Q3", "response_time_seconds": 2, "is_correct": false}
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
      "confidence": 0.5,
      "focusScore": 66,
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

**Request body:** `AnalysisWindow` — see [`docs/api_contract.md`](./AI2%20Behavioral%20Intelligence%20Service/docs/api_contract.md) §3 for the full field reference.

**Key request fields:**

* `sections[]` — sections observed since the last window (may be empty)
* `history[]` — summaries of all previous windows (Backend owns this list)
* `is_final` — `true` on the last call of a session (triggers debounce cleanup)

**Response body:** see [`docs/api_contract.md`](./AI2%20Behavioral%20Intelligence%20Service/docs/api_contract.md) §4.

**Minimal example:**

```bash
curl -X POST http://localhost:8000/ai2/analyze-window \
  -H "Content-Type: application/json" \
  -H "X-Service-Key: $AI2_SERVICE_KEY" \
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
        "scroll_speed_avg_px_per_sec": 500.0,
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
  "window_active_time_seconds": 37.0,
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

See [`docs/debounce.md`](./AI2%20Behavioral%20Intelligence%20Service/docs/debounce.md) for the full rule set (2-minute window, severity ordering, TTL cleanup).

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
├── README.md
└── AI2 Behavioral Intelligence Service/
    ├── docs/                       # Methodology and API contracts
    ├── tests/
    │   ├── test_scenarios.py
    │   ├── test_p1_fixes.py
    │   ├── test_p2_fixes.py
    │   └── test_window_scenarios.py
    ├── adaptive_decision.py
    ├── api.py                      # FastAPI HTTP layer (2 endpoints)
    ├── data_models.py
    ├── debounce.py
    ├── feature_extraction.py
    ├── focus_score.py
    ├── pipeline.py
    ├── state_detection.py
    ├── trend_analysis.py
    ├── README.md
    └── requirements.txt
```

---

## 5. Methodology Documentation

Each stage of the pipeline has a corresponding design doc in [`docs/`](./AI2%20Behavioral%20Intelligence%20Service/docs) — read these for the *why* behind every threshold, weight, and decision rule:

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
10. **Session-level aggregation is Backend-owned.** Persist every window's `window_active_time_seconds` with its result; use it to calculate active-time-weighted session `focusQuality` and `focusState`, and derive `focusTrend` from chronological non-null window scores. Confirm product display thresholds with Backend/Product.

### Service Integration

11. Final HTTP path/naming convention for `/ai2/analyze-session` (`/ai2/analyze-session` is a proposal).
12. **Service-to-service authentication is implemented:** both analysis endpoints require `X-Service-Key`, matched against `AI2_SERVICE_KEY`; `AI2_AUTH_DISABLED=true` is for local development only.
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
* ☑ **Automated test suite passes (`pytest tests/ -v`): 83 tests in this reviewed version**
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
