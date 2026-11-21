"""Settings, read from environment variables or a local .env file (never commit .env)."""

import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional in production
    pass

# Gemini model id from AI Studio. Free tier of gemini-3.5-flash-lite: 15 requests/min, 500/day per project.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Thinking models spend output tokens "thinking" before answering. LOW keeps replies fast and cheap.
# MINIMAL | LOW | MEDIUM | HIGH | OFF
GEMINI_THINKING = os.environ.get("GEMINI_THINKING", "LOW").upper()

MAX_MESSAGE_CHARS = 500
MAX_SUBJECT_CHARS = 60
MAX_HISTORY_TURNS = 6  # previous messages sent back to the model for context

# Lecture text per session. Only the parts related to each question are sent to Gemini (RAG),
# so a long lecture does not make each message more expensive.
MAX_LECTURE_CHARS = int(os.environ.get("CHAT_MAX_LECTURE_CHARS", 600_000))  # ~250 pages
CHUNK_CHARS = 1_000             # size of one searchable part of the lecture
MAX_CHUNKS = 5                  # parts sent with a normal question
MATERIAL_BUDGET_CHARS = 5_000   # max lecture characters sent with a normal question (~1,250 tokens)
OVERVIEW_BUDGET_CHARS = 12_000  # "summarize the lecture" questions get a wider spread

# Sessions are kept in memory. Each question keeps its session alive for this long.
SESSION_TTL_SECONDS = int(os.environ.get("CHAT_SESSION_TTL_SECONDS", 3 * 60 * 60))
MAX_SESSIONS = int(os.environ.get("CHAT_MAX_SESSIONS", 2_000))
