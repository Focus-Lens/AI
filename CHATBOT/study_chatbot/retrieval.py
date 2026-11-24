"""Finds the parts of the lecture that matter for a question (RAG without any extra API call).

The lecture text is split into small chunks once, when the session starts. For each question we
score the chunks with BM25 (classic keyword search, Arabic + English) and send Gemini only the
best ones. So the tokens per message stay about the same whether the lecture is 2 pages or 100.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from . import config

# ---------------------------------------------------------------------------
# Text normalization (Arabic + English)
# ---------------------------------------------------------------------------

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")  # harakat + tatweel
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_WORD = re.compile(r"[a-z0-9]+|[ء-ي]+")

_STOPWORDS = set("""
the a an of to in on at for and or is are was were be been it this that these those with as by from
what why how when where which who does do did can could explain me please about my i you
في من على عن الى إلى ان أن إن او أو و ثم هو هي هم دي ده دا اللي التي الذي الذين ما ماذا ليه لماذا
ازاي إزاي كيف ايه إيه يعني عايز عاوز ممكن اشرح اشرحلي اشرح لي قولي قول لي فهمني مش فاهم بتاع بتاعة
كان كانت يكون مع كل بس لو هل انا أنا انت إنت عند لما
""".split())

_PREFIXES = ("وال", "بال", "كال", "فال", "لل", "ال")
_SUFFIXES = ("ات", "ون", "ين", "ها", "هم", "ية", "يه", "ه", "ي")


def normalize(text: str) -> str:
    text = _DIACRITICS.sub("", text.lower()).translate(_ARABIC_DIGITS)
    text = re.sub("[إأآٱ]", "ا", text)
    return text.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")


def _stem(word: str) -> str:
    """Light stemming so الخلية / خلية / الخلايا-like forms meet more often."""
    if not word.isascii():
        for p in _PREFIXES:
            if word.startswith(p) and len(word) - len(p) >= 2:
                word = word[len(p):]
                break
        for s in _SUFFIXES:
            if word.endswith(s) and len(word) - len(s) >= 3:
                word = word[: -len(s)]
                break
    elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    return word


_AR_LETTER = re.compile(r"[ء-ي]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")


def arabic_share(text: str) -> float | None:
    """Share of Arabic letters among Arabic + Latin letters (None when there are no letters)."""
    ar = len(_AR_LETTER.findall(text))
    latin = len(_LATIN_LETTER.findall(text))
    return ar / (ar + latin) if ar + latin else None


def tokenize(text: str) -> list[str]:
    words = _WORD.findall(normalize(text))
    stop = {normalize(w) for w in _STOPWORDS}
    return [_stem(w) for w in words if w not in stop and len(w) > 1]


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

# "--- Page 5 ---", "Page 5", "صفحة 5", "[Page 5]" at the start of a line
_PAGE = re.compile(r"^\s*[\[\-=\s]*(?:page|صفحه|صفحة)\s*(\d+)\s*[\]\-=\s]*$", re.I | re.M)


@dataclass
class Chunk:
    id: int
    text: str
    page: int | None = None
    terms: Counter = field(default_factory=Counter)


def _split_long(paragraph: str, size: int) -> list[str]:
    """A paragraph longer than `size`: split on sentence ends, then hard-cut if needed."""
    parts, cur = [], ""
    for sentence in re.split(r"(?<=[.!?؟\n])\s+", paragraph):
        while len(sentence) > size:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(sentence[:size])
            sentence = sentence[size:]
        if len(cur) + len(sentence) + 1 > size and cur:
            parts.append(cur)
            cur = sentence
        else:
            cur = f"{cur} {sentence}".strip()
    if cur:
        parts.append(cur)
    return parts


def chunk_text(text: str, size: int = config.CHUNK_CHARS) -> list[Chunk]:
    """Split by page markers and paragraphs, then pack paragraphs into chunks of ~size characters."""
    pages: list[tuple[int | None, str]] = []
    last, page = 0, None
    for m in _PAGE.finditer(text):
        if text[last:m.start()].strip():
            pages.append((page, text[last:m.start()]))
        page, last = int(m.group(1)), m.end()
    if text[last:].strip():
        pages.append((page, text[last:]))

    chunks: list[Chunk] = []
    for page, body in pages:
        cur = ""
        for para in re.split(r"\n\s*\n", body):
            para = re.sub(r"[ \t]+", " ", para).strip()
            if not para:
                continue
            for piece in (_split_long(para, size) if len(para) > size else [para]):
                if cur and len(cur) + len(piece) + 2 > size:
                    chunks.append(Chunk(len(chunks), cur, page))
                    cur = piece
                else:
                    cur = f"{cur}\n\n{piece}" if cur else piece
        if cur:
            chunks.append(Chunk(len(chunks), cur, page))

    for c in chunks:
        c.terms = Counter(tokenize(c.text))
    return chunks


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

_OVERVIEW = re.compile(
    r"لخص|ملخص|تلخيص|الدرس كله|المحاضره كلها|المحاضرة كلها|الملف كله|الشابتر كله|الفصل كله|اهم النقاط|أهم النقاط|"
    r"اهم الافكار|أهم الأفكار|summar|overview|main points|key points|whole (lesson|lecture|chapter)", re.I)


def is_overview(question: str) -> bool:
    return bool(_OVERVIEW.search(question))


class LectureIndex:
    """BM25 over the chunks of one lecture."""

    K1, B = 1.5, 0.75

    def __init__(self, text: str, *, chunks: list[Chunk] | None = None):
        self.text = text
        self.truncated = False  # set by the session when the lecture was longer than MAX_LECTURE_CHARS
        self.chunks = chunk_text(text) if chunks is None else chunks
        self.arabic_share = arabic_share(text[:50_000])  # which language the lecture is written in
        n = len(self.chunks) or 1
        self.avg_len = sum(sum(c.terms.values()) for c in self.chunks) / n or 1
        df = Counter(t for c in self.chunks for t in c.terms)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def translation_target(self, question: str) -> str | None:
        """"English" / "Arabic" when the question is written in the other language than the lecture
        (e.g. an Arabic question about an English lecture): keyword search can't match across
        languages, so the caller asks the model for keywords in this language first. Else None."""
        q, lec = arabic_share(question), self.arabic_share
        if q is None or lec is None:
            return None
        if q >= 0.7 and lec <= 0.3:
            return "English"
        if q <= 0.3 and lec >= 0.7:
            return "Arabic"
        return None

    def _score(self, chunk: Chunk, query: dict[str, float]) -> float:
        length = sum(chunk.terms.values()) or 1
        score = 0.0
        for term, weight in query.items():
            tf = chunk.terms.get(term, 0)
            if tf:
                norm = tf * (self.K1 + 1) / (tf + self.K1 * (1 - self.B + self.B * length / self.avg_len))
                score += weight * self.idf.get(term, 0) * norm
        return score

    def _fit(self, ordered: list[Chunk], budget: int) -> list[Chunk]:
        picked, used = [], 0
        for c in ordered:
            if used + len(c.text) > budget and picked:
                continue
            picked.append(c)
            used += len(c.text)
        return sorted(picked, key=lambda c: c.id)

    def search(self, question: str, previous_question: str = "", fallback_ids: list[int] | None = None,
               budget: int = config.MATERIAL_BUDGET_CHARS, extra_terms: str = "") -> list[Chunk]:
        """The chunks to send with this question, in lecture order, within `budget` characters."""
        if not self.chunks:
            return []
        if len(self.text) <= budget:
            return list(self.chunks)  # short lecture: send it all

        if is_overview(question):
            # Spread over the whole lecture: the beginning of evenly spaced chunks.
            budget = config.OVERVIEW_BUDGET_CHARS
            step = max(1, math.ceil(len(self.chunks) * config.CHUNK_CHARS / budget))
            return self._fit(self.chunks[::step], budget)

        query: dict[str, float] = {}
        for t in tokenize(previous_question):  # follow-ups like "وضحلي أكتر" lean on the last question
            query[t] = 0.5
        for t in tokenize(question):
            query[t] = query.get(t, 0) + 1.0
        for t in tokenize(extra_terms):  # keywords in the lecture's language (cross-language questions)
            query[t] = query.get(t, 0) + 1.0

        scored = [(self._score(c, query), c) for c in self.chunks]
        hits = [c for s, c in sorted(scored, key=lambda x: -x[0]) if s > 0]
        if hits:
            return self._fit(hits[: config.MAX_CHUNKS], budget)

        # Nothing matched: reuse what the last answer was based on, else the start of the lecture.
        if fallback_ids:
            by_id = {c.id: c for c in self.chunks}
            again = [by_id[i] for i in fallback_ids if i in by_id]
            if again:
                return again
        return self._fit(self.chunks[:3], budget)


def format_chunks(chunks: list[Chunk]) -> str:
    return "\n\n".join(
        (f"[Page {c.page}]\n" if c.page is not None else f"[Part {c.id + 1}]\n") + c.text for c in chunks)
