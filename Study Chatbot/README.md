# Study Chatbot Service

FocusLens study assistant. Answers **school-learning questions (any subject)** and **questions about using FocusLens**. Replies follow the language of the latest question each turn, in clear English or simple Egyptian Arabic. Anything else gets a fixed reply.

The backend sends the **lecture text once per study session**. For each question, the service finds the parts of the lecture related to it (RAG) and sends only those to Gemini, so **tokens per message stay about the same whether the lecture is 2 pages or 200**.

Built with **FastAPI** and **Gemini** (`gemini-3.5-flash-lite`). Same service-to-service auth pattern as the AI 1 behavioral service (`X-Service-Key`).

---

## 1. Quick Start

```bash
cd "Study Chatbot Service"

# 1. Virtual environment
python -m venv venv
source venv/bin/activate      # on Windows: venv\Scripts\activate

# 2. Dependencies
pip install -r requirements.txt

# 3. Settings: copy .env.example to .env and fill it in (never commit .env)
#    GEMINI_API_KEY   key from aistudio.google.com -> API keys
#    CHAT_SERVICE_KEY shared secret; the .NET backend sends the same value
#    For local testing without the backend you can set CHAT_AUTH_DISABLED=true

# 4. Run (ONE worker: sessions live in this process's memory)
uvicorn api:app --port 8001 --workers 1

# 5. API docs
#    http://localhost:8001/docs
```

Tests (fake model, no internet, no quota):

```bash
python -m pytest -q
```

Checks against the real Gemini, **before every demo**:

```bash
python eval.py --limit 6     # the filter: 3 allowed + 3 blocked questions
python eval_session.py       # a study session: right page used for 3 questions
```

---

## 2. API — the backend uses two endpoints

### ① `POST /chat/session` — when the study session starts (header `X-Service-Key`)

Send the lecture text once. **No AI call, no tokens.**

```json
{
  "session_id": "study-session-42",
  "material_text": "--- Page 1 ---\n...\n--- Page 2 ---\n...",
  "subject": "Biology",
  "lesson_title": "Cell division",
  "student": { "grade": "Grade 10" }
}
```

| Field | |
|---|---|
| `session_id` | **Required.** Your own study-session id (any string up to 100 chars) |
| `material_text` | **Required.** The full extracted lecture text. If it has page markers (`--- Page 3 ---`, `Page 3`, `صفحة 3` on their own line), answers can point to the page |
| `subject`, `lesson_title` | Optional |
| `student.grade` | Optional. The explanation level follows it. **Don't send names or other personal data** (they are ignored) |

Response:
```json
{ "session_id": "study-session-42", "chunks": 38, "chars": 36500, "pages": 12,
  "truncated": false, "expires_at": "2026-11-21T15:00:00+00:00" }
```

Calling it again with the same `session_id` replaces the lecture and starts the history over.

### ② `POST /chat/message` — every student question (header `X-Service-Key`)

```json
{ "session_id": "study-session-42", "message": "إيه مراحل الانقسام الميتوزي؟" }
```

Response:
```json
{
  "reply": "...",
  "category": "study",
  "blocked": false,
  "reason": null,
  "session_id": "study-session-42",
  "session_renewed": false,
  "pages": [4],
  "usage": { "input": 2400, "output": 180, "total": 2580 }
}
```

| Field | Meaning |
|---|---|
| `category` | `app` / `study` / `other` / `unsafe` / `invalid` |
| `blocked` | `true` when the student got a fixed reply instead of an AI answer |
| `reason` | Why it was blocked: `filtered`, `empty`, `too_long`, `SAFETY`, ... |
| `pages` | Lecture pages the answer was based on (parts, if the text has no page markers) |
| `usage.total` | Tokens this message used. **Add it to the user's daily total** |

**The history is kept by the service**, per session (last 6 turns, refused messages not kept). The backend doesn't need to send it.

**Session not found → `409`** (expired after 3 hours without questions, ended, or the service restarted).
The backend calls `POST /chat/session` again with the same `session_id` and text, then resends the question.
Or, to skip the extra call: send `material_text` in the message request too, and the service rebuilds the session itself (`session_renewed: true`).

Without `session_id`, `/chat/message` works as a general study chat with no lecture.

### Others
- `POST /ocr` — extract attachment text before chat. Send `X-Service-Key` and JSON
  `{"mime_type":"image/png","data":"<raw base64>"}`. Accepts PNG, JPEG, and PDF up
  to 5 MiB. Returns `{"text":"..."}` (empty string if no readable text).
  Gemini reads the attachment independently of chat sessions. Visible tables
  are transcribed as Markdown tables with cell positions and chemical bonds
  preserved where readable. Unreadable entries are marked `[illegible]`.
  Pass the extracted text as `material_text` with a question to
  `POST /chat/message` for a single turn, or use it when starting a study
  session. The endpoint does not store the attachment.
