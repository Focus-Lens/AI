import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("AI2_AUTH_DISABLED", "true")  # api.py guards at import

import pytest
from pydantic import ValidationError

import feature_extraction as fe
from data_models import Section, AnalysisWindow, effective_time_seconds
from feature_extraction import extract_features
from focus_score import weighted_window_score
from state_detection import detect_state
from pipeline import _dominant_state, analyze_window


def make_section(**over) -> Section:
    d = dict(
        section_id="s", concept_id="c",
        time_spent_seconds=60.0,
        scroll_speed_avg_px_per_sec=200.0,
        scroll_direction_changes=0,
        content_progression_pct=95.0,
        section_revisit_count=0,
        interaction_count=3,
        background_count=0,
        total_background_seconds=0.0,
    )
    d.update(over)
    return Section.from_dict(d)


def state_of(section):
    return detect_state(extract_features(section))["state"]


# ---------------- Task 1: distraction gate ----------------

def test_weak_signals_alone_do_not_activate_distraction():
    s = make_section(background_count=0, total_background_seconds=0.0,
                     content_progression_pct=20, interaction_count=0,
                     time_spent_seconds=30)
    f = extract_features(s)
    assert f["progression"] == "INCOMPLETE" and f["interaction"] == "NONE"
    assert f["strong_disengagement"] is False
    assert state_of(s) != "DISTRACTION_DISENGAGEMENT"


def test_background_count_activates():
    s = make_section(background_count=1, total_background_seconds=3.0,
                     content_progression_pct=20, interaction_count=0,
                     time_spent_seconds=30)
    assert state_of(s) == "DISTRACTION_DISENGAGEMENT"


def test_background_seconds_activate():
    s = make_section(background_count=0, total_background_seconds=10.0,
                     content_progression_pct=20, interaction_count=0,
                     time_spent_seconds=30)
    assert state_of(s) == "DISTRACTION_DISENGAGEMENT"


def test_prolonged_inactivity_activates():
    s = make_section(background_count=0, total_background_seconds=0.0,
                     content_progression_pct=20, interaction_count=0,
                     time_spent_seconds=120)
    assert state_of(s) == "DISTRACTION_DISENGAGEMENT"


def test_inactivity_threshold_is_strictly_greater_and_configurable(monkeypatch):
    s = make_section(content_progression_pct=20, interaction_count=0, time_spent_seconds=60)
    assert state_of(s) != "DISTRACTION_DISENGAGEMENT"      # exactly 60 -> not > 60
    monkeypatch.setattr(fe, "DISTRACTION_MIN_INACTIVE_SECONDS", 30)
    assert state_of(s) == "DISTRACTION_DISENGAGEMENT"


def test_none_telemetry_is_never_a_strong_signal():
    s = make_section(background_count=None, total_background_seconds=None,
                     interaction_count=None, scroll_speed_avg_px_per_sec=None,
                     scroll_direction_changes=None,
                     content_progression_pct=20, time_spent_seconds=300)
    f = extract_features(s)
    assert f["disengagement"] is None and f["interaction"] is None
    assert f["strong_disengagement"] is False
    assert state_of(s) != "DISTRACTION_DISENGAGEMENT"


# ---------------- Task 2: effective time ----------------

def test_effective_time_priority_levels():
    assert effective_time_seconds(make_section(
        active_time_seconds=40, time_spent_seconds=300, total_background_seconds=100)) == 40
    assert effective_time_seconds(make_section(
        time_spent_seconds=300, total_background_seconds=100)) == 200
    assert effective_time_seconds(make_section(
        time_spent_seconds=300, total_background_seconds=None)) == 300


def test_effective_time_clamps_at_zero_and_respects_zero_active():
    assert effective_time_seconds(make_section(
        time_spent_seconds=50, total_background_seconds=80)) == 0
    assert effective_time_seconds(make_section(
        active_time_seconds=0.0, time_spent_seconds=300)) == 0


