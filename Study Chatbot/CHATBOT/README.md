# FocusLens Study Chatbot

A standalone FastAPI service for study questions and attachment OCR. It uses Gemini to answer in the language of the latest question and Redis to share study sessions across app instances.

## Deployment settings

In Vercel, import this repository and select its root directory. The root `app.py` contains the FastAPI entry point. Add the following settings to the project's Environment Variables and redeploy. [Vercel FastAPI deployment](https://vercel.com/docs/frameworks/backend/fastapi), [Vercel environment variables](https://vercel.com/docs/environment-variables).

| Variable | Value |
| --- | --- |
| `GEMINI_API_KEY` | The Gemini API key for this deployment |
| `CHAT_SERVICE_KEY` | The shared secret that the .NET backend sends in `X-Service-Key` |
| `REDIS_URL` | Native Redis connection URL from the provider. Use `rediss://` when TLS is required |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` by default |
| `GEMINI_THINKING` | `LOW` by default |
| `CHAT_SESSION_TTL_SECONDS` | `10800` by default. Each session access resets the three-hour TTL |
| `REDIS_KEY_PREFIX` | `focuslens` by default. Use distinct prefixes for separate environments |

Commit the example settings file. Enter actual secrets in Vercel or a local `.env` ignored by Git. If this deployment replaces the unified service and should continue its active chat sessions, point it at the same Redis database and key prefix. [Redis connection configuration](https://upstash.com/docs/redis/howto/connect-client).

## .NET integration

Set the backend's chatbot base URL to this deployment. Include `X-Service-Key` with the value of `CHAT_SERVICE_KEY` on each secured request.

| Route | Request or use | Auth |
| --- | --- | --- |
| `GET /health` | Liveness check | Public |
| `GET /chat/welcome` | Default welcome message | Public |
| `POST /chat/session` | Send `session_id`, extracted `material_text`, and optionally `subject`, `lesson_title` and `student.grade` | Service key |
| `POST /chat/message` | Send `message` with the study `session_id` | Service key |
| `POST /chat/session/end` | Send `session_id` to delete its stored state | Service key |
| `POST /ocr` | Send `mime_type` and base64 `data` for PNG, JPEG or PDF | Service key |

Send the lecture once when the study session starts. Redis keeps its index and recent history. Each question retrieves relevant lecture passages and returns `reply`, `pages` and `usage`. The .NET backend adds `usage.total` to the student's usage.

If a session is missing or expires, `/chat/message` returns `409` with `session_not_found`. Reopen it with `/chat/session` using the same session ID and lecture, or include `material_text` in the question to rebuild the session.

For a file attached outside a session, call `/ocr` first. Pass the resulting `text` as `material_text` to `/chat/message` with the student's question. On Vercel, keep the original file at about 3 MiB or smaller to allow for base64 and JSON overhead. [Vercel request body limit](https://vercel.com/docs/functions/limitations#request-body-size).

## Run locally

Use Python 3.13 and a running Redis instance. From the project root, create a virtual environment and a local settings file.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
```

Fill in `GEMINI_API_KEY`, `CHAT_SERVICE_KEY` and the appropriate `REDIS_URL` in `.env`. Start FastAPI and open [Swagger UI](http://localhost:8000/docs).

```powershell
.\.venv\Scripts\python.exe -m uvicorn app:app --port 8000
```

If a request returns `503` with `gemini_api_key_not_configured`, check the deployment's `GEMINI_API_KEY`. For `503` with `redis_storage_unavailable`, check `REDIS_URL` and the Redis connection. A `429` with the Gemini quota message points to the Gemini project's rate limits. [Gemini rate limits](https://aistudio.google.com/docs/rate-limits).

## Tests

The pytest suite uses a simulated Gemini client and a Redis emulator.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```
