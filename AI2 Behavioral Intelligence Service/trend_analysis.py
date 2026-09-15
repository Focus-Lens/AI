"""
Trend analysis over window history (Backend-supplied).
Used to decide whether to escalate actions — e.g., repeated distraction
across windows triggers a break even if the current score looks fine.
"""


def compute_understanding_score(sections: list) -> int | None:
    # Understanding is based only on MCQ correctness.
    challenges = [
        challenge
        for section in sections
        for challenge in section.micro_challenges
    ]

    if not challenges:
        return None

    correct = sum(1 for challenge in challenges if challenge.is_correct)
    return round((correct / len(challenges)) * 100)


def compute_understanding_trend(scores: list[int | None]) -> str:
    # Ignore windows that contain no MCQ data.
    valid_scores = [score for score in scores if score is not None]
    return compute_trend(valid_scores)


def compute_trend(scores: list[int]) -> str:
    """
    Returns IMPROVING / STABLE / DECLINING based on the last few scores.
    Uses the last up-to-3 windows; delta threshold is 8 points.
    """
    if len(scores) < 2:
        return "STABLE"

    recent = scores[-3:]
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
    count = 1
    for item in reversed(history):
        if item.state == current_state:
            count += 1
        else:
            break
    return count


def consecutive_low_score_count(
    history: list, current_score: int, threshold: int = 50
) -> int:
    """Same idea, but for consecutive low focus scores."""
    if current_score >= threshold:
        return 0
    count = 1
    for item in reversed(history):
        if item.focus_score < threshold:
            count += 1
        else:
            break
    return count