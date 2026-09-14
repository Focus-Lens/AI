"""
feature_extraction.py

Converts raw numeric signals (from a Section) into categorical classifications.
Direct implementation of `feature_thresholds.md`. Every function here is PURE:
same input always gives same output, no side effects, no external calls.
This is what makes the system explainable and reproducible.

Content is assumed English-only (per project decision) — no language branching.
"""

from data_models import Section


# ---------------------------------------------------------------------------
# 1. Reading speed (English-only content — see feature_thresholds.md §1)
# ---------------------------------------------------------------------------
# def classify_reading_speed(wpm: float) -> str:                                        # DELETED!
#     if wpm < 100:
#         return "VERY_SLOW"
#     elif wpm <= 250:
#         return "NORMAL"
#     elif wpm <= 400:
#         return "FAST"
#     else:
#         return "VERY_FAST"


# ---------------------------------------------------------------------------
# 2. Scroll speed (placeholder — pending px/dp unit confirmation with Frontend)
# ---------------------------------------------------------------------------
def classify_scroll_speed(px_per_sec: float) -> str:
    if px_per_sec < 100:
        return "SLOW"
    elif px_per_sec <= 400:
        return "NORMAL"
    else:
        return "FAST"


# ---------------------------------------------------------------------------
# 3. Scroll pattern (rate-normalized by time)
# ---------------------------------------------------------------------------
def classify_scroll_pattern(direction_changes: int, time_spent_seconds: float) -> str:
    if time_spent_seconds <= 0:
        # Edge Case B (test_scenarios.md): no time spent -> default to the
        # calmest/zero state rather than dividing by zero.
        return "STABLE"

    rate_per_minute = direction_changes / (time_spent_seconds / 60)

    if rate_per_minute <= 2:
        return "STABLE"
    elif rate_per_minute <= 6:
        return "MODERATE"
    else:
        return "ERRATIC"


# ---------------------------------------------------------------------------
# 4. Content progression
# ---------------------------------------------------------------------------
def classify_progression(progression_pct: float) -> str:
    if progression_pct < 50:
        return "INCOMPLETE"
    elif progression_pct <= 90:
        return "PARTIAL"
    else:
        return "COMPLETE"


# ---------------------------------------------------------------------------
# 5. Section revisit
# ---------------------------------------------------------------------------
def classify_revisit(revisit_count: int) -> str:
    if revisit_count == 0:
        return "NONE"
    elif revisit_count == 1:
        return "LOW"
    elif revisit_count <= 3:
        return "MODERATE"
    else:
        return "HIGH"


# ---------------------------------------------------------------------------
# 6. Interaction rate (rate-normalized by time)
# ---------------------------------------------------------------------------
def classify_interaction(interaction_count: int, time_spent_seconds: float) -> str:
    if interaction_count == 0 or time_spent_seconds <= 0:
        # Edge Case B: zero count or zero duration -> zero-state
        return "NONE"

    rate_per_minute = interaction_count / (time_spent_seconds / 60)

    if rate_per_minute <= 1:
        return "LOW"
    elif rate_per_minute <= 3:
        return "NORMAL"
    else:
        return "HIGH"


# ---------------------------------------------------------------------------
# 7. Micro-challenge accuracy (across all challenges in the section)
# ---------------------------------------------------------------------------
def classify_mcq_accuracy(correct_count: int, total_count: int) -> str | None:
    """Safe for direct call: Returns None when total_count is 0 to signal 'not applicable'."""
    if total_count <= 0:
        return None

    accuracy = correct_count / total_count
    if accuracy < 0.4:
        return "LOW"
    elif accuracy <= 0.7:
        return "MEDIUM"
    else:
        return "HIGH"


# ---------------------------------------------------------------------------
# 8. Micro-challenge response time (average across challenges in the section)
# ---------------------------------------------------------------------------
def classify_response_time(avg_response_time_seconds: float | None) -> str | None:
    """Safe for direct call: Handles None input seamlessly when no MCQs exist."""
    if avg_response_time_seconds is None:
        return None

    if avg_response_time_seconds < 3:
        return "TOO_FAST"
    elif avg_response_time_seconds <= 20:
        return "NORMAL"
    else:
        return "SLOW"


# ---------------------------------------------------------------------------
# 9. Disengagement / background behavior
# ---------------------------------------------------------------------------
def classify_disengagement(background_count: int, total_background_seconds: float) -> str:
    if background_count == 0:
        return "FOCUSED"
    elif background_count <= 2 and total_background_seconds < 30:
        return "MILD_DISTRACTION"
    else:
        return "SIGNIFICANT_DISTRACTION"


# ---------------------------------------------------------------------------
# Top-level: build the full feature vector for one Section
# ---------------------------------------------------------------------------
def extract_features(section: Section) -> dict[str, str | None]:
    """
    Runs every classify_* function against a Section and returns the
    combined feature vector, matching the shape in feature_thresholds.md §10.

    MCQ-dependent features (mcq_accuracy, mcq_response_time) are set to None
    when the section has no micro_challenges — this is NOT the same as a
    "bad" classification, it means "not applicable". Downstream layers
    (state_detection.py, focus_score.py) must check for None and exclude
    these from their calculations rather than treating None as a category.
    """
    total_mcq = len(section.micro_challenges)
    correct_mcq = sum(1 for c in section.micro_challenges if c.is_correct)
    avg_response_time = (
        sum(c.response_time_seconds for c in section.micro_challenges) / total_mcq
        if total_mcq > 0
        else None
    )

    return {
        # "reading_speed": classify_reading_speed(section.reading_speed_wpm),            # DELETED!
        "scroll_speed": classify_scroll_speed(section.scroll_speed_avg_px_per_sec),
        "scroll_pattern": classify_scroll_pattern(
            section.scroll_direction_changes, section.time_spent_seconds
        ),
        "progression": classify_progression(section.content_progression_pct),
        "revisit": classify_revisit(section.section_revisit_count),
        "interaction": classify_interaction(
            section.interaction_count, section.time_spent_seconds
        ),
        "mcq_accuracy": classify_mcq_accuracy(correct_mcq, total_mcq),
        "mcq_response_time": classify_response_time(avg_response_time),
        "disengagement": classify_disengagement(
            section.background_count, section.total_background_seconds
        ),
    }