"""
Learning-State Detection layer.
Combines classified features into a single state + confidence.
Direct implementation of state_detection.md — keep both in sync.

Methodology: weighted rule matching. Each state has a set of weighted
conditions; the state with the highest normalized score wins, provided
it clears the ACTIVATION_THRESHOLD. Otherwise NORMAL_FOCUSED is returned.
"""
import os

ACTIVATION_THRESHOLD = 0.4

# minimum number of MCQ observations required before any
# MCQ-driven state (SKIMMING, WEAK_UNDERSTANDING) is allowed to activate at
# all. Below this, the MCQ signal is treated as unavailable (has_mcq=False),
# exactly like a section with zero micro_challenges. Configurable because
# the "right" minimum is a product/statistics judgment call, not a fact.
MIN_MCQ_EVIDENCE = int(os.environ.get("AI2_MIN_MCQ_EVIDENCE", "3"))

# Once evidence is at/above MIN_MCQ_EVIDENCE the state DOES activate, but
# confidence in the conclusion still ramps up gradually with more evidence
# rather than jumping straight to the raw rule-match score — this is what
# stops a single (or barely-sufficient) MCQ observation from producing
# confidence = 1.0. Full confidence scaling is reached at this count.
CONFIDENCE_FULL_MCQ_EVIDENCE = MIN_MCQ_EVIDENCE * 2


def _mcq_evidence_factor(mcq_count: int) -> float:
    """0..1 scaling factor applied to confidence for MCQ-driven states,
    based on how much MCQ evidence actually backs the conclusion."""
    if mcq_count <= 0:
        return 0.0
    return min(1.0, mcq_count / CONFIDENCE_FULL_MCQ_EVIDENCE)


def _normal_evidence_factor(features: dict) -> float:
    """Scale NORMAL_FOCUSED confidence by independently observed domains.

    A neutral classification is only as reliable as the telemetry examined.
    The four domains are scrolling, interaction, app/tab focus, and MCQ
    performance. Missing values do not count as evidence.
    """
    observed_domains = (
        features.get("scroll_speed") is not None
        or features.get("scroll_pattern") is not None,
        features.get("interaction") is not None,
        features.get("disengagement") is not None
        or features.get("tab_hidden_count") is not None,
        features.get("mcq_accuracy") is not None
        or features.get("mcq_response_time") is not None,
    )
    return sum(observed_domains) / len(observed_domains)


def _skimming_support_count(features: dict) -> int:
    """Count independent positive signals supporting a SKIMMING result."""
    return sum((
        features.get("scroll_speed") == "FAST",
        features.get("mcq_accuracy") == "LOW",
        features.get("mcq_response_time") == "TOO_FAST",
    ))

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
    applicable_w = [3, 2]  #  revisit, scroll_pattern always applicable

    if features["revisit"] in ("MODERATE", "HIGH"):
        true_w.append(3)

    if features["scroll_pattern"] is not None:
        applicable_w.append(2)
        if features["scroll_pattern"] == "ERRATIC":
            true_w.append(2)

    if has_mcq:
        applicable_w.append(2)
        if features["mcq_response_time"] == "SLOW":
            true_w.append(2)

    return _score(true_w, applicable_w)


def score_skimming(features: dict, has_mcq: bool) -> float:
    true_w = []
    applicable_w = []

    if features["scroll_speed"] is not None:
        applicable_w.append(2)
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
    applicable_w = [3, 2, 1, 2]  # mcq_accuracy, revisit, progression, mcq_response_time

    if features["revisit"] in ("NONE", "LOW"):
        true_w.append(2)
    if features["progression"] == "COMPLETE":
        true_w.append(1)
    if features["mcq_response_time"] == "NORMAL":
        true_w.append(2)

    return _score(true_w, applicable_w)


def _has_strong_disengagement(features: dict) -> bool:
    """Gate for DISTRACTION_DISENGAGEMENT (P2). Uses the explicit flag computed
    in feature_extraction.has_strong_disengagement_signal. If the flag is
    absent (hand-built feature dicts), falls back to the classified
    disengagement category, which implies background_count > 0."""
    if "strong_disengagement" in features:
        return bool(features["strong_disengagement"])
    return features.get("disengagement") in ("MILD_DISTRACTION", "SIGNIFICANT_DISTRACTION")


def score_disengagement(features: dict) -> float:
    # GATE (P2): weak signals alone (INCOMPLETE progression + NONE/LOW
    # interaction) must NOT activate this state. Weights below are unchanged.
    if not _has_strong_disengagement(features):
        return 0.0

    # Not MCQ-dependent, but disengagement and interaction can be
    # None (missing telemetry) — excluded from the denominator
    # rather than counted as zero. progression is a required field, never
    # None, so it stays always-applicable.
    applicable_w = []
    true_w = []

    if features["disengagement"] is not None:
        applicable_w.append(4)
        if features["disengagement"] == "SIGNIFICANT_DISTRACTION":
            true_w.append(4)
        elif features["disengagement"] == "MILD_DISTRACTION":
            true_w.append(2)

    if features["interaction"] is not None:
        applicable_w.append(2)
        if features["interaction"] in ("NONE", "LOW"):
            true_w.append(2)

    applicable_w.append(2)  # progression always applicable
    if features["progression"] == "INCOMPLETE":
        true_w.append(2)

    return _score(true_w, applicable_w)



def detect_state(features: dict) -> dict:
    """
    Main entry point. Takes a classified feature vector (from feature_extraction.py)
    and returns {"state": ..., "confidence": ..., "rule_match_score": ...}.

    `confidence` and `rule_match_score` are deliberately different numbers
    rule_match_score is the raw weighted-condition score that
    picked the winning state (used for activation/tie-breaking, exactly as
    before); confidence is what's reported downstream and scales the state
    penalty in focus_score.py — for MCQ-driven states it is additionally
    discounted when the MCQ evidence behind it is thin, so e.g. a single
    wrong answer can no longer produce confidence = 1.0.
    """
    mcq_count = features.get("mcq_count") or 0
    has_mcq = mcq_count >= MIN_MCQ_EVIDENCE

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
    rule_match_score = round(best_score, 2)

    if best_score >= ACTIVATION_THRESHOLD:
        confidence = rule_match_score
        if best_state in ("SKIMMING", "WEAK_UNDERSTANDING") and has_mcq:
            confidence = round(rule_match_score * _mcq_evidence_factor(mcq_count), 2)
        if best_state == "SKIMMING" and _skimming_support_count(features) <= 1:
            confidence = min(confidence, 0.6)
        return {"state": best_state, "confidence": confidence, "rule_match_score": rule_match_score}
    else:
        # A low concern score is not proof of focus when the underlying
        # behavioral telemetry is absent. At most one observed domain gives
        # confidence <= 0.25; two domains cap it at 0.5.
        confidence = (1 - best_score) * _normal_evidence_factor(features)
        return {
            "state": "NORMAL_FOCUSED",
            "confidence": round(confidence, 2),
            "rule_match_score": rule_match_score,
        }
