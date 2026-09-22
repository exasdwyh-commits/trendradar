from __future__ import annotations

import re
from dataclasses import dataclass


STOP = {
    "the","a","an","to","of","for","and","in","on","with","from","at","by","is","are",
    "this","that","will","new","says","after","as","its","it","be","has","have",
}


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (value or "").lower())


def _bigrams(value: str) -> set[str]:
    normalized = _normalize_title(value)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[i:i+2] for i in range(len(normalized) - 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def tokens(title: str) -> set[str]:
    english = re.findall(r"[a-z0-9]{2,}", (title or "").lower())
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", title or "")
    return {x for x in english if x not in STOP} | set(chinese)


def similarity(a: str, b: str) -> float:
    """
    Hybrid title similarity.

    Word-token Jaccard is good for reordered English titles; character bigrams
    are much better for Chinese and for headlines that differ only in syntax.
    Using the stronger signal is intentionally conservative for clustering.
    """
    token_score = _jaccard(tokens(a), tokens(b))
    bigram_score = _jaccard(_bigrams(a), _bigrams(b))
    return max(token_score, bigram_score)


def body_terms(text: str) -> set[str]:
    text = (text or "").lower()
    terms = set(re.findall(r"[a-z][a-z0-9-]{3,}", text))
    han = re.sub(r"[^\u4e00-\u9fff]", "", text)
    terms.update(han[i:i+2] for i in range(max(0, len(han) - 1)))
    return terms


def body_similarity(a: str, b: str) -> float:
    aa, bb = body_terms(a), body_terms(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / min(len(aa), len(bb))


def same_event_score(title_a: str, body_a: str, title_b: str, body_b: str) -> float:
    title_score = similarity(title_a, title_b)
    if title_score >= 0.62:
        return title_score

    body_score = body_similarity(body_a, body_b)
    if title_score >= 0.34:
        return max(title_score, title_score * 0.65 + body_score * 0.35)

    # Body-only merges require some title affinity to avoid collapsing broad
    # industry articles that reuse the same vocabulary.
    if title_score >= 0.20 and body_score >= 0.55:
        return title_score * 0.35 + body_score * 0.65
    return title_score


@dataclass
class SimpleCluster:
    title: str
    item_ids: list[str]


def cluster_titles(rows: list[tuple[str, str]], threshold: float = 0.42) -> list[SimpleCluster]:
    clusters: list[SimpleCluster] = []
    for item_id, title in rows:
        target = None
        best = 0.0
        for cluster in clusters:
            score = similarity(title, cluster.title)
            if score > best:
                best, target = score, cluster
        if target is not None and best >= threshold:
            target.item_ids.append(item_id)
        else:
            clusters.append(SimpleCluster(title=title, item_ids=[item_id]))
    return clusters
