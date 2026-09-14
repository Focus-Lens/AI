"""
Full pipeline:
  End-of-session path: SessionPayload -> per-section results.
  Real-time path:      AnalysisWindow -> window score + debounced action.
Output shapes match api_contract.md.
"""

from data_models import Section, SessionPayload, AnalysisWindow
from feature_extraction import extract_features
from state_detection import detect_state, STATE_PRIORITY
from focus_score import compute_focus_score, weighted_window_score
from adaptive_decision import get_recommended_action
from trend_analysis import (
    compute_trend,
    consecutive_state_count,
    consecutive_low_score_count,
)
from debounce import debounce_store


# ---------------------------------------------------------------------------
# Per-section analysis (used by both paths)
# ---------------------------------------------------------------------------

def analyze_section(section: Section) -> dict:
    features = extract_features(section)
    state_result = detect_state(features)
    score = compute_focus_score(
        features, state_result["state"], state_result["confidence"]
    )
    action = get_recommended_action(state_result["state"], score)

    return {
        "section_id": section.section_id,
        "concept_id": section.concept_id,
        "state": state_result["state"],
        "confidence": state_result["confidence"],
        "focusScore": score,
        "recommendedAction": action,
        "features_used": features,
        "mcq_data_available": section.has_mcq,
    }


# ---------------------------------------------------------------------------
# End-of-session path (unchanged behaviour)
# ---------------------------------------------------------------------------

def analyze_session(session: SessionPayload) -> dict:
    results = []
    errors = []

    for section in session.sections:
        try:
            results.append(analyze_section(section))
        except (KeyError, TypeError, AttributeError) as exc:
            errors.append({
                "section_id": getattr(section, "section_id", "UNKNOWN"),
                "reason": "missing_required_field",
                "detail": str(exc),
            })

    response = {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "results": results,
    }
    if errors:
        response["errors"] = errors

    return response


# ---------------------------------------------------------------------------
# Real-time path: periodic window analysis
# ---------------------------------------------------------------------------

def analyze_window(window: AnalysisWindow) -> dict:
    """
    Called every 5 min (or earlier if session ends).
    Returns window-level score + ONE debounced recommended action.
    """
    # 1. Analyze each section; keep alignment with `sections` for weighting
    section_results = []
    aligned_sections = []
    for section in window.sections:
        try:
            result = analyze_section(section)
            section_results.append(result)
            aligned_sections.append(section)
        except (KeyError, TypeError, AttributeError):
            continue

    # 2. Edge case: empty window (student closed app immediately)
    if not section_results:
        return _empty_window_response(window)

    # 3. Duration-weighted window score
    window_score = weighted_window_score(section_results, aligned_sections)

    # 4. Dominant state (most frequent; tie-break by severity)
    state_counts: dict[str, int] = {}
    for r in section_results:
        state_counts[r["state"]] = state_counts.get(r["state"], 0) + 1
    max_count = max(state_counts.values())
    dominant_state = next(
        s for s in STATE_PRIORITY + ["NORMAL_FOCUSED"]
        if state_counts.get(s, 0) == max_count
    )

    # 5. History-aware trend + escalation
    history_scores = [h.focus_score for h in window.history]
    trend = compute_trend(history_scores + [window_score])
    consec_state = consecutive_state_count(window.history, dominant_state)
    consec_low = consecutive_low_score_count(window.history, window_score)

    raw_action = get_recommended_action(
        state=dominant_state,
        focus_score=window_score,
        consecutive_same_state=consec_state,
        consecutive_low_score=consec_low,
        trend=trend,
    )

    # 6. Debounce — only emit if it passes
    emitted = debounce_store.should_emit(window.session_id, raw_action)
    final_action = raw_action if emitted else "SUPPRESSED"

    # 7. Cleanup on final window
    if window.is_final:
        debounce_store.clear(window.session_id)

    return {
        "session_id": window.session_id,
        "window_index": window.window_index,
        "window_focus_score": window_score,
        "window_state": dominant_state,
        "recommended_action": final_action,
        "raw_action": raw_action,        # for debugging / logging
        "action_emitted": emitted,
        "trend": trend,
        "is_final": window.is_final,
        "sections_analyzed": len(section_results),
        "sections": section_results,
    }


def _empty_window_response(window: AnalysisWindow) -> dict:
    """No usable sections in this window — don't crash, don't debounce."""
    if window.is_final:
        debounce_store.clear(window.session_id)
    return {
        "session_id": window.session_id,
        "window_index": window.window_index,
        "window_focus_score": None,
        "window_state": "NORMAL_FOCUSED",
        "recommended_action": "CONTINUE",
        "raw_action": "CONTINUE",
        "action_emitted": False,
        "trend": "STABLE",
        "is_final": window.is_final,
        "sections_analyzed": 0,
        "note": "empty_window",
        "sections": [],
    }