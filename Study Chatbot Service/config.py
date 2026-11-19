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
MAX_MATERIAL_CHARS = 12_000
MAX_SUBJECT_CHARS = 60
MAX_HISTORY_TURNS = 6  # previous messages sent back to the model for context
