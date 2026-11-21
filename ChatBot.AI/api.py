"""
Study Chatbot Service — HTTP API.

  GET  /health
  GET  /chat/welcome       — fixed welcome message for the chat screen
  POST /chat/session       — start a study session: send the lecture text ONCE
  POST /chat/message       — the student's question -> reply
  POST /chat/session/end   — forget the session early (optional)
  (all POST routes need X-Service-Key)

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

class StudentInfo(BaseModel):
    grade: str = Field(default="", description="School year, e.g. 'Grade 10' / 'تانية ثانوي' (optional). "
                       "Don't send names or other personal data; they are not needed.")


class SessionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100, description="Your study session id")
    material_text: str = Field(description="Full lecture text. Page markers like '--- Page 3 ---' are used if present")
    subject: str = Field(default="", description="e.g. 'Biology' (optional)")
    lesson_title: str = Field(default="", description="e.g. 'Cell division' (optional)")
    student: StudentInfo = Field(default_factory=StudentInfo)


class SessionResponse(BaseModel):
    session_id: str
    chunks: int = Field(description="Searchable parts the lecture was split into")
    chars: int
    pages: int = Field(description="Pages found from page markers (0 if none)")
    truncated: bool = Field(description="true if the lecture was longer than the limit and was cut")
    expires_at: str = Field(description="Forgotten after this if no question is asked; each question extends it")


class ChatTurn(BaseModel):
    role: str = Field(description="'user' or 'assistant'")
    text: str


class ChatRequest(BaseModel):
    message: str
    session_id: str = Field(default="", description="From POST /chat/session (optional: without it, general chat)")
    history: list[ChatTurn] = Field(default_factory=list, description="Optional. Normally not needed: "
                                    "the session keeps its own history")
    material_text: str = Field(default="", description="Optional. Only to rebuild an expired session "
                               "automatically instead of getting 409")
    subject: str = Field(default="", description="Optional, only used without a session")


class ChatUsage(BaseModel):
    input: int
    output: int
    total: int


class ChatResponse(BaseModel):
    reply: str
    category: str = Field(description="app | study | other | unsafe | invalid")
    blocked: bool = Field(description="true when the student got a fixed reply instead of an AI answer")
    reason: str | None = None
    session_id: str | None = None
    session_renewed: bool = Field(default=False, description="true when an expired session was rebuilt "
                                  "from material_text (its history started over)")
    pages: list[int] = Field(default_factory=list, description="Lecture pages (or parts) the answer used")
    usage: ChatUsage


class EndSessionRequest(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app = FastAPI(title="FocusLens Study Chatbot Service", version="2.0.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/chat/welcome")
def welcome():
    return {"reply": REPLIES["welcome"]}


@app.post("/chat/session", response_model=SessionResponse, dependencies=[Depends(require_service_key)])
def chat_session(req: SessionRequest):
    return chat_logic.start_session(req.session_id, req.material_text, subject=req.subject,
                                    lesson_title=req.lesson_title, grade=req.student.grade)


@app.post("/chat/session/end", dependencies=[Depends(require_service_key)])
def chat_session_end(req: EndSessionRequest):
    return {"ended": chat_logic.end_session(req.session_id)}


@app.post("/chat/message", response_model=ChatResponse, dependencies=[Depends(require_service_key)])
def chat_message(req: ChatRequest, llm=Depends(get_llm)):
    try:
        return chat_logic.chat(
            req.message,
            llm,
            session_id=req.session_id,
            history=[t.model_dump() for t in req.history],
            subject=req.subject,
            material_text=req.material_text,
        )
    except chat_logic.SessionNotFound:
        raise HTTPException(status_code=409, detail="session_not_found: call POST /chat/session again, then resend")
    except errors.APIError as e:
        if e.code == 429:
            raise HTTPException(status_code=429, detail="Gemini quota or rate limit reached. Try again later.")
        raise HTTPException(status_code=502, detail=f"Gemini error {e.code}")
