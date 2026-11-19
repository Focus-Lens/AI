# Study Chatbot Service

FocusLens study assistant. Answers **school-learning questions (any subject)** and **questions about using FocusLens**, in simple Egyptian Arabic. Anything else gets a fixed reply.

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

# 4. Run
uvicorn api:app --reload --port 8001

# 5. API docs
#    http://localhost:8001/docs
```

Tests (fake model, no internet, no quota):

```bash
python -m pytest -q
```

Check the filter against the real Gemini **before every demo** (20 cases, or fewer with `--limit`):

```bash
python eval.py --limit 6
```

---

## 2. API

### `GET /health`
`{"status": "ok"}`

### `GET /chat/welcome`
Fixed welcome message for the chat screen (no AI call, no cost).

### `POST /chat/message`  (header `X-Service-Key`)

Request:
```json
{
  "message": "اشرحلي الانقسام الميتوزي",
  "history": [
    { "role": "user", "text": "..." },
    { "role": "assistant", "text": "..." }
  ],
  "subject": "Biology",
  "material_text": "text of the section being studied"
}
```
Only `message` is required. `history` = previous turns (only the last 6 user/assistant turns are used).

Response:
```json
{
  "reply": "...",
  "category": "study",
  "blocked": false,
  "reason": null,
  "usage": { "input": 1150, "output": 160, "total": 1310 }
}
```

| Field | Meaning |
|---|---|
| `category` | `app` / `study` / `other` / `unsafe` / `invalid` |
| `blocked` | `true` when the student got a fixed reply instead of an AI answer |
| `reason` | Why it was blocked: `filtered`, `empty`, `too_long`, `SAFETY`, ... |
| `usage.total` | Tokens this message used. **Add it to the user's daily total** |

Errors: `401` bad/missing `X-Service-Key` · `422` invalid body · `429` Gemini quota/rate limit · `502` other Gemini error.

---

## 3. How it works

```
Backend --> POST /chat/message --> validate --> ONE Gemini request --> {category, reply}
                                                                     |
                               category app/study --> AI reply ------+
                               category other/unsafe --> fixed reply (model text discarded)
```

- **One request per message.** Gemini returns JSON (`category` + `reply`, enforced by a response schema). The code decides what the student sees; for `other`/`unsafe` the model's text is never shown.
- **The bot knows the app from `knowledge/focuslens.md`.** No fine-tuning: edit that file and the bot knows the change immediately.
- **Prompt injection:** student text, history and material are sent inside tags as data, not instructions, so "ignore your rules" attempts don't work.
- **Fail closed:** unknown category, broken JSON or an empty answer → fixed reply.
- **Safety settings:** sexual content blocked at the strictest level, other harm categories at medium (the strictest level also blocked normal questions).
- **Retries:** 429/5xx are retried with backoff (2s, 5s, 10s), except a used-up daily quota or a bad key.
- **Thinking level:** `LOW` (fast and cheap). Change with `GEMINI_THINKING`.

### Project structure

```
Study Chatbot Service
├── api.py              FastAPI app, auth, routes
├── app.py              Vercel entrypoint
├── chat.py             chat logic (validation, decision, usage)
├── gemini_client.py    Gemini SDK wrapper (safety, thinking, retries, usage)
├── prompts.py          bot rules + fixed replies
├── config.py           settings from env / .env
├── knowledge/
│   └── focuslens.md    everything the bot knows about FocusLens
├── eval.py             real-Gemini filter check
└── tests/              pytest (fake model) + eval_cases.json
```

---

## 4. For the backend

| Item | What to do |
|---|---|
| **Call** | `POST /chat/message` with `X-Service-Key: <CHAT_SERVICE_KEY>` |
| **Daily tokens** | After each call, add `usage.total` to the user's total for today (Cairo time) |
| **Before a call** | If the user's balance is used up, return the "limit reached" reply yourself and don't call the service |
| **Plans** | Daily limits per plan (Free / Plus / Family) live in the backend |
| **Rate limit** | Messages per minute per user live in the backend |
| **History** | Append the message and reply to the history only when `blocked` is `false` |
| **Logging** | For refused messages, log `category` only, not the message text |
| **429 from this service** | Gemini quota hit; show the student "try again later" |

**Sizing:** ~**1,300 tokens per message** today (`eval.py` prints the current average). Daily token limit per plan = questions per day × that average.

---

## 5. Model and limits

- `gemini-3.5-flash-lite` free tier: **15 requests/minute, 500 requests/day for the whole Google project** (not per user). Check current limits at aistudio.google.com/rate-limit.
- We moved from `gemini-4-hydrogen` because its free tier is only **20 requests/day**.
- The .NET learning-AI service uses the same model. **If both use the same Google project, they share the same 500/day.**
- The free tier is fine for development and demos. **Use the paid tier before launch**, also because Google may use free-tier data to improve its products and our users are children.

## 6. Last results

- Unit tests: **22/22** passing.
- `eval.py` on real Gemini: **20/20** correct, ~1,316 tokens per message.
