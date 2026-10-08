"""
Data models for the AI2 Behavioral Intelligence service.
Mirrors the schema defined in data_dictionary.md — keep both in sync.
"""

from dataclasses import dataclass, field


@dataclass
class MicroChallenge:
    """One micro-challenge (MCQ) attempt tied to a section."""
    question_id: str
    response_time_seconds: float
    is_correct: bool

    @classmethod
    def from_dict(cls, data: dict) -> "MicroChallenge":
        return cls(
            question_id=data["question_id"],
            response_time_seconds=data["response_time_seconds"],
            is_correct=data["is_correct"],
        )


@dataclass
class Section:
    """One section visit record within a session."""
    section_id: str
    concept_id: str
    section_start_time: int
    section_end_time: int
    time_spent_seconds: float
    # None means "telemetry not reported", 0 means "reported, genuinely zero"
    scroll_speed_avg_px_per_sec: float | None
    scroll_direction_changes: int | None
    content_progression_pct: float
    section_revisit_count: int
    interaction_count: int | None
    background_count: int | None
    total_background_seconds: float | None
    micro_challenges: list[MicroChallenge] = field(default_factory=list)
    tab_hidden_count: int = 0
    # P2: seconds the learner was actually active in this section
    # (foreground + recent input). None = not reported by the backend.
    active_time_seconds: float | None = None

    @property
    def has_mcq(self) -> bool:
        return len(self.micro_challenges) > 0

    @classmethod
    def from_dict(cls, data: dict) -> "Section":
        mcqs = [
            MicroChallenge.from_dict(m) for m in data.get("micro_challenges", [])
        ]
        return cls(
            section_id=data["section_id"],
            concept_id=data["concept_id"],
            section_start_time=data.get("section_start_time", 0),
            section_end_time=data.get("section_end_time", 0),
            time_spent_seconds=data.get("time_spent_seconds", 0.0),
            scroll_speed_avg_px_per_sec=data.get("scroll_speed_avg_px_per_sec", 0.0),
            scroll_direction_changes=data.get("scroll_direction_changes", 0),
            content_progression_pct=data.get("content_progression_pct", 0.0),
            section_revisit_count=data.get("section_revisit_count", 0),
            interaction_count=data.get("interaction_count", 0),
            background_count=data.get("background_count", 0),
            total_background_seconds=data.get("total_background_seconds", 0.0),
            micro_challenges=mcqs,
            tab_hidden_count=data.get("tab_hidden_count", 0),
            active_time_seconds=data.get("active_time_seconds"),
        )


def effective_time_seconds(section) -> float:
    """
    Single source of truth for "how long did the learner really spend here".
    Used for the interaction rate, window duration weighting and
    dominant-state weighting. Nothing else should read time_spent_seconds
    for those purposes.

    Priority:
      1. active_time_seconds, if provided (0 is a valid value and is respected)
      2. else time_spent_seconds - total_background_seconds, if the latter
         is not None (never below 0)
      3. else time_spent_seconds

    Result is always >= 0.
    """
    active = getattr(section, "active_time_seconds", None)
    if active is not None:
        return max(0.0, float(active))

    spent = float(section.time_spent_seconds)
    background = getattr(section, "total_background_seconds", None)
    if background is not None:
        return max(0.0, spent - float(background))

    return max(0.0, spent)


@dataclass
class SessionPayload:
    """Top-level payload received from Backend at end of session."""
    user_id: str
    session_id: str
    session_start: int
    session_end: int
    sections: list[Section] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionPayload":
        return cls(
            user_id=data["user_id"],
            session_id=data["session_id"],
            session_start=data.get("session_start", 0),
            session_end=data.get("session_end", 0),
            sections=[Section.from_dict(s) for s in data.get("sections", [])],
        )


# ---------------------------------------------------------------------------
# Real-time window models (periodic analysis every 5 min)
# ---------------------------------------------------------------------------

@dataclass
class WindowHistoryItem:
    """Summary of a previous window — Backend supplies this so we can
    compute trends and escalation without persisting state ourselves.

    dominant_action is the RAW action the AI computed for that window
    (the `raw_action` field of the analyze-window response), NOT the
    debounced `recommended_action` and never a SUPPRESSED marker. The AI
    does not use it for trend/escalation; it is carried for logging only."""
    window_index: int
    focus_score: int
    state: str
    dominant_action: str  # RAW action (pre-debounce), see class docstring
    understanding_score: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "WindowHistoryItem":
        return cls(
            window_index=data["window_index"],
            focus_score=data["focus_score"],
            state=data["state"],
            dominant_action=data["dominant_action"],
            understanding_score=data.get("understanding_score"),
        )


@dataclass
class AnalysisWindow:
    """One periodic analysis window (every 5 min, or shorter if the
    student closes the session early). Backend supplies history with
    each call — service remains otherwise stateless."""
    user_id: str
    session_id: str
    window_index: int
    window_start: int
    window_end: int
    is_final: bool
    sections: list[Section] = field(default_factory=list)
    history: list[WindowHistoryItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "AnalysisWindow":
        sections = [
            s if isinstance(s, Section) else Section.from_dict(s)
            for s in data.get("sections", [])
        ]

        return cls(
            user_id=data["user_id"],
            session_id=data["session_id"],
            window_index=data["window_index"],
            window_start=data["window_start"],
            window_end=data["window_end"],
            is_final=data.get("is_final", False),
            sections=sections,
            history=[
                h if isinstance(h, WindowHistoryItem) else WindowHistoryItem.from_dict(h)
                for h in data.get("history", [])
            ],
        )


# ---------------------------------------------------------------------------
# Module-level convenience wrapper
# ---------------------------------------------------------------------------

def parse_session_payload(data: dict) -> SessionPayload:
    return SessionPayload.from_dict(data)