def test_interaction_rate_uses_effective_time():
    base = dict(interaction_count=6, time_spent_seconds=300, total_background_seconds=None)
    assert extract_features(make_section(**base))["interaction"] == "NORMAL"          # 1.2/min
    assert extract_features(make_section(active_time_seconds=60, **base))["interaction"] == "HIGH"  # 6/min


def test_inactive_gap_gets_no_extra_window_weight_when_active_time_supplied():
    results = [{"focusScore": 100}, {"focusScore": 0}]
    a = make_section(time_spent_seconds=60, total_background_seconds=None)
    b_gap = make_section(time_spent_seconds=600, total_background_seconds=None)
    b_active = make_section(time_spent_seconds=600, total_background_seconds=None,
                            active_time_seconds=60)
    assert weighted_window_score(results, [a, b_gap]) == round(6000 / 660)   # 9
    assert weighted_window_score(results, [a, b_active]) == 50


def test_api_model_active_time_validation():
    from api import SectionIn
    base = dict(section_id="s", concept_id="c", time_spent_seconds=1, content_progression_pct=10)
    assert SectionIn(**base).active_time_seconds is None
    assert SectionIn(**base, active_time_seconds=0).active_time_seconds == 0
    with pytest.raises(ValidationError):
        SectionIn(**base, active_time_seconds=-1)


# ---------------- Task 3: dominant state ----------------

def _r(*states):
    return [{"state": s} for s in states]


def test_long_section_beats_short_one():
    secs = [make_section(time_spent_seconds=5, total_background_seconds=None),
            make_section(time_spent_seconds=295, total_background_seconds=None)]
    assert _dominant_state(_r("DISTRACTION_DISENGAGEMENT", "NORMAL_FOCUSED"), secs) == "NORMAL_FOCUSED"


def test_exact_tie_uses_severity():
    secs = [make_section(time_spent_seconds=100, total_background_seconds=None) for _ in range(2)]
    assert _dominant_state(_r("SKIMMING", "DISTRACTION_DISENGAGEMENT"), secs) == "DISTRACTION_DISENGAGEMENT"
    assert _dominant_state(_r("NORMAL_FOCUSED", "SKIMMING"), secs) == "SKIMMING"


def test_all_zero_durations_use_severity():
    secs = [make_section(time_spent_seconds=0, total_background_seconds=None) for _ in range(2)]
    assert _dominant_state(_r("NORMAL_FOCUSED", "WEAK_UNDERSTANDING"), secs) == "WEAK_UNDERSTANDING"


def test_single_section_and_empty():
    s = [make_section(time_spent_seconds=10, total_background_seconds=None)]
    assert _dominant_state(_r("SKIMMING"), s) == "SKIMMING"
    assert _dominant_state([], []) == "NORMAL_FOCUSED"


def test_dominant_state_uses_effective_not_raw_time():
    a = make_section(time_spent_seconds=300, total_background_seconds=290)   # effective 10
    b = make_section(time_spent_seconds=60, total_background_seconds=0.0)    # effective 60
    assert _dominant_state(_r("DISTRACTION_DISENGAGEMENT", "NORMAL_FOCUSED"), [a, b]) == "NORMAL_FOCUSED"


def test_empty_window_unchanged():
    w = AnalysisWindow.from_dict(dict(user_id="u", session_id="p2-empty", window_index=1,
                                      window_start=0, window_end=1000, is_final=True,
                                      sections=[], history=[]))
    out = analyze_window(w)
    assert out["window_focus_score"] is None
    assert out["window_state"] == "NORMAL_FOCUSED"
    assert out["recommended_action"] == "CONTINUE"


# ---------------- Task 4: contract ----------------

def test_dominant_action_description_states_raw():
    from api import WindowHistoryItemIn
    desc = WindowHistoryItemIn.model_fields["dominant_action"].description
    assert "RAW" in desc and "NOT the debounced" in desc