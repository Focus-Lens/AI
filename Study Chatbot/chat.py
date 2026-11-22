"""Chat logic: one Gemini request per message. The model returns {category, reply};
this code decides what the student sees.

The lecture is sent once per study session (start_session). For each question only the parts of
the lecture related to it are sent to Gemini (see retrieval.py).
"""

from __future__ import annotations

import math
from typing import Protocol

import config
from gemini_client import LLMResult, Usage
from prompts import KNOWLEDGE, REPLIES, system_prompt
from retrieval import LectureIndex, format_chunks, is_overview
from sessions import Session, SessionStore, store as default_store

CATEGORIES = ("app", "study", "other", "unsafe")

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "category": {"type": "STRING", "enum": list(CATEGORIES)},
        "reply": {"type": "STRING"},
    },
    "required": ["category", "reply"],
}


class LLM(Protocol):
    def json(self, system: str, contents: list[dict], schema: dict, temperature: float = 0.4) -> LLMResult: ...


class SessionNotFound(Exception):
    """Unknown or expired session_id and no lecture text sent to rebuild it."""


def estimate_tokens(text: str) -> int:
    """~4 characters per token: a safe rough estimate for Arabic + English."""
    return math.ceil(len(text) / 4)


def clean_history(history) -> list[dict]:
    """Keep only user/assistant turns with text, last few only. Drops anything else (e.g. role 'system')."""
    if not isinstance(history, list):
        return []
    turns = [
        {"role": h["role"], "text": h["text"][: config.MAX_MESSAGE_CHARS * 2]}
        for h in history
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and isinstance(h.get("text"), str) and h["text"].strip()
    ]
    return turns[-config.MAX_HISTORY_TURNS:]


def estimate_chat_tokens(message: str = "", history=None, has_material: bool = True) -> int:
    """Rough upper estimate of one chat turn, so the backend can check the user's balance first.
    It doesn't depend on the lecture length: at most MATERIAL_BUDGET_CHARS of it is sent."""
    h = "\n".join(t["text"] for t in clean_history(history or []))
    material = config.MATERIAL_BUDGET_CHARS if has_material else 0
    return estimate_tokens(KNOWLEDGE + h + message) + math.ceil(material / 4) + 600


def _result(reply, category, blocked, reason=None, usage: Usage | None = None, session_id=None,
            session_renewed=False, pages=None) -> dict:
    u = usage or Usage()
    return {
        "reply": reply,
        "category": category,
        "blocked": blocked,
        "reason": reason,
        "session_id": session_id,
        "session_renewed": session_renewed,
        "pages": pages or [],
        "usage": {"input": u.input, "output": u.output, "total": u.total},
    }


# ---------------------------------------------------------------------------
# Study session
# ---------------------------------------------------------------------------

def _session_info(s: Session) -> dict:
    pages = sorted({c.page for c in s.index.chunks if c.page is not None})
    return {
        "session_id": s.id,
        "chunks": len(s.index.chunks),
        "chars": len(s.index.text),
        "pages": len(pages),
        "truncated": s.index.truncated,
        "expires_at": s.expires_at(),
    }


def start_session(session_id: str, material_text: str = "", subject: str = "", lesson_title: str = "",
                  grade: str = "", store: SessionStore = default_store) -> dict:
    """Keep the lecture for this study session (no AI call, no tokens).
    Calling it again with the same session_id replaces the lecture and clears the history."""
    text = (material_text or "").strip()
    index = LectureIndex(text[: config.MAX_LECTURE_CHARS])
    index.truncated = len(text) > config.MAX_LECTURE_CHARS
    s = store.put(Session(
        id=session_id,
        index=index,
        subject=(subject or "")[: config.MAX_SUBJECT_CHARS],
        lesson_title=(lesson_title or "")[: config.MAX_SUBJECT_CHARS * 2],
        grade=(grade or "")[: config.MAX_SUBJECT_CHARS],
    ))
    return _session_info(s)


def end_session(session_id: str, store: SessionStore = default_store) -> bool:
    return store.end(session_id)


# ---------------------------------------------------------------------------
# One chat turn
# ---------------------------------------------------------------------------

