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

import hmac
import os

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from data_models import SessionPayload, AnalysisWindow
from pipeline import analyze_session, analyze_window


# ---------------------------------------------------------------------------
# All *_start / *_end fields are epoch milliseconds, matching the rest of
# the schema. These ceilings are generous on purpose — they exist to catch
# obviously-broken payloads (e.g. a swapped start/end, or a stuck client
# clock), not to police realistic session lengths.
MAX_SECTION_DURATION_SECONDS = int(os.environ.get("AI2_MAX_SECTION_DURATION_SECONDS", 4 * 60 * 60))       # 4h
MAX_SESSION_DURATION_MS = int(os.environ.get("AI2_MAX_SESSION_DURATION_MS", 12 * 60 * 60 * 1000))         # 12h
MAX_WINDOW_DURATION_MS = int(os.environ.get("AI2_MAX_WINDOW_DURATION_MS", 30 * 60 * 1000))                # 30min

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
    # None = telemetry not reported, 0 = reported and genuinely
    # zero. ge=0 still applies to any value that IS provided.
    scroll_speed_avg_px_per_sec: float | None = Field(default=None, ge=0)
    scroll_direction_changes: int | None = Field(default=None, ge=0)
    content_progression_pct: float = Field(ge=0, le=100)
    section_revisit_count: int = Field(ge=0, default=0)
    interaction_count: int | None = Field(default=None, ge=0)
    background_count: int | None = Field(default=None, ge=0)
    total_background_seconds: float | None = Field(default=None, ge=0)
    micro_challenges: list[MicroChallengeIn] = []
    tab_hidden_count: int = 0
    active_time_seconds: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Optional. Seconds the learner was actively engaged (foreground, "
            "recent input) in this section. When provided it is used for "
            "interaction rate and window weighting instead of "
            "time_spent_seconds. None = not reported."
        ),
    )

    @model_validator(mode="after")
    def _validate_section_times(self):
        if self.section_end_time < self.section_start_time:
            raise ValueError("section_end_time must be >= section_start_time")
        duration_s = (self.section_end_time - self.section_start_time) / 1000
        if duration_s > MAX_SECTION_DURATION_SECONDS:
            raise ValueError(
                f"section duration ({duration_s}s) exceeds max allowed "
                f"({MAX_SECTION_DURATION_SECONDS}s)"
            )
        if self.time_spent_seconds > MAX_SECTION_DURATION_SECONDS:
            raise ValueError(
                f"time_spent_seconds ({self.time_spent_seconds}) exceeds max allowed "
                f"({MAX_SECTION_DURATION_SECONDS}s)"
            )
        return self


class SessionIn(BaseModel):
    user_id: str
    session_id: str
    session_start: int
    session_end: int
    sections: list[SectionIn]

    @model_validator(mode="after")
    def _validate_session_times(self):
        if self.session_end < self.session_start:
            raise ValueError("session_end must be >= session_start")
        duration_ms = self.session_end - self.session_start
        if duration_ms > MAX_SESSION_DURATION_MS:
            raise ValueError(
                f"session duration ({duration_ms}ms) exceeds max allowed "
                f"({MAX_SESSION_DURATION_MS}ms)"
            )
        return self


class WindowHistoryItemIn(BaseModel):
    window_index: int
    focus_score: int | None = Field(default=None, ge=0, le=100)
    state: str
    dominant_action: str = Field(
        description=(
            "The RAW action the AI returned for that window (`raw_action` in "
            "the analyze-window response). NOT the debounced "
            "`recommended_action`, and never 'SUPPRESSED'. Informational only; "
            "not used by trend/escalation logic."
        )
    )
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

    @model_validator(mode="after")
    def _validate_window_times(self):
        if self.window_end < self.window_start:
            raise ValueError("window_end must be >= window_start")
        duration_ms = self.window_end - self.window_start
        if duration_ms > MAX_WINDOW_DURATION_MS:
            raise ValueError(
                f"window duration ({duration_ms}ms) exceeds max allowed "
                f"({MAX_WINDOW_DURATION_MS}ms)"
            )
        return self


# ---------------------------------------------------------------------------
# 1b. Service-to-service authentication
# ---------------------------------------------------------------------------
# Fail clearly at import (= startup, for this single-process service) if no
# key is configured and auth wasn't explicitly disabled for local dev.
_AI2_AUTH_DISABLED_AT_STARTUP = os.environ.get("AI2_AUTH_DISABLED", "false").lower() == "true"
if not _AI2_AUTH_DISABLED_AT_STARTUP and not os.environ.get("AI2_SERVICE_KEY"):
    raise RuntimeError(
        "AI2_SERVICE_KEY is not set. Set it to a shared secret the .NET "
        "backend will also send, or set AI2_AUTH_DISABLED=true explicitly "
        "for local development only."
    )


def require_service_key(x_service_key: str | None = Header(default=None, alias="X-Service-Key")) -> None:
    """FastAPI dependency guarding the two analyze endpoints. Reads env vars
    fresh on every call (rather than caching at import time) so tests can
    toggle AI2_AUTH_DISABLED / AI2_SERVICE_KEY per-test with monkeypatch."""
    if os.environ.get("AI2_AUTH_DISABLED", "false").lower() == "true":
        return

    service_key = os.environ.get("AI2_SERVICE_KEY")
    if not service_key:
        # Startup guard above should prevent this; defend anyway against
        # the env var being cleared after the process started.
        raise HTTPException(status_code=500, detail="AI2_SERVICE_KEY not configured")

    if x_service_key is None or not hmac.compare_digest(x_service_key.encode("utf-8"), service_key.encode("utf-8")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Service-Key")


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


@app.post("/ai2/analyze-session", dependencies=[Depends(require_service_key)])
def analyze_session_endpoint(payload: SessionIn):
    """
    End-of-session batch endpoint. Backend sends the full session once.
    """
    try:
        session = SessionPayload.from_dict(payload.model_dump())
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Malformed payload: {exc}")

    return analyze_session(session)


@app.post("/ai2/analyze-window", dependencies=[Depends(require_service_key)])
def analyze_window_endpoint(payload: AnalysisWindowIn):
    """
    Real-time endpoint. Backend calls every 5 min (or earlier if the
    student closes the session). Returns window-level score + debounced
    recommended action. Backend supplies history with each call.

    History items: `dominant_action` must be the RAW action (`raw_action` of
    a previous response), not the debounced `recommended_action`.
    """
    try:
        window = AnalysisWindow.from_dict(payload.model_dump())
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Malformed payload: {exc}")

    return analyze_window(window)