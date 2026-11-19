"""Chat logic: one Gemini request per message. The model returns {category, reply};
this code decides what the student sees."""

from __future__ import annotations

import math
from typing import Protocol

import config
from gemini_client import LLMResult, Usage
from prompts import KNOWLEDGE, REPLIES, system_prompt

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


def estimate_chat_tokens(message: str = "", history=None, material_text: str = "") -> int:
    """Rough upper estimate of one chat turn, so the backend can check the user's balance first."""
    h = "\n".join(t["text"] for t in clean_history(history or []))
    return estimate_tokens(KNOWLEDGE + (material_text or "")[: config.MAX_MATERIAL_CHARS] + h + message) + 600


def _result(reply, category, blocked, reason=None, usage: Usage | None = None) -> dict:
    u = usage or Usage()
    return {
        "reply": reply,
        "category": category,
        "blocked": blocked,
        "reason": reason,
        "usage": {"input": u.input, "output": u.output, "total": u.total},
    }


def chat(message: str, llm: LLM, history=None, subject: str = "", material_text: str = "") -> dict:
    """One chat turn.

    Returns {reply, category, blocked, reason, usage: {input, output, total}}
      category: app | study | other | unsafe | invalid
      usage:    tokens this turn really used (add usage.total to the user's daily total)
    """
    message = (message or "").strip()
    subject = (subject or "")[: config.MAX_SUBJECT_CHARS]
    material = (material_text or "")[: config.MAX_MATERIAL_CHARS]
    turns = clean_history(history)

    if not message:
        return _result(REPLIES["empty"], "invalid", True, "empty")
    if len(message) > config.MAX_MESSAGE_CHARS:
        return _result(REPLIES["too_long"], "invalid", True, "too_long")

    contents = [
        {"role": "user" if t["role"] == "user" else "model", "parts": [{"text": t["text"]}]} for t in turns
    ]
    last = (f"<material>\n{material}\n</material>\n" if material else "") + f"<student_message>\n{message}\n</student_message>"
    contents.append({"role": "user", "parts": [{"text": last}]})

    r = llm.json(system_prompt(subject, bool(material)), contents, SCHEMA)

    category = "unsafe" if r.blocked else (r.data or {}).get("category")
    if category not in CATEGORIES:
        category = "other"  # unknown or unreadable output: fail closed

    if category in ("other", "unsafe"):
        # Never show the model's own text for these.
        reply = REPLIES["unsafe"] if category == "unsafe" else REPLIES["off_topic"]
        return _result(reply, category, True, r.reason if r.blocked else "filtered", r.usage)

    reply = ((r.data or {}).get("reply") or "").strip()
    if not reply:
        return _result(REPLIES["off_topic"], category, True, r.reason or "empty_answer", r.usage)

    return _result(reply, category, False, None, r.usage)
