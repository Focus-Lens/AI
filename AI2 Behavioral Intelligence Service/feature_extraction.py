"""
feature_extraction.py

Converts raw numeric signals (from a Section) into categorical classifications.
Direct implementation of `feature_thresholds.md`. Every function here is PURE:
same input always gives same output, no side effects, no external calls.
This is what makes the system explainable and reproducible.

Content is assumed English-only (per project decision) — no language branching.
"""

import os
import state_detection  # MIN_MCQ_EVIDENCE is read at call time
from data_models import Section, MicroChallenge, effective_time_seconds

# ---------------------------------------------------------------------------
# MCQ accuracy metric selection (configurable, product decision pending).
# Default preserves pre-existing behaviour.
# ---------------------------------------------------------------------------
MCQ_METRIC = os.environ.get("AI2_MCQ_METRIC", "attempt_accuracy")
_VALID_MCQ_METRICS = {"attempt_accuracy", "first_attempt_accuracy", "final_answer_accuracy"}

# ---------------------------------------------------------------------------
# P2: strong-disengagement gate (product decisions — configurable).
# DISTRACTION_DISENGAGEMENT may only activate if at least ONE strong signal
# exists (see has_strong_disengagement_signal).
# ---------------------------------------------------------------------------
DISTRACTION_MIN_BACKGROUND_SECONDS = float(
    os.environ.get("AI2_DISTRACTION_MIN_BACKGROUND_SECONDS", "5")
)
DISTRACTION_MIN_INACTIVE_SECONDS = float(
    os.environ.get("AI2_DISTRACTION_MIN_INACTIVE_SECONDS", "60")
)


# ---------------------------------------------------------------------------
# 2. Scroll speed (placeholder — pending px/dp unit confirmation with Frontend)
# ---------------------------------------------------------------------------
def classify_scroll_speed(px_per_sec: float | None) -> str | None:
    if px_per_sec is None:
        return None  # telemetry not reported
    if px_per_sec < 100:
        return "SLOW"
    elif px_per_sec <= 400:
        return "NORMAL"
    else:
        return "FAST"


# ---------------------------------------------------------------------------
# 3. Scroll pattern (rate-normalized by time)
# ---------------------------------------------------------------------------
def classify_scroll_pattern(direction_changes: int | None, time_spent_seconds: float) -> str | None:
    if direction_changes is None:
        return None  # telemetry not reported
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
def classify_interaction(interaction_count: int | None, time_spent_seconds: float) -> str | None:
    """`time_spent_seconds` here must be the EFFECTIVE time
    (data_models.effective_time_seconds), not the raw first-to-last-event time."""
    if interaction_count is None:
        return None  # telemetry not reported
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
def classify_disengagement(background_count: int | None, total_background_seconds: float | None) -> str | None:
    """Returns None (unknown) when either half of this signal pair is
    missing — a partial reading (e.g. count but no duration) is not enough
    to classify disengagement severity."""
    if background_count is None or total_background_seconds is None:
        return None

    if background_count == 0:
        return "FOCUSED"
    elif background_count <= 2 and total_background_seconds < 30:
        return "MILD_DISTRACTION"
    else:
        return "SIGNIFICANT_DISTRACTION"


