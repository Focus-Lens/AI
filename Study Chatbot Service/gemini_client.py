"""Thin Gemini wrapper. The rest of the service (and the tests) never touch the SDK directly."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from google import genai
from google.genai import errors, types

import config

# The users are children: sexual content is blocked at the strictest level. The others use the
# medium level, because the strictest one also blocked normal questions. Our own classifier
# still refuses anything "unsafe".
SAFETY = [
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                        threshold=types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE),
]

RETRYABLE = {429, 500, 503, 504}


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    total: int = 0


@dataclass
class LLMResult:
    data: dict | None
    blocked: bool
    reason: str
    usage: Usage = field(default_factory=Usage)


def is_daily_quota(err: Exception) -> bool:
    return getattr(err, "code", None) == 429 and bool(re.search(r"per day|PerDay", str(err), re.I))


def with_retry(fn: Callable[[], Any], delays=(2, 5, 10), sleep=time.sleep):
    """Retries busy/overloaded errors (429/5xx) with backoff. Not a bad key (400) or a used-up daily quota."""
    for attempt in range(len(delays) + 1):
        try:
            return fn()
        except errors.APIError as e:
            if e.code not in RETRYABLE or is_daily_quota(e) or attempt == len(delays):
                raise
            sleep(delays[attempt])


class GeminiLLM:
    def __init__(self, api_key: str, model: str = config.GEMINI_MODEL):
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.thinking = None if config.GEMINI_THINKING == "OFF" else config.GEMINI_THINKING

    def _config(self, system: str, schema: dict, temperature: float) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=schema,
            safety_settings=SAFETY,
            max_output_tokens=2048,
            thinking_config=types.ThinkingConfig(thinking_level=self.thinking) if self.thinking else None,
        )

    def json(self, system: str, contents: list[dict], schema: dict, temperature: float = 0.4) -> LLMResult:
        def call():
            return self.client.models.generate_content(
                model=self.model, contents=contents, config=self._config(system, schema, temperature))

        try:
            res = with_retry(call)
        except errors.APIError as e:
            # Model doesn't support this thinking setting: drop it and try once more.
            if self.thinking and e.code == 400 and "thinking" in str(e).lower():
                self.thinking = None
                res = with_retry(call)
            else:
                raise

        text = res.text or ""
        try:
            data = json.loads(text) if text else None
        except json.JSONDecodeError:
            data = None

        reason = "UNKNOWN"
        if res.prompt_feedback and res.prompt_feedback.block_reason:
            reason = str(res.prompt_feedback.block_reason)
        elif res.candidates and res.candidates[0].finish_reason:
            reason = str(res.candidates[0].finish_reason)

        u = res.usage_metadata
        usage = Usage()
        if u:
            usage.input = u.prompt_token_count or 0
            usage.output = (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
            usage.total = u.total_token_count or usage.input + usage.output

        return LLMResult(data=data, blocked=not text, reason=reason, usage=usage)
