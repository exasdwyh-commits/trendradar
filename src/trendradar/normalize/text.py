from __future__ import annotations

import hashlib
import re

_WS = re.compile(r"\s+")
_URL = re.compile(r"https?://\S+")
_MD = re.compile(r"[*_`>#\[\]()]+")


def clean_text(value: str | None) -> str:
    text = (value or "").replace("\r", " ")
    text = _URL.sub(" ", text)
    text = _MD.sub(" ", text)
    return _WS.sub(" ", text).strip()


def normalized_key(value: str) -> str:
    """Lowercase alnum-only key used for hashing near-identical text."""
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (value or "").lower())


def content_hash(title: str, content: str) -> str:
    key = normalized_key(title) + "|" + normalized_key(content)[:2000]
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def detect_lang(text: str) -> str:
    """Cheap language guess: enough to route CJK vs Latin text. Not a full detector."""
    if not text:
        return "und"
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    if han and han / max(1, len(text)) > 0.15:
        return "zh"
    kana = len(re.findall(r"[\u3040-\u30ff]", text))
    if kana:
        return "ja"
    return "en"


_TOKEN = re.compile(r"[a-z][a-z0-9'+#.-]{1,}")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\uac00-\ud7af]+")
STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "if",
    "then",
    "so",
    "of",
    "to",
    "in",
    "on",
    "at",
    "for",
    "with",
    "from",
    "by",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "am",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "i",
    "me",
    "my",
    "we",
    "our",
    "you",
    "your",
    "they",
    "them",
    "their",
    "he",
    "she",
    "his",
    "her",
    "as",
    "than",
    "too",
    "very",
    "just",
    "can",
    "could",
    "would",
    "should",
    "will",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "not",
    "no",
    "yes",
    "there",
    "here",
    "what",
    "which",
    "who",
    "when",
    "where",
    "why",
    "how",
    "all",
    "any",
    "some",
    "one",
    "every",
    "each",
    "into",
    "about",
    "up",
    "out",
    "over",
    "again",
    "still",
    "also",
    "because",
    "while",
    "after",
    "before",
    "now",
    "get",
    "got",
    "like",
    "use",
    "using",
    "used",
    "really",
    "thing",
    "things",
    "way",
    "much",
    "more",
    "most",
    "im",
    "ive",
    "dont",
    "cant",
}


def cjk_bigrams(text: str) -> list[str]:
    """Character bigrams for CJK runs (no whitespace word boundaries); a lone character stands by itself."""
    out: list[str] = []
    for run in _CJK_RUN.findall(text or ""):
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i : i + 2] for i in range(len(run) - 1))
    return out


def tokens(text: str) -> list[str]:
    """Latin word tokens (stopwords removed) plus CJK character bigrams, so Chinese/Japanese text
    gets real features for simhash, local embeddings and keyword overlap instead of an empty list."""
    lowered = (text or "").lower()
    words = [t for t in _TOKEN.findall(lowered) if t not in STOPWORDS and len(t) > 1]
    return words + cjk_bigrams(lowered)
