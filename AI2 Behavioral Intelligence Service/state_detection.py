"""
Learning-State Detection layer.
Combines classified features into a single state + confidence.
Direct implementation of state_detection.md — keep both in sync.

Methodology: weighted rule matching. Each state has a set of weighted
conditions; the state with the highest normalized score wins, provided
it clears the ACTIVATION_THRESHOLD. Otherwise NORMAL_FOCUSED is returned.
"""

ACTIVATION_THRESHOLD = 0.4

# Explicit tie-breaking priority — see test_scenarios.md Edge Case C.
# If two states score equally, the one listed FIRST wins.
# Ordered by "severity of inaction" — disengagement is most costly to miss,
# followed by comprehension gaps, then skimming, then difficulty.
STATE_PRIORITY = [
    "DISTRACTION_DISENGAGEMENT",
    "WEAK_UNDERSTANDING",
    "SKIMMING",
    "CONTENT_DIFFICULTY",
]


def _score(true_weights: list[int], applicable_weights: list[int]) -> float:
    """Generic weighted-scoring helper. Returns 0.0 if nothing is applicable."""
    max_score = sum(applicable_weights)
    if max_score == 0:
        return 0.0
    return sum(true_weights) / max_score


def score_content_difficulty(features: dict, has_mcq: bool) -> float:
    true_w = []
    applicable_w = [3, 3, 2]  # reading_speed, revisit, scroll_pattern always applicable

    if features["reading_speed"] == "VERY_SLOW":
        true_w.append(3)
    if features["revisit"] in ("MODERATE", "HIGH"):
        true_w.append(3)
    if features["scroll_pattern"] == "ERRATIC":
        true_w.append(2)

    if has_mcq:
        applicable_w.append(2)
        if features["mcq_response_time"] == "SLOW":
            true_w.append(2)

    return _score(true_w, applicable_w)


def score_skimming(features: dict, has_mcq: bool) -> float:
    true_w = []
    applicable_w = [3, 2]  # reading_speed, scroll_speed always applicable

    if features["reading_speed"] in ("FAST", "VERY_FAST"):
        true_w.append(3)
    if features["scroll_speed"] == "FAST":
        true_w.append(2)

    if has_mcq:
        applicable_w.extend([3, 2])
        if features["mcq_accuracy"] == "LOW":
            true_w.append(3)
        if features["mcq_response_time"] == "TOO_FAST":
            true_w.append(2)

    return _score(true_w, applicable_w)


def score_weak_understanding(features: dict, has_mcq: bool) -> float:
    # GATE: without MCQ data, or without a confirmed LOW accuracy, this state
    # cannot be meaningfully detected — comprehension can only be measured
    # via the micro-challenge. Returning 0.0 here prevents the bug where
    # otherwise-neutral signals (normal reading, no revisits, normal response
    # time) would falsely accumulate enough score to trigger this state even
    # when the learner actually answered correctly.
    if not has_mcq or features["mcq_accuracy"] != "LOW":
        return 0.0

    true_w = [3]  # mcq_accuracy == LOW is guaranteed true to reach this point
    applicable_w = [3, 2, 2, 1, 2]  # mcq_accuracy, reading_speed, revisit, progression, mcq_response_time

    if features["reading_speed"] == "NORMAL":
        true_w.append(2)
    if features["revisit"] in ("NONE", "LOW"):
        true_w.append(2)
    if features["progression"] == "COMPLETE":
        true_w.append(1)
    if features["mcq_response_time"] == "NORMAL":
        true_w.append(2)

    return _score(true_w, applicable_w)


def score_disengagement(features: dict) -> float:
    # Not MCQ-dependent — always fully applicable.
    applicable_w = [4, 2, 2, 2]
    true_w = []

    if features["disengagement"] == "SIGNIFICANT_DISTRACTION":
        true_w.append(4)
    elif features["disengagement"] == "MILD_DISTRACTION":
        true_w.append(2)
    if features["interaction"] in ("NONE", "LOW"):
        true_w.append(2)
    if features["progression"] == "INCOMPLETE":
        true_w.append(2)

    return _score(true_w, applicable_w)


def detect_state(features: dict) -> dict:
    """
    Main entry point. Takes a classified feature vector (from feature_extraction.py)
    and returns {"state": ..., "confidence": ...}.
    """
    has_mcq = features.get("mcq_accuracy") is not None

    candidates = {
        "CONTENT_DIFFICULTY": score_content_difficulty(features, has_mcq),
        "SKIMMING": score_skimming(features, has_mcq),
        "WEAK_UNDERSTANDING": score_weak_understanding(features, has_mcq),
        "DISTRACTION_DISENGAGEMENT": score_disengagement(features),
    }

    # Deterministic tie-breaking: iterate in STATE_PRIORITY order, pick first
    # state that matches the max score (handles exact ties predictably).
    best_score = max(candidates.values())
    best_state = next(s for s in STATE_PRIORITY if candidates[s] == best_score)

    if best_score >= ACTIVATION_THRESHOLD:
        return {"state": best_state, "confidence": round(best_score, 2)}
    else:
        return {"state": "NORMAL_FOCUSED", "confidence": round(1 - best_score, 2)}