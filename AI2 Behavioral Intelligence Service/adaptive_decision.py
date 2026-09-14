"""
Adaptive Decision layer.
Maps (state, focusScore) to a recommended action via a lookup table,
then applies history-aware escalation rules on top.

MVP scope: decision is based on the CURRENT window's (state, score)
plus optional history signals (consecutive state, trend).
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


def _lookup_base_action(state: str, focus_score: int) -> str:
    for low, high, action in DECISION_TABLE[state]:
        if low <= focus_score <= high:
            return action
    return "CONTINUE"


def get_recommended_action(
    state: str,
    focus_score: int,
    consecutive_same_state: int = 1,
    consecutive_low_score: int = 0,
    trend: str = "STABLE",
) -> str:
    """
    Base action from lookup table, then escalation rules:
      - Repeated DISTRACTION_DISENGAGEMENT across windows -> break.
      - Sustained low score (2+ windows below 50) -> break.
      - DECLINING trend on a non-normal state -> upgrade support.
    """
    base_action = _lookup_base_action(state, focus_score)

    if state == "DISTRACTION_DISENGAGEMENT" and consecutive_same_state >= 2:
        return "SUGGEST_BREAK"

    if consecutive_low_score >= 2:
        return "SUGGEST_BREAK"

    if trend == "DECLINING" and state != "NORMAL_FOCUSED":
        if base_action in ("CONTINUE", "SLOW_PACE"):
            return "SHOW_EXPLANATION"

    return base_action