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
    scroll_speed_avg_px_per_sec: float
    scroll_direction_changes: int
    content_progression_pct: float
    section_revisit_count: int
    interaction_count: int
    background_count: int
    total_background_seconds: float
    micro_challenges: list[MicroChallenge] = field(default_factory=list)
    tab_hidden_count: int = 0

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
        )


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
# NEW: Real-time window models (periodic analysis every 5 min)
# ---------------------------------------------------------------------------

@dataclass
class WindowHistoryItem:
    """Summary of a previous window — Backend supplies this so we can
    compute trends and escalation without persisting state ourselves."""
    window_index: int
    focus_score: int
    state: str
    dominant_action: str
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