"""Study sessions + RAG: the lecture is sent once, each question gets only the related parts."""

import pytest
from .conftest import FakeLLM
from fastapi.testclient import TestClient

from app import app
from redis_state import state_key
from study_chatbot import api
from study_chatbot import chat
from study_chatbot import config
from study_chatbot import retrieval
from study_chatbot import sessions

TOPICS = {
    1: "Photosynthesis happens in the chloroplast. Plants use sunlight, water and carbon dioxide to make glucose and oxygen.",
    2: "Mitosis is cell division that makes two identical daughter cells. Its phases are prophase, metaphase, anaphase and telophase.",
    3: "Meiosis makes four gametes with half the chromosomes. It happens in sex cells and creates genetic variation.",
    4: "The heart pumps blood through arteries and veins. The left ventricle pumps oxygenated blood to the body.",
    5: "Enzymes are proteins that speed up chemical reactions. Temperature and pH affect how enzymes work.",
}


def lecture(filler=1800):
    """A 5-page lecture with page markers, long enough that only part of it fits in one message."""
    return "\n".join(f"--- Page {p} ---\n{text}\n\n" + ("General review notes for the unit. " * (filler // 36))
                     for p, text in TOPICS.items())


def material_of(llm, call=-1):
    return llm.calls[call]["contents"][-1]["parts"][0]["text"]


# ---------------------------------------------------------------------------
# retrieval
# ---------------------------------------------------------------------------

def test_chunks_keep_page_numbers():
    chunks = retrieval.chunk_text(lecture())
    assert {c.page for c in chunks} == {1, 2, 3, 4, 5}
    assert all(len(c.text) <= config.CHUNK_CHARS for c in chunks)


def test_question_gets_the_matching_page_only():
    index = retrieval.LectureIndex(lecture())
    found = index.search("What are the phases of mitosis?")
    assert found[0].page == 2
    assert sum(len(c.text) for c in found) <= config.MATERIAL_BUDGET_CHARS


def test_arabic_search_ignores_hamza_tashkeel_and_al():
    text = ("--- Page 1 ---\nالبناء الضوئي يحدث في البلاستيدات الخضراء.\n\n" + "مراجعة عامة. " * 400 +
            "\n--- Page 2 ---\nالانقسام الميتوزي ينتج خليتين متطابقتين.\n\n" + "ملاحظات. " * 400)
    index = retrieval.LectureIndex(text)
    assert index.search("إشرحلي الإنقسام الميتوزى")[0].page == 2


def test_short_lecture_is_sent_whole():
    index = retrieval.LectureIndex("Mitosis makes two cells.")
    assert [c.text for c in index.search("anything")] == ["Mitosis makes two cells."]


def test_summary_question_spreads_over_the_whole_lecture():
    index = retrieval.LectureIndex(lecture())
    pages = {c.page for c in index.search("لخصلي المحاضرة كلها")}
    assert pages == {1, 2, 3, 4, 5}


def test_follow_up_uses_previous_question():
    index = retrieval.LectureIndex(lecture())
    found = index.search("وضحلي أكتر", previous_question="What is meiosis?")
    assert found[0].page == 3


# ---------------------------------------------------------------------------
# sessions in chat()
# ---------------------------------------------------------------------------

def test_session_then_question_sends_only_related_part():
    llm = FakeLLM()
    info = chat.start_session("s1", lecture(), subject="Biology", lesson_title="Cells", grade="Grade 10")
    assert info["session_id"] == "s1" and info["pages"] == 5 and info["chunks"] >= 5 and not info["truncated"]

    r = chat.chat("What does the heart pump?", llm, session_id="s1")
    assert r["blocked"] is False and r["pages"] == [4] and r["session_id"] == "s1"
    sent = material_of(llm)
    assert "left ventricle" in sent and "Photosynthesis" not in sent
    assert "Biology - Cells" in llm.calls[0]["system"] and "Grade 10" in llm.calls[0]["system"]


def test_tokens_per_message_dont_grow_with_lecture_length():
    llm = FakeLLM()
    chat.start_session("short", lecture(filler=1800))
    chat.start_session("long", lecture(filler=40_000))  # ~20x longer
    chat.chat("phases of mitosis", llm, session_id="short")
    chat.chat("phases of mitosis", llm, session_id="long")
    assert len(material_of(llm, -1)) < config.MATERIAL_BUDGET_CHARS + 500
    assert abs(len(material_of(llm, -1)) - len(material_of(llm, 0))) < 2000


def test_session_keeps_history_but_not_refused_messages():
    llm = FakeLLM()
    chat.start_session("s1", lecture())
    chat.chat("What is mitosis?", llm, session_id="s1")
    chat.chat("اكتبلي قصيدة", llm, session_id="s1")  # refused: not kept
    chat.chat("and meiosis?", llm, session_id="s1")
    history = llm.calls[-1]["contents"][:-1]
    assert [h["parts"][0]["text"] for h in history] == ["What is mitosis?", "إجابة تجريبية"]
    assert len(sessions.store.get("s1").history) == 4


def test_unknown_session_without_text_raises():
    with pytest.raises(chat.SessionNotFound):
        chat.chat("hi", FakeLLM(), session_id="gone")


def test_unknown_session_with_text_is_rebuilt():
    llm = FakeLLM()
    r = chat.chat("phases of mitosis", llm, session_id="gone", material_text=lecture())
    assert r["session_renewed"] is True and r["pages"] == [2]
    assert sessions.store.get("gone") is not None


def test_expired_session_is_forgotten(redis_client):
    chat.start_session("s1", lecture())
    redis_client.expire(state_key("chat", "s1"), 0)
    assert sessions.store.get("s1") is None


def test_read_renews_session_ttl(redis_client):
    store = sessions.SessionStore(ttl_seconds=60)
    chat.start_session("s1", "text", store=store)
    key = state_key("chat", "s1")
    assert 55 <= redis_client.ttl(key) <= 60
    redis_client.expire(key, 5)
    assert store.get("s1") is not None
    assert 55 <= redis_client.ttl(key) <= 60


def test_overlapping_turns_append_to_latest_history():
    store = sessions.store
    chat.start_session("s1", "text")
    first = store.get("s1")
    second = store.get("s1")
    store.add_turn(first, "Question 1", "Answer 1", [0])
    store.add_turn(second, "Question 2", "Answer 2", [0])
    assert [m["text"] for m in store.get("s1").history] == [
        "Question 1", "Answer 1", "Question 2", "Answer 2",
    ]


@pytest.mark.parametrize("restart", [False, True])
def test_in_flight_turn_cannot_restore_old_session(restart):
    store = sessions.store
    chat.start_session("s1", "old lecture")
    previous = store.get("s1")
    assert store.end("s1")
    if restart:
        chat.start_session("s1", "new lecture")

    store.add_turn(previous, "Old question", "Old answer", [0])
    current = store.get("s1")
    if restart:
        assert current.index.text == "new lecture" and current.history == []
    else:
        assert current is None


def test_long_lecture_is_cut_and_reported(monkeypatch):
    monkeypatch.setattr(config, "MAX_LECTURE_CHARS", 1000)
    info = chat.start_session("s1", "x " * 2000)
    assert info["truncated"] is True and info["chars"] <= 1000


# ---------------------------------------------------------------------------
# API: the two endpoints the backend uses
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    fake = FakeLLM()
    app.dependency_overrides[api.get_llm] = lambda: fake
    yield TestClient(app), fake
    app.dependency_overrides.clear()


def test_api_session_then_message(client):
    c, fake = client
    res = c.post("/chat/session", json={
        "session_id": "study-42", "material_text": lecture(), "subject": "Biology",
        "lesson_title": "Cells", "student": {"grade": "Grade 10", "name": "ignored"}})
    assert res.status_code == 200
    assert res.json()["pages"] == 5
    assert fake.calls == [], "starting a session costs no AI call"

    res = c.post("/chat/message", json={"session_id": "study-42", "message": "What are enzymes?"})
    body = res.json()
    assert res.status_code == 200 and body["pages"] == [5] and body["usage"]["total"] == 2250
    assert "ignored" not in str(fake.calls), "student name never reaches the model"


def test_api_unknown_session_is_409(client):
    c, _ = client
    res = c.post("/chat/message", json={"session_id": "nope", "message": "hi"})
    assert res.status_code == 409 and "session_not_found" in res.json()["detail"]


def test_api_end_session(client):
    c, _ = client
    c.post("/chat/session", json={"session_id": "s1", "material_text": "text"})
    assert c.post("/chat/session/end", json={"session_id": "s1"}).json() == {"ended": True}
    assert c.post("/chat/message", json={"session_id": "s1", "message": "hi"}).status_code == 409


def test_api_session_needs_id(client):
    c, _ = client
    assert c.post("/chat/session", json={"material_text": "text"}).status_code == 422
