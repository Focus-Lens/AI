"""FastAPI entry point for FocusLens Study Chatbot."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from study_chatbot.api import router as chat_router
from redis_state import RedisNotConfigured

app = FastAPI(title="FocusLens Study Chatbot", version="1.0.0")
app.include_router(chat_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.exception_handler(RedisNotConfigured)
@app.exception_handler(RedisError)
async def redis_unavailable(_request, _error):
    return JSONResponse(status_code=503, content={"detail": "redis_storage_unavailable"})
