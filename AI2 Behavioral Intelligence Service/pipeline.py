"""
Full pipeline: Section -> classified features -> state -> focus score -> action.
Ties together feature_extraction.py, state_detection.py, focus_score.py,
and adaptive_decision.py into the final per-section result.
Output shape matches api_contract.md.
"""

from data_models import Section, SessionPayload
from feature_extraction import extract_features
from state_detection import detect_state
from focus_score import compute_focus_score
from adaptive_decision import get_recommended_action


def analyze_section(section: Section) -> dict:
    """
    Processes ONE section through the full pipeline.
    Returns a result dict matching the `results[]` entry shape in api_contract.md.
    Raises KeyError/TypeError if required fields are missing — caller (analyze_session)
    is responsible for catching these and routing to errors[] per api_contract.md §3.
    """
    features = extract_features(section)
    state_result = detect_state(features)
    score = compute_focus_score(features, state_result["state"], state_result["confidence"])
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


def analyze_session(session: SessionPayload) -> dict:
    """
    Processes an entire session (all sections). Partial-failure tolerant:
    a bad section is reported in errors[] instead of failing the whole request
    (see api_contract.md §3.1).
    """
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