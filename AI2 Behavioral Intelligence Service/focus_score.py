"""
Focus Score calculation layer.
Two-layer scoring: Base Score (from raw features) minus a State Penalty
(from the detected state, scaled by confidence).
Direct implementation of focus_score.md — keep both in sync.
"""

from data_models import effective_time_seconds

# ---------------------------------------------------------------------------
# Layer 1 — Base Score adjustments
# ---------------------------------------------------------------------------

ADJUSTMENTS = {
    "scroll_pattern": {"STABLE": 0, "MODERATE": -5, "ERRATIC": -15},
    "revisit": {"NONE": 0, "LOW": -3, "MODERATE": -8, "HIGH": -15},
    "interaction": {"NONE": -15, "LOW": -8, "NORMAL": 0, "HIGH": 5},
    "mcq_accuracy": {"LOW": -20, "MEDIUM": -8, "HIGH": 5},
    "mcq_response_time": {"TOO_FAST": -12, "NORMAL": 0, "SLOW": -5},
    "disengagement": {"FOCUSED": 0, "MILD_DISTRACTION": -10, "SIGNIFICANT_DISTRACTION": -25},
    "progression": {"INCOMPLETE": -15, "PARTIAL": -5, "COMPLETE": 5},
}


def base_score(features: dict) -> float:
    # scroll_pattern / interaction / disengagement can be None
    # (missing telemetry, not a reported zero) — skip the adjustment
    # entirely rather than crashing on ADJUSTMENTS[...][None] or silently
    # treating missing data as the "best"/"worst" category. revisit and
    # progression remain required fields and are never None.
    score = 100
    if features.get("scroll_pattern") is not None:
        score += ADJUSTMENTS["scroll_pattern"][features["scroll_pattern"]]
    score += ADJUSTMENTS["revisit"][features["revisit"]]
    if features.get("interaction") is not None:
        score += ADJUSTMENTS["interaction"][features["interaction"]]
    if features.get("disengagement") is not None:
        score += ADJUSTMENTS["disengagement"][features["disengagement"]]
    score += ADJUSTMENTS["progression"][features["progression"]]

    if features.get("mcq_accuracy") is not None:
        score += ADJUSTMENTS["mcq_accuracy"][features["mcq_accuracy"]]
        score += ADJUSTMENTS["mcq_response_time"][features["mcq_response_time"]]

    return max(0, min(100, score))


# ---------------------------------------------------------------------------
# Layer 2 — State Penalty
# ---------------------------------------------------------------------------

MAX_PENALTY = {
    "CONTENT_DIFFICULTY": 10,
    "SKIMMING": 15,
    "WEAK_UNDERSTANDING": 15,
    "DISTRACTION_DISENGAGEMENT": 20,
    "NORMAL_FOCUSED": 0,
}


def state_penalty(state: str, confidence: float) -> float:
    return MAX_PENALTY[state] * confidence


# ---------------------------------------------------------------------------
# Final computation
# ---------------------------------------------------------------------------

def compute_focus_score(features: dict, state: str, confidence: float) -> int:
    b_score = base_score(features)
    penalty = state_penalty(state, confidence)
    final = max(0, min(100, b_score - penalty))
    return round(final)


# ---------------------------------------------------------------------------
# Window-level aggregation (duration-weighted)
# ---------------------------------------------------------------------------

def weighted_window_score(section_results: list[dict], sections: list) -> int:
    """
    Window-level focus score = duration-weighted mean of per-section scores.

    Weight = effective_time_seconds(section) (see data_models): active time if
    provided, else time minus background time, else raw time. Long inactive
    gaps therefore do not inflate a section's weight.
    Fallback: if total weight is 0 (student opened and closed instantly),
    fall back to simple mean to avoid dividing by zero.

    section_results and sections MUST be aligned by index.
    """
    if not section_results:
        return 0

    weights = [effective_time_seconds(s) for s in sections]
    total_time = sum(weights)

    if total_time <= 0:
        return round(sum(r["focusScore"] for r in section_results) / len(section_results))

    weighted_sum = sum(r["focusScore"] * w for r, w in zip(section_results, weights))
    return round(weighted_sum / total_time)