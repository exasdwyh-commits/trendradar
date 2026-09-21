from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import feedparser
import httpx
from bs4 import BeautifulSoup

from .config import Source
from .scoring import commercial_score, evidence_score, freshness_score


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
    commercial_score: float
    title_hash: str


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    query = "&".join(
        p for p in parts.query.split("&")
        if p and not p.lower().startswith(("utm_", "ref=", "source=", "fbclid="))
    )
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def title_hash(title: str) -> str:
    key = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", title.lower())
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def make_item(source: Source, title: str, url: str, summary: str = "", published_at: datetime | None = None) -> Item:
    canonical = canonicalize_url(url)
    item_id = hashlib.sha256(f"{source.id}|{canonical}".encode()).hexdigest()[:24]
    return Item(
        id=item_id,
        source_id=source.id,
        title=normalize_title(title),
        url=url,
        canonical_url=canonical,
        published_at=published_at,
        summary=normalize_title(summary),
        source_role=source.role,
        lane=source.lane,
        freshness_score=freshness_score(published_at),
        evidence_score=evidence_score(source.role, bool(summary), bool(published_at)),
        commercial_score=commercial_score(title, summary),
        title_hash=title_hash(title),
    )


def collect_rss(source: Source, limit: int = 25) -> list[Item]:
    parsed = feedparser.parse(source.url)
    items: list[Item] = []
    for entry in parsed.entries[:limit]:
        title = str(entry.get("title", "")).strip()
        url = str(entry.get("link", "")).strip()
        if not title or not url:
            continue
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = datetime(*stamp[:6]) if stamp else None
        summary = re.sub(r"<[^>]+>", " ", str(entry.get("summary", "")))
        items.append(make_item(source, title, url, summary, published))
    return items


def collect_html(source: Source, client: httpx.Client, limit: int = 25) -> list[Item]:
    response = client.get(source.url, follow_redirects=True)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    pattern = re.compile(source.include_pattern) if source.include_pattern else None
    base_host = urlsplit(source.url).netloc
    seen: set[str] = set()
    items: list[Item] = []

    for anchor in soup.find_all("a", href=True):
        title = normalize_title(anchor.get_text(" ", strip=True))
        if len(title) < 20:
            continue
        url = urljoin(source.url, anchor["href"])
        parts = urlsplit(url)
        if parts.netloc != base_host:
            continue
        if pattern and not pattern.search(parts.path):
            continue
        canonical = canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        items.append(make_item(source, title, url))
        if len(items) >= limit:
            break
    return items


def collect_source(source: Source, timeout: float = 18, limit: int = 25) -> list[Item]:
    if source.type == "rss":
        return collect_rss(source, limit)
    headers = {"User-Agent": "TrendRadar-Business/3.0"}
    with httpx.Client(timeout=timeout, headers=headers) as client:
        return collect_html(source, client, limit)