# ---------------------------------------------------------------------------
# 9b. P2: strong disengagement signal (gate for DISTRACTION_DISENGAGEMENT)
# ---------------------------------------------------------------------------
def has_strong_disengagement_signal(section: Section) -> bool:
    """
    True if at least one STRONG disengagement signal is present:
      - background_count > 0
      - total_background_seconds > DISTRACTION_MIN_BACKGROUND_SECONDS
      - prolonged inactivity: interaction_count == 0 AND effective time
        > DISTRACTION_MIN_INACTIVE_SECONDS

    None (unreported) telemetry never counts. Weak signals alone
    (INCOMPLETE progression, NONE interaction on a short section) are NOT
    enough.
    """
    if section.background_count is not None and section.background_count > 0:
        return True
    if (
        section.total_background_seconds is not None
        and section.total_background_seconds > DISTRACTION_MIN_BACKGROUND_SECONDS
    ):
        return True
    if (
        section.interaction_count is not None
        and section.interaction_count == 0
        and effective_time_seconds(section) > DISTRACTION_MIN_INACTIVE_SECONDS
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# 10. MCQ accuracy reduction — metric is configurable
# ---------------------------------------------------------------------------
def compute_mcq_accuracy_counts(
    micro_challenges: list[MicroChallenge], metric: str | None = None
) -> tuple[int, int]:
    """
    Reduces a section's raw micro-challenge attempts into (correct_count,
    total_count) to be fed into classify_mcq_accuracy(). The reduction
    strategy is controlled by `metric` (defaults to the module-level
    MCQ_METRIC, i.e. the AI2_MCQ_METRIC env var):

      - "attempt_accuracy" (default, preserves original behaviour):
        every recorded attempt counts individually. correct_count = number
        of attempts with is_correct=True; total_count = number of attempts.
        A student who retries the same question 3 times contributes 3
        data points, so a late correct answer does not erase earlier wrong
        ones from the signal.

      - "first_attempt_accuracy": only the FIRST recorded attempt per
        distinct question_id counts; retries are ignored. Measures raw,
        unaided understanding at first exposure. Assumes `micro_challenges`
        is given in chronological attempt order (the Frontend must send it
        that way for this metric to be meaningful — there is no timestamp
        field on MicroChallenge to verify this independently).

      - "final_answer_accuracy": only the LAST recorded attempt per
        distinct question_id counts. Measures the student's end state per
        question after any retries ("did they eventually get it").

    NOTE: none of these three is identical to the Backend Reports page's
    definition ("distinct questions with at least one correct answer,
    ever"), which is closer to "best-of" than "first" or "final". That
    mismatch is a product decision, not something this function resolves
    silently.
    """
    if metric is None:
        metric = MCQ_METRIC
    if metric not in _VALID_MCQ_METRICS:
        raise ValueError(f"Unknown MCQ_METRIC: {metric!r}; expected one of {_VALID_MCQ_METRICS}")

    if not micro_challenges:
        return 0, 0

    if metric == "attempt_accuracy":
        total = len(micro_challenges)
        correct = sum(1 for c in micro_challenges if c.is_correct)
        return correct, total

    # "first_attempt_accuracy" / "final_answer_accuracy": one attempt per
    # distinct question_id, preserving first-seen order of questions.
    by_question: dict[str, list[MicroChallenge]] = {}
    for c in micro_challenges:
        by_question.setdefault(c.question_id, []).append(c)

    if metric == "first_attempt_accuracy":
        chosen = [attempts[0] for attempts in by_question.values()]
    else:  # final_answer_accuracy
        chosen = [attempts[-1] for attempts in by_question.values()]

    total = len(chosen)
    correct = sum(1 for c in chosen if c.is_correct)
    return correct, total


# ---------------------------------------------------------------------------
# Top-level: build the full feature vector for one Section
# ---------------------------------------------------------------------------
def extract_features(section: Section, mcq_metric: str | None = None) -> dict[str, object]:
    """
    Runs every classify_* function against a Section and returns the
    combined feature vector, matching the shape in feature_thresholds.md §10.

    MCQ-dependent features (mcq_accuracy, mcq_response_time) are set to None
    when the section has no micro_challenges — this is NOT the same as a
    "bad" classification, it means "not applicable". Non-MCQ behavioral
    features (scroll_speed, scroll_pattern, interaction, disengagement) can
    ALSO be None, when the corresponding telemetry was not reported at
    all by the Frontend (as opposed to a reported value of 0). Downstream
    layers (state_detection.py, focus_score.py) must check for None and
    exclude these from their calculations rather than treating None as a
    category or as zero.

    `mcq_metric` overrides MCQ_METRIC for this call only (mainly for tests);
    production code should rely on the AI2_MCQ_METRIC env var instead.

    The returned "mcq_count" is the number of MCQ observations that fed
    mcq_accuracy under the active metric (after any first/final dedup) —
    state_detection.py uses it as the evidence count for MIN_MCQ_EVIDENCE.

    P2 additions (additive keys): "effective_time_seconds" and
    "strong_disengagement" (gate for DISTRACTION_DISENGAGEMENT).
    """
    correct_mcq, total_mcq = compute_mcq_accuracy_counts(section.micro_challenges, metric=mcq_metric)
    avg_response_time = (
        sum(c.response_time_seconds for c in section.micro_challenges) / len(section.micro_challenges)
        if section.micro_challenges
        else None
    )
    eff_time = effective_time_seconds(section)
    # P1: below MIN_MCQ_EVIDENCE observations the MCQ signal is UNAVAILABLE
    # (None) for everything downstream (state detection AND focus score),
    # not only for state activation. "mcq_count" still reports how many
    # observations existed.
    mcq_enough = total_mcq >= state_detection.MIN_MCQ_EVIDENCE

    return {
        "scroll_speed": classify_scroll_speed(section.scroll_speed_avg_px_per_sec),
        # scroll_pattern still uses raw time_spent_seconds (out of P2 scope)
        "scroll_pattern": classify_scroll_pattern(
            section.scroll_direction_changes, section.time_spent_seconds
        ),
        "progression": classify_progression(section.content_progression_pct),
        "revisit": classify_revisit(section.section_revisit_count),
        "interaction": classify_interaction(section.interaction_count, eff_time),
        "mcq_accuracy": classify_mcq_accuracy(correct_mcq, total_mcq) if mcq_enough else None,
        "mcq_response_time": classify_response_time(avg_response_time) if mcq_enough else None,
        "mcq_count": total_mcq,
        "disengagement": classify_disengagement(
            section.background_count, section.total_background_seconds
        ),
        "effective_time_seconds": eff_time,
        "strong_disengagement": has_strong_disengagement_signal(section),
    }