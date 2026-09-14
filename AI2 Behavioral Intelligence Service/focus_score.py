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
    # "reading_speed": {"VERY_SLOW": -10, "NORMAL": 0, "FAST": -5, "VERY_FAST": -15},                # DELETED!       
    "scroll_pattern": {"STABLE": 0, "MODERATE": -5, "ERRATIC": -15},  # زياد بسيط في الخصم للتعويض
    "revisit": {"NONE": 0, "LOW": -3, "MODERATE": -8, "HIGH": -15},
    "interaction": {"NONE": -15, "LOW": -8, "NORMAL": 0, "HIGH": 5},
    "mcq_accuracy": {"LOW": -20, "MEDIUM": -8, "HIGH": 5},
    "mcq_response_time": {"TOO_FAST": -12, "NORMAL": 0, "SLOW": -5},
    "disengagement": {"FOCUSED": 0, "MILD_DISTRACTION": -10, "SIGNIFICANT_DISTRACTION": -25},
    "progression": {"INCOMPLETE": -15, "PARTIAL": -5, "COMPLETE": 5},
}


def base_score(features: dict) -> float:
    score = 100
    # score += ADJUSTMENTS["reading_speed"][features["reading_speed"]]                              # DELETED!
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