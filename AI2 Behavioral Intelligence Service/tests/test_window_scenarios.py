"""
Regression tests for the real-time (periodic window) path.
Covers: analyze_window, weighted scoring, trend analysis, debounce,
escalation rules, and edge cases around is_final / empty windows.
"""

import sys
import os
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_models import (
    Section,
    AnalysisWindow,
    WindowHistoryItem,
)
from pipeline import analyze_window
from focus_score import weighted_window_score
from trend_analysis import (
    compute_trend,
    consecutive_state_count,
    consecutive_low_score_count,
)
from debounce import DebounceStore, debounce_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_section(**overrides) -> Section:
    defaults = {
        "section_id": "S_TEST",
        "concept_id": "C_TEST",
        "section_start_time": 1700000000000,
        "section_end_time": 1700000060000,
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


def make_window(**overrides) -> AnalysisWindow:
    defaults = {
        "user_id": "u_test",
        "session_id": "s_test",
        "window_index": 1,
        "window_start": 1700000000,
        "window_end": 1700000300,
        "is_final": False,
        "sections": [],
        "history": [],
    }
    defaults.update(overrides)
    return AnalysisWindow.from_dict(defaults)


def make_history_item(window_index: int, focus_score: int, state: str) -> WindowHistoryItem:
    return WindowHistoryItem.from_dict({
        "window_index": window_index,
        "focus_score": focus_score,
        "state": state,
        "dominant_action": "CONTINUE",
    })


@pytest.fixture(autouse=True)
def _clean_debounce():
    """Ensure the global debounce store doesn't leak between tests."""
    yield
    # Wipe all sessions after each test
    with debounce_store._lock:
        debounce_store._store.clear()


# ---------------------------------------------------------------------------
# A. weighted_window_score
# ---------------------------------------------------------------------------

def test_weighted_score_duration_dominates():
    """A long section should dominate a short one."""
    sections = [
        make_section(section_id="short", time_spent_seconds=10),
        make_section(section_id="long", time_spent_seconds=290),
    ]
    results = [
        {"focusScore": 100},  # short section: perfect score
        {"focusScore": 0},    # long section: terrible score
    ]
    score = weighted_window_score(results, sections)

    # Expected: (100*10 + 0*290) / 300 = 3.33 -> 3
    assert score == 3


def test_weighted_score_equal_weights_equals_simple_mean():
    sections = [
        make_section(section_id="a", time_spent_seconds=60),
        make_section(section_id="b", time_spent_seconds=60),
    ]
    results = [{"focusScore": 80}, {"focusScore": 60}]
    assert weighted_window_score(results, sections) == 70


def test_weighted_score_zero_total_time_falls_back_to_mean():
    """Edge case: all sections have 0 duration -> simple mean."""
    sections = [
        make_section(section_id="a", time_spent_seconds=0),
        make_section(section_id="b", time_spent_seconds=0),
    ]
    results = [{"focusScore": 80}, {"focusScore": 60}]
    assert weighted_window_score(results, sections) == 70


# ---------------------------------------------------------------------------
# B. trend_analysis
# ---------------------------------------------------------------------------

def test_compute_trend_single_score_is_stable():
    assert compute_trend([75]) == "STABLE"


def test_compute_trend_improving():
    assert compute_trend([50, 60, 70]) == "IMPROVING"


def test_compute_trend_declining():
    assert compute_trend([80, 70, 60]) == "DECLINING"


def test_compute_trend_uses_last_three_only():
    """Older scores must not affect the verdict."""
    # First two are high, last three decline
    assert compute_trend([100, 100, 80, 70, 60]) == "DECLINING"


def test_consecutive_state_count():
    history = [
        make_history_item(1, 50, "NORMAL_FOCUSED"),
        make_history_item(2, 50, "DISTRACTION_DISENGAGEMENT"),
        make_history_item(3, 50, "DISTRACTION_DISENGAGEMENT"),
    ]
    assert consecutive_state_count(history, "DISTRACTION_DISENGAGEMENT") == 3
    assert consecutive_state_count(history, "NORMAL_FOCUSED") == 1


def test_consecutive_low_score_count_below_threshold():
    history = [
        make_history_item(1, 40, "NORMAL_FOCUSED"),
        make_history_item(2, 45, "NORMAL_FOCUSED"),
    ]
    assert consecutive_low_score_count(history, 30) == 3


def test_consecutive_low_score_count_current_ok():
    history = [make_history_item(1, 30, "NORMAL_FOCUSED")]
    assert consecutive_low_score_count(history, 80) == 0


def test_compute_understanding_score_all_correct():
    from trend_analysis import compute_understanding_score

    sections = [
        make_section(micro_challenges=[
            {"question_id": "Q1", "response_time_seconds": 8, "is_correct": True},
            {"question_id": "Q2", "response_time_seconds": 9, "is_correct": True},
        ])
    ]

    assert compute_understanding_score(sections) == 100


def test_compute_understanding_score_mixed_answers():
    from trend_analysis import compute_understanding_score

    sections = [
        make_section(micro_challenges=[
            {"question_id": "Q1", "response_time_seconds": 8, "is_correct": True},
            {"question_id": "Q2", "response_time_seconds": 9, "is_correct": False},
            {"question_id": "Q3", "response_time_seconds": 10, "is_correct": False},
            {"question_id": "Q4", "response_time_seconds": 11, "is_correct": True},
        ])
    ]

    assert compute_understanding_score(sections) == 50


def test_compute_understanding_score_without_mcqs_returns_none():
    from trend_analysis import compute_understanding_score

    assert compute_understanding_score([make_section()]) is None


def test_compute_understanding_trend_ignores_missing_windows():
    from trend_analysis import compute_understanding_trend

    assert compute_understanding_trend([None, 50, 60]) == "IMPROVING"
    assert compute_understanding_trend([100, None, 80]) == "DECLINING"
    assert compute_understanding_trend([None, None]) == "STABLE"


def test_window_includes_understanding_score_and_trend():
    history = [
        make_history_item(1, 80, "NORMAL_FOCUSED"),
        make_history_item(2, 70, "NORMAL_FOCUSED"),
    ]
    history[0].understanding_score = 40
    history[1].understanding_score = 50

    window = make_window(
        window_index=3,
        history=history,
        sections=[make_section(
            micro_challenges=[
                {"question_id": "Q1", "response_time_seconds": 8, "is_correct": True},
                {"question_id": "Q2", "response_time_seconds": 9, "is_correct": True},
                {"question_id": "Q3", "response_time_seconds": 10, "is_correct": False},
                {"question_id": "Q4", "response_time_seconds": 11, "is_correct": True},
                {"question_id": "Q5", "response_time_seconds": 12, "is_correct": True},
                {"question_id": "Q6", "response_time_seconds": 13, "is_correct": True},
                {"question_id": "Q7", "response_time_seconds": 14, "is_correct": True},
                {"question_id": "Q8", "response_time_seconds": 15, "is_correct": True},
                {"question_id": "Q9", "response_time_seconds": 16, "is_correct": True},
                {"question_id": "Q10", "response_time_seconds": 17, "is_correct": True},
            ]
        )],
    )

    result = analyze_window(window)

    assert result["window_understanding_score"] == 90
    assert result["understanding_trend"] == "IMPROVING"


def test_empty_window_has_null_understanding_score():
    window = make_window(sections=[], is_final=True)

    result = analyze_window(window)

    assert result["window_understanding_score"] is None
    assert result["understanding_trend"] == "STABLE"


# ---------------------------------------------------------------------------
# C. Debounce
# ---------------------------------------------------------------------------

def test_debounce_first_action_always_emits():
    store = DebounceStore()
    assert store.should_emit("sess_a", "SLOW_PACE") is True


def test_debounce_same_action_suppressed_within_window():
    store = DebounceStore()
    assert store.should_emit("sess_a", "SLOW_PACE") is True
    assert store.should_emit("sess_a", "SLOW_PACE") is False


def test_debounce_escalation_always_passes():
    store = DebounceStore()
    assert store.should_emit("sess_a", "SLOW_PACE") is True
    # Higher severity -> must pass even immediately
    assert store.should_emit("sess_a", "SUGGEST_BREAK") is True


def test_debounce_downgrade_suppressed_within_window():
    store = DebounceStore()
    assert store.should_emit("sess_a", "SUGGEST_BREAK") is True
    # Lower severity within window -> suppress
    assert store.should_emit("sess_a", "CONTINUE") is False


def test_debounce_different_sessions_are_independent():
    store = DebounceStore()
    assert store.should_emit("sess_a", "SLOW_PACE") is True
    assert store.should_emit("sess_b", "SLOW_PACE") is True


def test_debounce_clear_releases_state():
    store = DebounceStore()
    store.should_emit("sess_a", "SLOW_PACE")
    store.clear("sess_a")
    # After clear, first-action rule applies again
    assert store.should_emit("sess_a", "SLOW_PACE") is True


def test_debounce_same_action_after_window_passes(monkeypatch):
    store = DebounceStore()
    # Freeze time progression manually
    base = time.time()

    # First emit
    monkeypatch.setattr(time, "time", lambda: base)
    assert store.should_emit("sess_a", "SLOW_PACE") is True

    # Same action immediately -> suppressed
    assert store.should_emit("sess_a", "SLOW_PACE") is False

    # Advance time past the window
    monkeypatch.setattr(time, "time", lambda: base + 200)
    assert store.should_emit("sess_a", "SLOW_PACE") is True


# ---------------------------------------------------------------------------
# D. analyze_window — happy path
# ---------------------------------------------------------------------------

def test_window_single_focused_section():
    window = make_window(
        sections=[make_section(
            time_spent_seconds=120,
            content_progression_pct=100,
            interaction_count=3,
            micro_challenges=[{"question_id": "Q1", "response_time_seconds": 8, "is_correct": True}],
        )],
    )
    result = analyze_window(window)

    assert result["window_index"] == 1
    assert result["window_state"] == "NORMAL_FOCUSED"
    assert result["window_focus_score"] == 100
    assert result["trend"] == "STABLE"
    assert result["sections_analyzed"] == 1


def test_window_dominant_state_is_most_frequent():
    """Two DISTRACTION sections + one NORMAL -> dominant is DISTRACTION."""
    window = make_window(
        sections=[
            make_section(
                section_id="d1",
                time_spent_seconds=60,
                background_count=4,
                total_background_seconds=60,
                content_progression_pct=20,
                interaction_count=0,
            ),
            make_section(
                section_id="d2",
                time_spent_seconds=60,
                background_count=4,
                total_background_seconds=60,
                content_progression_pct=20,
                interaction_count=0,
            ),
            make_section(
                section_id="n1",
                time_spent_seconds=60,
                content_progression_pct=100,
                interaction_count=3,
                micro_challenges=[{"question_id": "Q1", "response_time_seconds": 8, "is_correct": True}],
            ),
        ],
    )
    result = analyze_window(window)

    assert result["window_state"] == "DISTRACTION_DISENGAGEMENT"


# ---------------------------------------------------------------------------
# E. analyze_window — edge cases
# ---------------------------------------------------------------------------

def test_window_empty_sections_does_not_crash():
    """Student closed the app immediately."""
    window = make_window(sections=[], is_final=True)
    result = analyze_window(window)

    assert result["window_focus_score"] is None
    assert result["window_state"] == "NORMAL_FOCUSED"
    assert result["recommended_action"] == "CONTINUE"
    assert result["sections_analyzed"] == 0
    assert result.get("note") == "empty_window"


def test_window_is_final_clears_debounce():
    debounce_store.should_emit("s_test", "SLOW_PACE")
    window = make_window(
        sections=[make_section()],
        is_final=True,
    )
    analyze_window(window)
    # State should be wiped -> next emit is treated as first
    assert debounce_store.should_emit("s_test", "SLOW_PACE") is True


def test_window_malformed_section_is_skipped():
    """One bad section should not kill the whole window."""
    good = make_section(section_id="good")
    bad = make_section(section_id="bad")
    del bad.__dict__["time_spent_seconds"]

    window = make_window(sections=[good, bad])
    result = analyze_window(window)

    assert result["sections_analyzed"] == 1
    assert len(result["sections"]) == 1
    assert result["sections"][0]["section_id"] == "good"


# ---------------------------------------------------------------------------
# F. analyze_window — escalation rules
# ---------------------------------------------------------------------------

def test_window_escalation_repeated_distraction_suggests_break():
    """Two prior DISTRACTION windows + current DISTRACTION -> SUGGEST_BREAK."""
    history = [
        make_history_item(1, 30, "DISTRACTION_DISENGAGEMENT"),
        make_history_item(2, 30, "DISTRACTION_DISENGAGEMENT"),
    ]
    window = make_window(
        window_index=3,
        history=history,
        sections=[make_section(
            time_spent_seconds=180,
            background_count=4,
            total_background_seconds=60,
            content_progression_pct=20,
            interaction_count=0,
        )],
    )
    result = analyze_window(window)

    assert result["raw_action"] == "SUGGEST_BREAK"
    assert result["action_emitted"] is True


def test_window_escalation_consecutive_low_scores():
    """Two prior low scores + current low -> SUGGEST_BREAK."""
    history = [
        make_history_item(1, 40, "CONTENT_DIFFICULTY"),
        make_history_item(2, 40, "CONTENT_DIFFICULTY"),
    ]
    # Section scores below 50, validating consecutive-low-score escalation.
    window = make_window(
        window_index=3,
        history=history,
        sections=[make_section(
            time_spent_seconds=180,
            scroll_direction_changes=20,
            section_revisit_count=5,
            content_progression_pct=10,
            interaction_count=0,
            background_count=4,
            total_background_seconds=60,
        )],
    )
    result = analyze_window(window)

    assert result["raw_action"] == "SUGGEST_BREAK"


def test_window_declining_trend_upgrades_slow_pace():
    """Declining trend + CONTENT_DIFFICULTY high score -> SHOW_EXPLANATION."""
    history = [
        make_history_item(1, 95, "NORMAL_FOCUSED"),
        make_history_item(2, 90, "NORMAL_FOCUSED"),
    ]
    # Section scores 77: base action is SLOW_PACE, while 95 -> 90 -> 77
    # is a genuine declining trend, so it upgrades to SHOW_EXPLANATION.
    window = make_window(
        window_index=3,
        history=history,
        sections=[make_section(
            time_spent_seconds=180,
            scroll_direction_changes=8,
            section_revisit_count=3,
            content_progression_pct=95,
            interaction_count=3,
            micro_challenges=[{"question_id": "Q1", "response_time_seconds": 25, "is_correct": True}],
        )],
    )
    result = analyze_window(window)

    # Sanity: base action would be SLOW_PACE; decline upgrades it
    assert result["raw_action"] == "SHOW_EXPLANATION"