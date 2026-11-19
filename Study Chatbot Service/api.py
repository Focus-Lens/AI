"""
Study Chatbot Service — HTTP API.

  GET  /health
  GET  /chat/welcome   — fixed welcome message for the chat screen
  POST /chat/message   — one chat turn (needs X-Service-Key)

Run locally:
    uvicorn api:app --reload --port 8001

Interactive docs:
    http://localhost:8001/docs
"""

import hmac
import os
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, status
from google.genai import errors
from pydantic import BaseModel, Field

import chat as chat_logic
from gemini_client import GeminiLLM
from prompts import REPLIES

# ---------------------------------------------------------------------------
# Service-to-service auth (same pattern as the AI 1 behavioral service):
# the .NET backend sends the shared secret in X-Service-Key.
# ---------------------------------------------------------------------------

if os.environ.get("CHAT_AUTH_DISABLED", "false").lower() != "true" and not os.environ.get("CHAT_SERVICE_KEY"):
    print("WARNING: CHAT_SERVICE_KEY is not set. Set it to a shared secret the .NET backend will also send, "
          "or set CHAT_AUTH_DISABLED=true for local testing only.")


def require_service_key(x_service_key: str | None = Header(default=None, alias="X-Service-Key")) -> None:
    if os.environ.get("CHAT_AUTH_DISABLED", "false").lower() == "true":
        return
    service_key = os.environ.get("CHAT_SERVICE_KEY")
    if not service_key:
        raise HTTPException(status_code=500, detail="CHAT_SERVICE_KEY not configured")
    if x_service_key is None or not hmac.compare_digest(x_service_key.encode("utf-8"), service_key.encode("utf-8")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Service-Key")


@lru_cache(maxsize=1)
def get_llm():
    """Created once per process. Tests override this dependency with a fake."""
    return GeminiLLM(os.environ.get("GEMINI_API_KEY", ""))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ChatTurn(BaseModel):
    role: str = Field(description="'user' or 'assistant'")
    text: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = Field(default_factory=list, description="Previous turns (optional)")
    subject: str = Field(default="", description="Subject of the current session, e.g. 'Biology' (optional)")
    material_text: str = Field(default="", description="Text of the section being studied (optional)")


class ChatUsage(BaseModel):
    input: int
    output: int
    total: int


class ChatResponse(BaseModel):
    reply: str
    category: str = Field(description="app | study | other | unsafe | invalid")
    blocked: bool = Field(description="true when the student got a fixed reply instead of an AI answer")
    reason: str | None = None
    usage: ChatUsage


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app = FastAPI(title="FocusLens Study Chatbot Service", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/chat/welcome")
def welcome():
    return {"reply": REPLIES["welcome"]}


@app.post("/chat/message", response_model=ChatResponse, dependencies=[Depends(require_service_key)])
def chat_message(req: ChatRequest, llm=Depends(get_llm)):
    try:
        return chat_logic.chat(
            req.message,
            llm,
            history=[t.model_dump() for t in req.history],
            subject=req.subject,
            material_text=req.material_text,
        )
    except errors.APIError as e:
        if e.code == 429:
            raise HTTPException(status_code=429, detail="Gemini quota or rate limit reached. Try again later.")
        raise HTTPException(status_code=502, detail=f"Gemini error {e.code}")
