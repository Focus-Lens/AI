"""
Adaptive Decision layer.
Maps (state, focusScore) to a recommended action via a lookup table.
Direct implementation of adaptive_decision.md — keep both in sync.

MVP scope: decision is based only on the CURRENT section's (state, score).
Does not consider repetition of the same state across consecutive sections
(see Open Points in adaptive_decision.md for future enhancement).
"""

DECISION_TABLE = {
    "CONTENT_DIFFICULTY": [
        (70, 100, "SLOW_PACE"),
        (40, 69, "SHOW_EXPLANATION"),
        (0, 39, "REASSESS"),
    ],
    "SKIMMING": [
        (70, 100, "INCREASE_ASSESSMENT_FREQUENCY"),
        (40, 69, "SHOW_EXPLANATION"),
        (0, 39, "REASSESS"),
    ],
    "WEAK_UNDERSTANDING": [
        (60, 100, "SHOW_EXPLANATION"),
        (0, 59, "REASSESS"),
    ],
    "DISTRACTION_DISENGAGEMENT": [
        (50, 100, "SLOW_PACE"),
        (0, 49, "SUGGEST_BREAK"),
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