- `POST /chat/session/end` `{ "session_id": "..." }` — when the study session ends (optional; it expires by itself).
- `GET /chat/welcome` — fixed welcome message for the chat screen (no AI call).
- `GET /health` — `{"status": "ok"}`

Errors: `401` bad/missing `X-Service-Key` · `409` session not found · `422` invalid body · `429` Gemini quota/rate limit · `502` other Gemini error.

---

## 3. How it works

```
POST /chat/session  --> split the lecture into ~1,000-char parts (keeps page numbers) --> kept in memory

POST /chat/message  --> validate --> find the related parts (BM25 keyword search, Arabic + English, no API call)
                    --> ONE Gemini request: rules + app knowledge + related parts + history + question
                    --> {category, reply}
                          app/study    --> AI reply
                          other/unsafe --> fixed reply (model text discarded)
```

- **RAG:** a normal question gets up to 5 related parts (max 5,000 characters, ~1,250 tokens). Follow-ups like "وضحلي أكتر" also search with the previous question. "لخصلي المحاضرة" questions get parts spread over the whole lecture (max 12,000 characters). A lecture shorter than 5,000 characters is sent whole.
- **Arabic search** ignores tashkeel, hamza forms (أ/إ/ا), ة/ه, ى/ي and "ال", so "الإنقسام" finds "انقسام".
- **One request per message.** Gemini returns JSON (`category` + `reply`, enforced by a response schema). The code decides what the student sees; for `other`/`unsafe` the model's text is never shown.
- **The bot knows the app from `knowledge/focuslens.md`.** Edit that file and the bot knows the change immediately.
- **Prompt injection:** student text, history and lecture are sent inside tags as data, not instructions.
- **Fail closed:** unknown category, broken JSON or an empty answer → fixed reply.
- **Safety settings:** sexual content blocked at the strictest level, other harm categories at medium.
- **Retries:** 429/5xx are retried with backoff (2s, 5s, 10s), except a used-up daily quota or a bad key.

### Limits

| | |
|---|---|
| Lecture per session | 600,000 characters (~250 pages); longer is cut and `truncated: true` |
| Question | 500 characters |
| Session lifetime | 3 hours after the last question (`CHAT_SESSION_TTL_SECONDS`) |
| Sessions in memory | 2,000 (the least recently used is dropped first) |

### Project structure

```
Study Chatbot Service
├── api.py              FastAPI app, auth, routes
├── chat.py             chat logic (sessions, validation, decision, usage)
├── retrieval.py        lecture splitting + search (RAG)
├── sessions.py         in-memory study sessions
├── gemini_client.py    Gemini SDK wrapper (safety, thinking, retries, usage)
├── prompts.py          bot rules + fixed replies
├── config.py           settings from env / .env
├── knowledge/
│   └── focuslens.md    everything the bot knows about FocusLens
├── eval.py             real-Gemini filter check
├── eval_session.py     real-Gemini study-session check
└── tests/              pytest (fake model) + eval_cases.json
```

---

## 4. For the backend

| Item | What to do |
|---|---|
| **Session start** | After the lecture text is extracted: `POST /chat/session` with your session id |
| **Each question** | `POST /chat/message` with `session_id` + `message` |
| **409** | Call `/chat/session` again with the same id and text, then resend the question |
| **Daily tokens** | After each message, add `usage.total` to the user's total for today (Cairo time) |
| **Before a call** | If the user's balance is used up, return the "limit reached" reply yourself and don't call the service |
| **Plans / rate limit** | Daily limits per plan and messages per minute live in the backend |
| **Logging** | For refused messages, log `category` only, not the message text |
| **429 from this service** | Gemini quota hit; show the student "try again later" |

**Sizing:** about **2,500 tokens per message** with a lecture, about 1,300 without, and it does not grow with the lecture length.

---

## 5. Deployment notes

- Run **one worker** (`--workers 1`). Sessions are in memory, so a second worker would not see them. One worker is enough here: the slow part is waiting for Gemini, and FastAPI handles that concurrently.
- A restart forgets all sessions. That is fine: the backend gets `409` and sends the lecture again.
- If we ever need several instances, move `sessions.py` to Redis; nothing else changes.

## 6. Model and limits

- `gemini-3.5-flash-lite` free tier: **15 requests/minute, 500 requests/day for the whole Google project** (not per user). Check current limits at aistudio.google.com/rate-limit.
- The free tier is fine for development and demos. **Enable billing before launch**: the free daily limit isn't enough for real users, and Google may use free-tier data to improve its products, while our users are children. Billing is pay-as-you-go, no subscription.
- No context caching needed: RAG keeps every message small on any plan and any model.

## 7. Last results

- Unit tests: **40/40** passing.
- `eval.py` on real Gemini: **20/20** correct.
