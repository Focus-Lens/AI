"""Tests for the P1 fixes: null semantics, MCQ evidence, MCQ metrics,
timestamp validation, null focus_score in history, service-key auth."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("AI2_AUTH_DISABLED", "true")  # api.py guards at import

import pytest

from data_models import Section, MicroChallenge, AnalysisWindow, WindowHistoryItem
from feature_extraction import extract_features, compute_mcq_accuracy_counts
from state_detection import detect_state
from pipeline import analyze_section, analyze_window
from trend_analysis import compute_trend, consecutive_low_score_count


def sec(**over) -> Section:
    d = dict(section_id="s", concept_id="c", time_spent_seconds=120,
             scroll_speed_avg_px_per_sec=200, scroll_direction_changes=1,
             content_progression_pct=100, section_revisit_count=0,
             interaction_count=2, background_count=0, total_background_seconds=0)
    d.update(over)
    return Section.from_dict(d)


def mcqs(n, correct=False, rt=10):
    return [{"question_id": f"Q{i}", "response_time_seconds": rt, "is_correct": correct}
            for i in range(1, n + 1)]


# ---------------- Task 1: None vs 0 ----------------

def test_missing_keys_are_none_not_zero():
    s = Section.from_dict({"section_id": "s", "concept_id": "c",
                           "time_spent_seconds": 120, "content_progression_pct": 20})
    assert s.interaction_count is None
    assert s.background_count is None
    assert s.total_background_seconds is None
    assert s.scroll_speed_avg_px_per_sec is None
    assert s.scroll_direction_changes is None
    assert s.tab_hidden_count is None


def test_missing_vs_reported_zero_behave_differently():
    base = {"section_id": "s", "concept_id": "c", "time_spent_seconds": 120,
            "content_progression_pct": 20}
    missing = analyze_section(Section.from_dict(dict(base)))
    zero = analyze_section(Section.from_dict(dict(base, interaction_count=0)))
    assert missing["features_used"]["interaction"] is None
    assert zero["features_used"]["interaction"] == "NONE"
    assert missing["state"] != "DISTRACTION_DISENGAGEMENT"
    assert zero["state"] == "DISTRACTION_DISENGAGEMENT"   # 0 interactions for 120s


def test_tab_hidden_missing_and_zero_are_distinct():
    base = {"section_id": "s", "concept_id": "c", "time_spent_seconds": 30,
            "content_progression_pct": 80}
    missing = extract_features(Section.from_dict(base))
    reported_zero = extract_features(Section.from_dict(dict(base, tab_hidden_count=0)))
    assert missing["tab_hidden_count"] is None
    assert missing["disengagement"] is None
    assert reported_zero["tab_hidden_count"] == 0
    assert reported_zero["disengagement"] == "FOCUSED"


# ---------------- Task 2: MCQ evidence ----------------

def test_one_wrong_answer_is_not_evidence():
    r = analyze_section(sec(micro_challenges=mcqs(1)))
    f = r["features_used"]
    assert f["mcq_accuracy"] is None and f["mcq_response_time"] is None
    assert f["mcq_count"] == 1
    assert r["state"] not in ("WEAK_UNDERSTANDING", "SKIMMING")
    # focus score is not penalised by a single observation either
    assert r["focusScore"] == analyze_section(sec())["focusScore"]


def test_one_fast_wrong_answer_plus_fast_scroll_gets_no_mcq_contribution():
    fast = dict(scroll_speed_avg_px_per_sec=500)
    without = detect_state(extract_features(sec(**fast)))
    with_one = detect_state(extract_features(sec(micro_challenges=mcqs(1, rt=1), **fast)))
    assert with_one == without   # the single MCQ changed nothing


def test_single_fast_scroll_does_not_activate_skimming_or_intervention():
    result = analyze_section(sec(scroll_speed_avg_px_per_sec=500))
    assert result["state"] == "NORMAL_FOCUSED"
    assert result["recommendedAction"] == "CONTINUE"


def test_skimming_still_activates_with_corroborating_evidence():
    result = analyze_section(
        sec(scroll_speed_avg_px_per_sec=500, micro_challenges=mcqs(3, correct=False, rt=1))
    )
    assert result["state"] == "SKIMMING"
    assert result["confidence"] == 0.5


def test_enough_evidence_activates_with_scaled_confidence():
    three = analyze_section(sec(micro_challenges=mcqs(3)))
    six = analyze_section(sec(micro_challenges=mcqs(6)))
    assert three["state"] == "WEAK_UNDERSTANDING"
    assert three["rule_match_score"] == 1.0
    assert three["confidence"] == 0.5          # 3 of 6 for full confidence
    assert six["confidence"] == 1.0


# ---------------- Task 5: MCQ metrics ----------------

def _attempts():
    # Q1: wrong, wrong, correct   Q2: correct
    return [MicroChallenge("Q1", 5, False), MicroChallenge("Q1", 5, False),
            MicroChallenge("Q1", 5, True), MicroChallenge("Q2", 5, True)]


def test_mcq_metrics_differ_on_the_same_data():
    assert compute_mcq_accuracy_counts(_attempts(), "attempt_accuracy") == (2, 4)
    assert compute_mcq_accuracy_counts(_attempts(), "first_attempt_accuracy") == (1, 2)
    assert compute_mcq_accuracy_counts(_attempts(), "final_answer_accuracy") == (2, 2)


def test_mcq_metric_empty_and_invalid():
    assert compute_mcq_accuracy_counts([], "attempt_accuracy") == (0, 0)
    with pytest.raises(ValueError):
        compute_mcq_accuracy_counts(_attempts(), "nope")


# ---------------- Task 4: null focus_score in history ----------------

def _h(i, score, state="NORMAL_FOCUSED"):
    return WindowHistoryItem.from_dict({"window_index": i, "focus_score": score,
                                        "state": state, "dominant_action": "CONTINUE"})


def test_trend_ignores_null_scores():
    assert compute_trend([80, None, 60, None, 40]) == "DECLINING"
    assert compute_trend([None, None, 70]) == "STABLE"


def test_low_score_streak_skips_nulls_without_breaking_or_counting():
    hist = [_h(1, 40), _h(2, None), _h(3, 45)]
    assert consecutive_low_score_count(hist, 30) == 3        # nulls not counted
    assert consecutive_low_score_count([_h(1, 90), _h(2, None)], 30) == 1  # null doesn't extend it


def test_history_item_accepts_missing_or_null_focus_score():
    assert WindowHistoryItem.from_dict(
        {"window_index": 1, "focus_score": None, "state": "NORMAL_FOCUSED",
         "dominant_action": "CONTINUE"}).focus_score is None
    assert WindowHistoryItem.from_dict(
        {"window_index": 1, "state": "NORMAL_FOCUSED", "dominant_action": "CONTINUE"}
    ).focus_score is None


def test_analyze_window_with_null_history_scores():
    w = AnalysisWindow.from_dict({
        "user_id": "u", "session_id": "p1-null-hist", "window_index": 4,
        "window_start": 0, "window_end": 1000, "is_final": True,
        "sections": [sec().__dict__ | {"micro_challenges": []}],
        "history": [{"window_index": 1, "focus_score": None, "state": "NORMAL_FOCUSED",
                     "dominant_action": "CONTINUE"},
                    {"window_index": 2, "focus_score": 90, "state": "NORMAL_FOCUSED",
                     "dominant_action": "CONTINUE"}],
    })
    out = analyze_window(w)
    assert out["window_focus_score"] is not None
    assert out["trend"] in ("STABLE", "IMPROVING", "DECLINING")


# ---------------- Task 3 + 6: real endpoints ----------------

def _client():
    from fastapi.testclient import TestClient   # skipped where fastapi isn't installed
    import api
    return TestClient(api.app)


def _window(**over):
    d = {"user_id": "u", "session_id": "p1-api", "window_index": 1,
         "window_start": 1_000_000, "window_end": 1_300_000, "sections": [], "history": []}
    d.update(over)
    return d


def _section(**over):
    d = {"section_id": "s", "concept_id": "c", "time_spent_seconds": 10,
         "content_progression_pct": 10}
    d.update(over)
    return d


def test_api_rejects_window_end_before_start():
    r = _client().post("/ai2/analyze-window", json=_window(window_start=2000, window_end=1000))
    assert r.status_code == 422


def test_api_rejects_window_too_long():
    r = _client().post("/ai2/analyze-window",
                       json=_window(window_start=0, window_end=31 * 60 * 1000))
    assert r.status_code == 422


def test_api_rejects_session_end_before_start():
    r = _client().post("/ai2/analyze-session", json={
        "user_id": "u", "session_id": "s", "session_start": 2000, "session_end": 1000,
        "sections": []})
    assert r.status_code == 422


def test_api_rejects_section_end_before_start():
    r = _client().post("/ai2/analyze-window", json=_window(
        sections=[_section(section_start_time=2000, section_end_time=1000)]))
    assert r.status_code == 422


def test_api_accepts_null_history_focus_score():
    r = _client().post("/ai2/analyze-window", json=_window(
        history=[{"window_index": 1, "focus_score": None, "state": "NORMAL_FOCUSED",
                  "dominant_action": "CONTINUE"}]))
    assert r.status_code == 200


def test_api_auth_rules(monkeypatch):
    c = _client()
    monkeypatch.setenv("AI2_AUTH_DISABLED", "false")
    monkeypatch.setenv("AI2_SERVICE_KEY", "secret-key")
    body = _window()
    assert c.post("/ai2/analyze-window", json=body).status_code == 401
    assert c.post("/ai2/analyze-window", json=body,
                  headers={"X-Service-Key": "wrong"}).status_code == 401
    assert c.post("/ai2/analyze-window", json=body,
                  headers={"X-Service-Key": "secret-key"}).status_code == 200
    assert c.post("/ai2/analyze-session", json={
        "user_id": "u", "session_id": "s", "session_start": 1, "session_end": 2,
        "sections": []}).status_code == 401
    assert c.get("/health").status_code == 200          # stays unauthenticated
