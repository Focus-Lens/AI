# Behavioral Intelligence — Adaptive Decision Methodology

**Version:** 0.1 (Draft — MVP, per-section decision only, no cross-section history)
**Owner:** Hossam — AI 
**Depends on:** `state_detection.md` (state + confidence), `focus_score.md` (focusScore)
**Purpose:** Maps a detected (state, focusScore) pair to a concrete recommended action. Simple lookup table — no ML/LLM (per spec 2.5).

**Scope note (MVP):** Decision is based only on the current section's (state, focusScore). It does NOT consider repetition of the same state across multiple consecutive sections in the session. This is a deliberate simplification for the MVP — see Open Points for the future enhancement.

---

## 0. Core Principle

Each Learning State has one or more Focus Score "bands." As the score drops within a state, the recommended action escalates in severity. This is a direct lookup, not a weighted calculation — the hard reasoning already happened in the State Detection and Focus Score layers.

---

## 1. Decision Table

### `CONTENT_DIFFICULTY`

| Focus Score | Action | Rationale |
|---|---|---|
| ≥ 70 | `SLOW_PACE` | Mild difficulty — slowing down is enough |
| 40 – 69 | `SHOW_EXPLANATION` | Clear difficulty — needs actual extra explanation |
| < 40 | `REASSESS` | Severe difficulty — need to confirm foundational understanding |

### `SKIMMING`

| Focus Score | Action | Rationale |
|---|---|---|
| ≥ 70 | `INCREASE_ASSESSMENT_FREQUENCY` | Light skimming — more questions re-engage attention |
| 40 – 69 | `SHOW_EXPLANATION` | Clear skimming with comprehension gap — needs re-exposure to content |
| < 40 | `REASSESS` | Severe skimming — content not being absorbed at all |

### `WEAK_UNDERSTANDING`

| Focus Score | Action | Rationale |
|---|---|---|
| ≥ 60 | `SHOW_EXPLANATION` | Mild comprehension gap — extra explanation suffices |
| < 60 | `REASSESS` | Clear comprehension gap — needs deeper evaluation before continuing |

> No `SLOW_PACE` option here: reading speed is already normal, so pacing isn't the issue — the problem is comprehension, requiring direct intervention.

### `DISTRACTION_DISENGAGEMENT`

| Focus Score | Action | Rationale |
|---|---|---|
| ≥ 50 | `SLOW_PACE` | Mild distraction — slowing down may help refocus |
| < 50 | `SUGGEST_BREAK` | Severe distraction — better to rest than continue poorly |

### `NORMAL_FOCUSED`

| Focus Score | Action |
|---|---|
| any | `CONTINUE` |

---

## 2. Implementation

```python
DECISION_TABLE = {
    "CONTENT_DIFFICULTY": [
        (70, 100, "SLOW_PACE"),
        (40, 69,  "SHOW_EXPLANATION"),
        (0,  39,  "REASSESS"),
    ],
    "SKIMMING": [
        (70, 100, "INCREASE_ASSESSMENT_FREQUENCY"),
        (40, 69,  "SHOW_EXPLANATION"),
        (0,  39,  "REASSESS"),
    ],
    "WEAK_UNDERSTANDING": [
        (60, 100, "SHOW_EXPLANATION"),
        (0,  59,  "REASSESS"),
    ],
    "DISTRACTION_DISENGAGEMENT": [
        (50, 100, "SLOW_PACE"),
        (0,  49,  "SUGGEST_BREAK"),
    ],
    "NORMAL_FOCUSED": [
        (0, 100, "CONTINUE"),
    ],
}

def get_recommended_action(state: str, focus_score: int) -> str:
    for low, high, action in DECISION_TABLE[state]:
        if low <= focus_score <= high:
            return action
    return "CONTINUE"  # fallback safety net — should never be hit if table is exhaustive
```

---

## 3. Full Pipeline Recap (how all documents connect)

```
Raw Events/Signals (Data Dictionary)
        ↓
Classified Features (feature_thresholds.md)
        ↓
Learning State + Confidence (state_detection.md)
        ↓
Focus Score (focus_score.md)
        ↓
Recommended Action (this document)
        ↓
Final structured output → Backend (next: API contract, 2.6)
```

---

## 4. Open Points

- [ ] **Cross-section repetition (future enhancement):** if the same state repeats across multiple consecutive sections in a session, the action may need to escalate faster (e.g. `SKIMMING` 3 times in a row → jump straight to `SUGGEST_BREAK` instead of waiting for score to drop). Deliberately out of scope for MVP — revisit after collecting session-level usage patterns.
- [ ] Score band boundaries (70/40, 60, 50) are initial estimates — must be validated against the test scenarios deliverable.
- [ ] Confirm with Product/Backend whether `recommendedAction` should ever be overridden by business rules unrelated to behavior (e.g. a hard cap on how many `SUGGEST_BREAK` actions per session to avoid annoying the user) — likely a Backend/Product concern layered on top of this output, not something this module should handle.

---

*This document is the direct implementation reference for the Adaptive Decision module. Any band boundary changes must be re-validated against the test scenarios deliverable.*
