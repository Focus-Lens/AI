"""
Trend analysis over window history (Backend-supplied).
Used to decide whether to escalate actions — e.g., repeated distraction
across windows triggers a break even if the current score looks fine.
"""

from typing import List, Optional


def compute_understanding_score(sections: list) -> Optional[int]:
    """
    Understanding is based only on MCQ correctness.
    Returns None if no MCQs are present in the provided sections.
    """
    challenges = [
        challenge
        for section in sections
        for challenge in getattr(section, "micro_challenges", [])
    ]

    if not challenges:
        return None

    correct = sum(1 for challenge in challenges if getattr(challenge, "is_correct", False))
    return round((correct / len(challenges)) * 100)


def compute_understanding_trend(scores: List[Optional[int]]) -> str:
    """Ignore windows that contain no MCQ data (None) and calculate trend."""
    valid_scores = [score for score in scores if score is not None]
    return compute_trend(valid_scores)


def compute_trend(scores: List[int]) -> str:
    """
    Returns IMPROVING / STABLE / DECLINING based on the last few scores.
    Uses the last up-to-3 windows; delta threshold is 8 points.
    Filters out any None values if passed accidentally.
    """
    valid_scores = [s for s in scores if s is not None]

    if len(valid_scores) < 2:
        return "STABLE"

    recent = valid_scores[-3:]
    delta = recent[-1] - recent[0]

    if delta >= 8:
        return "IMPROVING"
    elif delta <= -8:
        return "DECLINING"
    return "STABLE"


def consecutive_state_count(history: list, current_state: str) -> int:
    """
    How many windows in a row (including current) shared the same state?
    Walks history backwards while states match.
    """
    if not current_state:
        return 0

    count = 1
    for item in reversed(history):
        item_state = getattr(item, "state", None) or (item.get("state") if isinstance(item, dict) else None)
        if item_state == current_state:
            count += 1
        else:
            break
    return count


def consecutive_low_score_count(
    history: list, current_score: Optional[int], threshold: int = 50
) -> int:
    """
    Calculates consecutive low focus scores below threshold.
    Safely skips windows where focus_score is None (missing telemetry/empty window).
    """
    if current_score is None or current_score >= threshold:
        return 0

    count = 1
    for item in reversed(history):
        # Support both Pydantic models (attr) and dictionaries
        score = getattr(item, "focus_score", None) if not isinstance(item, dict) else item.get("focus_score")
        
        # Skip empty windows / null scores in history without breaking the streak
        if score is None:
            continue

        if score < threshold:
            count += 1
        else:
            break

    return count