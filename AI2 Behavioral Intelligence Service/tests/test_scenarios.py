"""
Automated regression tests, translated from test_scenarios.md.

NOTE: while writing these, two hand-calculation mistakes were found in
test_scenarios.md Scenario 1 (scroll_pattern and interaction rate math).
The code below follows feature_thresholds.md exactly (the source of truth);
test_scenarios.md should be corrected to match — see conversation notes.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_models import Section, SessionPayload, parse_session_payload
from pipeline import analyze_section, analyze_session


def make_section(**overrides) -> Section:
    """Helper to create a Section instance matching the strict data_models contract."""
    defaults = {
        "section_id": "S_TEST",
        "concept_id": "C_TEST",
        "section_start_time": 1700000000000,
        "section_end_time": 1700000060000,
        "reading_speed_wpm": 200,
        "time_spent_seconds": 60,
        "scroll_speed_avg_px_per_sec": 200,
        "scroll_direction_changes": 1,
        "content_progression_pct": 100,
        "section_revisit_count": 0,
        "interaction_count": 2,
        "background_count": 0,
        "total_background_seconds": 0,
        "micro_challenges": [],
        "tab_hidden_count": 0,
    }
    defaults.update(overrides)
    
    return Section.from_dict(defaults)


# ---------------------------------------------------------------------------
# Scenario 1 — CONTENT_DIFFICULTY
# ---------------------------------------------------------------------------

def test_scenario_1_content_difficulty():
    section = make_section(
        reading_speed_wpm=70,
        time_spent_seconds=120,
        scroll_direction_changes=8,
        content_progression_pct=95,
        section_revisit_count=3,
        interaction_count=3,
        micro_challenges=[{"question_id": "Q1", "response_time_seconds": 25, "is_correct": True}],
    )
    result = analyze_section(section)

    assert result["state"] == "CONTENT_DIFFICULTY"
    assert result["features_used"]["reading_speed"] == "VERY_SLOW"
    assert result["features_used"]["revisit"] == "MODERATE"
    assert result["recommendedAction"] in ("SHOW_EXPLANATION", "SLOW_PACE", "REASSESS")


# ---------------------------------------------------------------------------
# Scenario 2 — SKIMMING
# ---------------------------------------------------------------------------

def test_scenario_2_skimming():
    section = make_section(
        reading_speed_wpm=450,
        time_spent_seconds=20,
        scroll_speed_avg_px_per_sec=500,
        scroll_direction_changes=0,
        content_progression_pct=100,
        section_revisit_count=0,
        interaction_count=0,
        micro_challenges=[{"question_id": "Q1", "response_time_seconds": 2, "is_correct": False}],
    )
    result = analyze_section(section)

    assert result["state"] == "SKIMMING"
    assert result["features_used"]["reading_speed"] == "VERY_FAST"
    assert result["features_used"]["mcq_accuracy"] == "LOW"


# ---------------------------------------------------------------------------
# Scenario 3 — WEAK_UNDERSTANDING
# ---------------------------------------------------------------------------

def test_scenario_3_weak_understanding():
    section = make_section(
        reading_speed_wpm=180,
        time_spent_seconds=90,
        scroll_direction_changes=1,
        content_progression_pct=100,
        section_revisit_count=0,
        interaction_count=2,
        micro_challenges=[{"question_id": "Q1", "response_time_seconds": 10, "is_correct": False}],
    )
    result = analyze_section(section)

    assert result["state"] == "WEAK_UNDERSTANDING"
    assert result["confidence"] == 1.0
    assert result["recommendedAction"] == "SHOW_EXPLANATION"


# ---------------------------------------------------------------------------
# Scenario 4 — DISTRACTION_DISENGAGEMENT (boundary test)
# ---------------------------------------------------------------------------

def test_scenario_4_distraction():
    section = make_section(
        reading_speed_wpm=150,
        time_spent_seconds=180,
        scroll_direction_changes=1,
        content_progression_pct=30,
        section_revisit_count=0,
        interaction_count=0,
        micro_challenges=[],
        background_count=4,
        total_background_seconds=60,
    )
    result = analyze_section(section)

    assert result["state"] == "DISTRACTION_DISENGAGEMENT"
    assert result["mcq_data_available"] is False
    # confirms the boundary logic in adaptive_decision.md near the 50-point split
    assert result["recommendedAction"] in ("SLOW_PACE", "SUGGEST_BREAK")


# ---------------------------------------------------------------------------
# Scenario 5 — NORMAL_FOCUSED (default fallback)
# ---------------------------------------------------------------------------

def test_scenario_5_normal_focused():
    section = make_section(
        reading_speed_wpm=200,
        time_spent_seconds=100,
        scroll_direction_changes=1,
        content_progression_pct=100,
        section_revisit_count=0,
        interaction_count=3,
        micro_challenges=[{"question_id": "Q1", "response_time_seconds": 8, "is_correct": True}],
    )
    result = analyze_section(section)

    assert result["state"] == "NORMAL_FOCUSED"
    assert result["recommendedAction"] == "CONTINUE"
    assert result["focusScore"] == 100


# ---------------------------------------------------------------------------
# Edge Case A — No Micro-Challenges
# ---------------------------------------------------------------------------

def test_edge_case_a_no_mcq_does_not_crash():
    section = make_section(
        reading_speed_wpm=70,
        time_spent_seconds=120,
        scroll_direction_changes=8,
        section_revisit_count=3,
        micro_challenges=[],  # explicitly empty
    )
    result = analyze_section(section)  # should not raise

    assert result["mcq_data_available"] is False
    assert result["features_used"]["mcq_accuracy"] is None
    assert result["features_used"]["mcq_response_time"] is None
    assert isinstance(result["focusScore"], int)


# ---------------------------------------------------------------------------
# Edge Case B — Zero Time Spent (division-by-zero risk)
# ---------------------------------------------------------------------------

def test_edge_case_b_zero_time_spent_does_not_crash():
    section = make_section(
        time_spent_seconds=0,
        interaction_count=0,
        scroll_direction_changes=0,
    )
    result = analyze_section(section)  # should not raise ZeroDivisionError

    assert result["features_used"]["scroll_pattern"] == "STABLE"
    assert result["features_used"]["interaction"] == "NONE"

# ---------------------------------------------------------------------------
# Edge Case D — Malformed section (missing required field) in a full session
# ---------------------------------------------------------------------------

def test_edge_case_d_partial_failure_isolated():
    session_data = {
        "user_id": "usr_1",
        "session_id": "sess_1",
        "session_start": 1700000000000,
        "session_end": 1700000060000,
        "sections": [
            {
                "section_id": "S_GOOD",
                "concept_id": "C1",
                "section_start_time": 1700000000000,
                "section_end_time": 1700000060000,
                "time_spent_seconds": 60,
                "reading_speed_wpm": 200,
                "scroll_speed_avg_px_per_sec": 200,
                "scroll_direction_changes": 1,
                "content_progression_pct": 100,
                "section_revisit_count": 0,
                "interaction_count": 2,
                "background_count": 0,
                "total_background_seconds": 0,
            },
        ],
    }
    
    session = SessionPayload.from_dict(session_data)
    
    # محاكاة تلف بيانات قسم بإلغاء حقل إجباري منه
    del session.sections[0].__dict__["reading_speed_wpm"]

    response = analyze_session(session)

    assert response["results"] == []
    assert "errors" in response
    assert response["errors"][0]["section_id"] == "S_GOOD"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])