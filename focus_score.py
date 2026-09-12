"""
Focus Score calculation layer.
Two-layer scoring: Base Score (from raw features) minus a State Penalty
(from the detected state, scaled by confidence).
Direct implementation of focus_score.md — keep both in sync.
"""

# ---------------------------------------------------------------------------
# Layer 1 — Base Score adjustments
# ---------------------------------------------------------------------------

ADJUSTMENTS = {
    "reading_speed": {"VERY_SLOW": -10, "NORMAL": 0, "FAST": -5, "VERY_FAST": -15},
    "scroll_pattern": {"STABLE": 0, "MODERATE": -3, "ERRATIC": -10},
    "revisit": {"NONE": 0, "LOW": -2, "MODERATE": -5, "HIGH": -10},
    "interaction": {"NONE": -10, "LOW": -5, "NORMAL": 0, "HIGH": 5},
    "mcq_accuracy": {"LOW": -15, "MEDIUM": -5, "HIGH": 5},
    "mcq_response_time": {"TOO_FAST": -10, "NORMAL": 0, "SLOW": -5},
    "disengagement": {"FOCUSED": 0, "MILD_DISTRACTION": -8, "SIGNIFICANT_DISTRACTION": -20},
    "progression": {"INCOMPLETE": -10, "PARTIAL": -3, "COMPLETE": 5},
}


def base_score(features: dict) -> float:
    score = 100
    score += ADJUSTMENTS["reading_speed"][features["reading_speed"]]
    score += ADJUSTMENTS["scroll_pattern"][features["scroll_pattern"]]
    score += ADJUSTMENTS["revisit"][features["revisit"]]
    score += ADJUSTMENTS["interaction"][features["interaction"]]
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