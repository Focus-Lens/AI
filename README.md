# AI2 — Behavioral Intelligence Service

Analyzes learner session behavior (reading speed, scroll patterns, micro-challenge performance, app engagement) and returns, **per section**: a detected learning state, a focus score (0–100), and a recommended adaptive action.

Rule-based / weighted-signal methodology — no ML/LLM. Fully explainable and reproducible. Owned by: Hossam (AI Engineer).

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

## 2. Run the Tests

```bash
pytest tests/ -v
```

All 8 scenarios (5 learning states + 3 edge cases) should pass. Run this after any change to a threshold, weight, or scoring rule.

---

## 3. API Overview

### `GET /health`
Liveness check. Returns `{"status": "ok"}` if the service is running.

### `POST /ai2/analyze-session`
Main endpoint. Backend calls this **once, at the end of a session**, with the full session payload (all sections visited). Returns one result object per section.

**Request body:** see [`docs/data_dictionary.md`](./docs/data_dictionary.md) for the full field reference.

**Response body:** see [`docs/api_contract.md`](./docs/api_contract.md) for the full field reference, including error handling for partial failures.

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
        "reading_speed_wpm": 300,
        "time_spent_seconds": 60,
        "scroll_direction_changes": 1,
        "content_progression_pct": 95,
        "section_revisit_count": 0,
        "interaction_count": 2,
        "micro_challenges": [
          {"question_id": "Q1", "response_time_seconds": 2, "is_correct": false}
        ],
        "background_count": 0,
        "total_background_seconds": 0
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
      "focusScore": 63,
      "recommendedAction": "SHOW_EXPLANATION",
      "features_used": { "...": "..." },
      "mcq_data_available": true
    }
  ]
}
```

---

## 4. Project Structure

```
ai2_service/
├── data_models.py          # SessionPayload, Section, MicroChallenge (data classes + from_dict parsing)
├── feature_extraction.py   # Raw signals -> classified features (thresholds)
├── state_detection.py      # Classified features -> learning state + confidence
├── focus_score.py          # Features + state -> 0-100 focus score
├── adaptive_decision.py    # (state, score) -> recommended action
├── pipeline.py             # Ties the above together per section / per session
├── api.py                  # FastAPI HTTP layer — the only entry point Backend calls
├── requirements.txt
├── .gitignore
├── tests/
│   └── test_scenarios.py   # Automated regression tests for all states + edge cases
└── docs/                    # Full methodology documentation (see below)
    ├── data_dictionary.md
    ├── feature_thresholds.md
    ├── state_detection.md
    ├── focus_score.md
    ├── adaptive_decision.md
    ├── api_contract.md
    └── test_scenarios.md
```

## 5. Methodology Documentation

Each stage of the pipeline has a corresponding design doc in [`docs/`](./docs) — read these for the *why* behind every threshold, weight, and decision rule:

| Doc | Covers |
|---|---|
| `docs/data_dictionary.md` | Input payload schema (what Backend/Frontend must send) |
| `docs/feature_thresholds.md` | How raw signals are classified into categories |
| `docs/state_detection.md` | How classified features combine into a learning state |
| `docs/focus_score.md` | How the 0–100 focus score is computed |
| `docs/adaptive_decision.md` | How (state, score) maps to a recommended action |
| `docs/api_contract.md` | Full request/response schema + error handling contract |
| `docs/test_scenarios.md` | Test case reference (input → expected output) |

---

## 6. Open Points — Needs Confirmation with Backend/Frontend

These are tracked in detail inside each doc above, summarized here for convenience:

1. How repeated visits to the same section are represented (merged vs. multiple entries) — assumed **merged** for now.
2. Unit for `scroll_speed_avg_px_per_sec` (raw px vs. density-independent dp) — thresholds are placeholders until confirmed.
3. Null/missing field convention from Frontend (0 vs. `null`).
4. Final HTTP path/naming convention expected by Backend's service registry (`/ai2/analyze-session` is a proposal, not final).
5. Service-to-service auth mechanism.
6. Retry/timeout behavior expected if this service is slow or down.
7. Whether session-level aggregation (e.g. average focus score across sections) is needed anywhere — current recommendation: Backend aggregates, this service only returns per-section results.
8. Naming convention consistency: most fields are `snake_case`, but `focusScore`/`recommendedAction` are `camelCase` (matching the original spec example) — confirm whether Backend wants full consistency in either direction.

---

## 7. Status

- [x] Core logic implemented and unit-tested (8/8 passing)
- [x] HTTP API implemented (FastAPI + Pydantic validation)
- [ ] Deployment configuration (Docker, hosting) — not yet addressed, pending Backend/DevOps input
- [ ] Open Points above confirmed with Backend/Frontend
