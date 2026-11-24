"""Shared pytest setup. Tests use a fake LLM: no internet, no Gemini quota."""

import re

import pytest

from study_chatbot.gemini_client import LLMResult, Usage


class FakeLLM:
    """Classifies by keywords so the pipeline can be tested. It does NOT test how well Gemini
    classifies; that is what eval.py is for, with a real key."""

    def __init__(self, reply="إجابة تجريبية", blocked=False, data=None):
        self.calls = []
        self.reply = reply
        self.blocked = blocked
        self.data = data

    def json(self, system, contents, schema, temperature=0.4):
        self.calls.append({"system": system, "contents": contents})
        if self.blocked:
            return LLMResult(data=None, blocked=True, reason="SAFETY", usage=Usage(1000, 0, 1000))
        if self.data is not None:
            return LLMResult(data=self.data, blocked=False, reason="STOP", usage=Usage(2000, 100, 2100))
        msg = contents[-1]["parts"][0]["text"].split("<student_message>")[-1]
        category = "study"
        if re.search(r"قصيدة|نكتة|ignore|كورة", msg):
            category = "other"
        if re.search(r"أذي نفسي|انتحار", msg):
            category = "unsafe"
        if re.search(r"الجلسة|أبلكيشن|التليفون", msg):
            category = "app"
        reply = "model tried to answer anyway" if category == "other" else ("" if category == "unsafe" else self.reply)
        return LLMResult(data={"category": category, "reply": reply}, blocked=False, reason="STOP",
                         usage=Usage(2100, 150, 2250))


@pytest.fixture
def fake_llm():
    return FakeLLM()