def chat(message: str, llm: LLM, session_id: str = "", history=None, subject: str = "",
         material_text: str = "", store: SessionStore = default_store) -> dict:
    """One chat turn.

    session_id: from start_session. The lecture, subject and history come from the session.
      If the session is gone (expired / service restarted) and material_text is sent, it is rebuilt
      (session_renewed=true); without material_text -> SessionNotFound (API answers 409).
    history: optional. If sent it is used instead of the history kept in the session.
    Without session_id it works as a general study chat (material_text optional, not stored).

    Returns {reply, category, blocked, reason, session_id, session_renewed, pages, usage{input, output, total}}
      category: app | study | other | unsafe | invalid
      pages:    lecture pages (or parts) the answer was based on
      usage:    tokens this turn used (add usage.total to the user's daily total)
    """
    message = (message or "").strip()

    session: Session | None = None
    renewed = False
    if session_id:
        session = store.get(session_id)
        if session is None:
            if not (material_text or "").strip():
                raise SessionNotFound(session_id)
            start_session(session_id, material_text, subject=subject, store=store)
            session = store.get(session_id)
            renewed = True

    if not message:
        return _result(REPLIES["empty"], "invalid", True, "empty", session_id=session_id or None,
                       session_renewed=renewed)
    if len(message) > config.MAX_MESSAGE_CHARS:
        return _result(REPLIES["too_long"], "invalid", True, "too_long", session_id=session_id or None,
                       session_renewed=renewed)

    if session:
        index = session.index
        subject = session.subject or (subject or "")[: config.MAX_SUBJECT_CHARS]
        turns = clean_history(history) if history else list(session.history)
    else:
        text = (material_text or "").strip()
        index = LectureIndex(text[: config.MAX_LECTURE_CHARS]) if text else None
        subject = (subject or "")[: config.MAX_SUBJECT_CHARS]
        turns = clean_history(history)

    chunks = []
    kw_usage = Usage()
    if index and index.chunks:
        previous = next((t["text"] for t in reversed(turns) if t["role"] == "user"), "")
        extra = ""
        # Question in a different language than the lecture (e.g. Arabic question, English lecture):
        # ask the model for search keywords in the lecture's language. One small extra request, only
        # in this case; if it fails we search as before.
        target = index.translation_target(message)
        if (target and len(index.text) > config.MATERIAL_BUDGET_CHARS and not is_overview(message)
                and hasattr(llm, "keywords")):
            try:
                words, kw_usage = llm.keywords(message, previous, target)
                extra = " ".join(words)
            except Exception:
                extra, kw_usage = "", Usage()
        chunks = index.search(message, previous_question=previous, extra_terms=extra,
                              fallback_ids=session.last_chunk_ids if session else None)
    pages = sorted({c.page if c.page is not None else c.id + 1 for c in chunks})

    contents = [
        {"role": "user" if t["role"] == "user" else "model", "parts": [{"text": t["text"]}]} for t in turns
    ]
    last = (f"<material>\n{format_chunks(chunks)}\n</material>\n" if chunks else "") + \
        f"<student_message>\n{message}\n</student_message>"
    contents.append({"role": "user", "parts": [{"text": last}]})

    system = system_prompt(subject, bool(chunks),
                           lesson_title=session.lesson_title if session else "",
                           grade=session.grade if session else "")
    r = llm.json(system, contents, SCHEMA)
    usage = Usage(r.usage.input + kw_usage.input, r.usage.output + kw_usage.output,
                  r.usage.total + kw_usage.total)  # the keyword request (if any) counts too

    category = "unsafe" if r.blocked else (r.data or {}).get("category")
    if category not in CATEGORIES:
        category = "other"  # unknown or unreadable output: fail closed

    sid = session.id if session else None
    if category in ("other", "unsafe"):
        # Never show the model's own text for these, and don't keep them in the history.
        reply = REPLIES["unsafe"] if category == "unsafe" else REPLIES["off_topic"]
        return _result(reply, category, True, r.reason if r.blocked else "filtered", usage, sid, renewed)

    reply = ((r.data or {}).get("reply") or "").strip()
    if not reply:
        return _result(REPLIES["off_topic"], category, True, r.reason or "empty_answer", usage, sid, renewed)

    if session:
        session.add_turn(message, reply)
        session.last_chunk_ids = [c.id for c in chunks]
    return _result(reply, category, False, None, usage, sid, renewed, pages)
