from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

import feedparser

from .config import Source
from .scoring import evidence_score, freshness_score


@dataclass
class Item:
    id: str
    source_id: str
    title: str
    url: str
    canonical_url: str
    published_at: datetime | None
    summary: str
    source_role: str
    lane: str
    freshness_score: float
    evidence_score: float
    title_hash: str


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    clean_query = "&".join(
        p for p in parts.query.split("&")
        if p and not p.lower().startswith(("utm_", "ref=", "source="))
    )
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), clean_query, ""))


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip()


def title_hash(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", normalize_title(title).lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def collect_rss(source: Source) -> list[Item]:
    feed = feedparser.parse(source.url)
    result: list[Item] = []
    for entry in feed.entries:
        title = normalize_title(str(entry.get("title", "")))
        url = str(entry.get("link", "")).strip()
        if not title or not url:
            continue
        published_at = None
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            published_at = datetime(*parsed[:6])
        summary = re.sub(r"<[^>]+>", " ", str(entry.get("summary", "")))
        summary = re.sub(r"\s+", " ", summary).strip()
        canonical = canonicalize_url(url)
        fingerprint = hashlib.sha256(f"{source.id}|{canonical}".encode("utf-8")).hexdigest()[:24]
        result.append(Item(
            id=fingerprint,
            source_id=source.id,
            title=title,
            url=url,
            canonical_url=canonical,
            published_at=published_at,
            summary=summary,
            source_role=source.role,
            lane=source.lane,
            freshness_score=freshness_score(published_at),
            evidence_score=evidence_score(source.role, bool(summary), bool(published_at)),
            title_hash=title_hash(title),
        ))
    return result
