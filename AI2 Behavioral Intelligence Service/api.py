"""
AI2 Behavioral Intelligence Service — HTTP API.

Two endpoints:
  POST /ai2/analyze-session  — end-of-session batch analysis (existing).
  POST /ai2/analyze-window   — real-time periodic analysis (every 5 min).

Run locally:
    uvicorn api:app --reload --port 8000

Interactive docs:
    http://localhost:8000/docs
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from data_models import SessionPayload, AnalysisWindow
from pipeline import analyze_session, analyze_window


# ---------------------------------------------------------------------------
# 1. Pydantic request models
# ---------------------------------------------------------------------------

class MicroChallengeIn(BaseModel):
    question_id: str
    response_time_seconds: float = Field(ge=0)
    is_correct: bool


class SectionIn(BaseModel):
    section_id: str
    concept_id: str
    section_start_time: int = 0
    section_end_time: int = 0
    time_spent_seconds: float = Field(ge=0)
    scroll_speed_avg_px_per_sec: float = Field(ge=0, default=0.0)
    scroll_direction_changes: int = Field(ge=0, default=0)
    content_progression_pct: float = Field(ge=0, le=100)
    section_revisit_count: int = Field(ge=0, default=0)
    interaction_count: int = Field(ge=0, default=0)
    background_count: int = Field(ge=0, default=0)
    total_background_seconds: float = Field(ge=0, default=0.0)
    micro_challenges: list[MicroChallengeIn] = []
    tab_hidden_count: int = 0


class SessionIn(BaseModel):
    user_id: str
    session_id: str
    session_start: int
    session_end: int
    sections: list[SectionIn]


class WindowHistoryItemIn(BaseModel):
    window_index: int
    focus_score: int = Field(ge=0, le=100)
    state: str
    dominant_action: str
    understanding_score: int | None = Field(default=None, ge=0, le=100)


class AnalysisWindowIn(BaseModel):
    user_id: str
    session_id: str
    window_index: int = Field(ge=1)
    window_start: int
    window_end: int
    is_final: bool = False
    sections: list[SectionIn] = []
    history: list[WindowHistoryItemIn] = []


# ---------------------------------------------------------------------------
# 2. FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI2 Behavioral Intelligence Service",
    description=(
        "Analyzes learner session behavior and returns state, focus score, "
        "and recommended action. Supports both end-of-session batch mode "
        "and real-time 5-minute window analysis."
    ),
    version="0.2.0",
)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/ai2/analyze-session")
def analyze_session_endpoint(payload: SessionIn):
    """
    End-of-session batch endpoint. Backend sends the full session once.
    """
    try:
        session = SessionPayload.from_dict(payload.model_dump())
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Malformed payload: {exc}")

    return analyze_session(session)


@app.post("/ai2/analyze-window")
def analyze_window_endpoint(payload: AnalysisWindowIn):
    """
    Real-time endpoint. Backend calls every 5 min (or earlier if the
    student closes the session). Returns window-level score + debounced
    recommended action. Backend supplies history with each call.
    """
    try:
        window = AnalysisWindow.from_dict(payload.model_dump())
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Malformed payload: {exc}")

    return analyze_window(window)