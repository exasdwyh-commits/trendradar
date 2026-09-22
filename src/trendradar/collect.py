from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
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
    content: str
    source_role: str
    lane: str
    freshness_score: float
    evidence_score: float
    commercial_score: float
    title_hash: str


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


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


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None


def make_item(
    source: Source,
    title: str,
    url: str,
    summary: str = "",
    published_at: datetime | None = None,
    content: str = "",
) -> Item:
    canonical = canonicalize_url(url)
    item_id = hashlib.sha256(f"{source.id}|{canonical}".encode()).hexdigest()[:24]
    body_present = bool(normalize_title(content) or normalize_title(summary))
    return Item(
        id=item_id,
        source_id=source.id,
        title=normalize_title(title),
        url=url,
        canonical_url=canonical,
        published_at=published_at,
        summary=normalize_title(summary)[:1600],
        content=normalize_title(content)[:9000],
        source_role=source.role,
        lane=source.lane,
        freshness_score=freshness_score(published_at),
        evidence_score=evidence_score(
            source.role,
            body_present,
            bool(published_at),
            reliability=source.reliability,
            noise=source.noise,
            accuracy=source.accuracy,
        ),
        commercial_score=commercial_score(
            title,
            f"{summary} {content[:1800]}",
            source_business_value=source.business_value,
        ),
        title_hash=title_hash(title),
    )


def collect_rss(source: Source, limit: int = 18) -> list[Item]:
    parsed = feedparser.parse(source.url)
    scan_limit = source.scan_limit or max(limit, 80 if source.window_days else limit)
    cutoff = None
    if source.window_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=source.window_days)

    picked: list[Item] = []
    for entry in parsed.entries[:scan_limit]:
        title = str(entry.get("title", "")).strip()
        url = str(entry.get("link", "")).strip()
        if not title or not url:
            continue
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = datetime(*stamp[:6], tzinfo=timezone.utc) if stamp else None

        # A time window protects high-volume full-history feeds from a quota bug:
        # we scan enough recent history first, then apply max_per_round. Entries
        # without a parseable date are kept rather than silently discarded.
        if cutoff is not None and published is not None and published < cutoff:
            continue

        summary = re.sub(r"<[^>]+>", " ", str(entry.get("summary", "")))
        content_blocks = entry.get("content") or []
        content = " ".join(str(x.get("value","")) for x in content_blocks)
        content = re.sub(r"<[^>]+>", " ", content)
        picked.append(make_item(source, title, url, summary, published, content))
        if len(picked) >= limit:
            break
    return picked


def _json_ld(soup: BeautifulSoup) -> list[dict]:
    result = []
    for node in soup.find_all("script", type="application/ld+json"):
        try:
            raw = json.loads(node.get_text(strip=True))
            if isinstance(raw, dict):
                result.append(raw)
            elif isinstance(raw, list):
                result.extend(x for x in raw if isinstance(x, dict))
        except (json.JSONDecodeError, TypeError):
            continue
    return result


def extract_article(html_text: str, fallback_title: str) -> tuple[str, str, str, datetime | None]:
    soup = BeautifulSoup(html_text, "html.parser")
    title = fallback_title
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = normalize_title(og_title["content"])
    elif soup.title and soup.title.string:
        title = normalize_title(soup.title.string)

    summary = ""
    for attrs in (
        {"name": "description"},
        {"property": "og:description"},
        {"name": "twitter:description"},
    ):
        node = soup.find("meta", attrs=attrs)
        if node and node.get("content"):
            summary = normalize_title(node["content"])
            break

    published = None
    for attrs in (
        {"property": "article:published_time"},
        {"name": "date"},
        {"name": "pubdate"},
    ):
        node = soup.find("meta", attrs=attrs)
        if node and node.get("content"):
            published = parse_datetime(node["content"])
            if published:
                break
    if not published:
        time_node = soup.find("time", attrs={"datetime": True})
        if time_node:
            published = parse_datetime(time_node.get("datetime"))

    for obj in _json_ld(soup):
        if not published and obj.get("datePublished"):
            published = parse_datetime(str(obj.get("datePublished")))
        if not summary and obj.get("description"):
            summary = normalize_title(str(obj.get("description")))

    container = soup.find("article") or soup.find("main") or soup.body
    content = ""
    if container:
        for tag in container.find_all(["script","style","nav","footer","form","aside"]):
            tag.decompose()
        paragraphs = [normalize_title(p.get_text(" ", strip=True)) for p in container.find_all(["p","li"])]
        paragraphs = [p for p in paragraphs if len(p) >= 35]
        content = "\n".join(paragraphs[:60])[:9000]
    return title, summary, content, published


def _discover_links(source: Source, html_text: str, limit: int) -> list[tuple[str,str]]:
    soup = BeautifulSoup(html_text, "html.parser")
    pattern = re.compile(source.include_pattern) if source.include_pattern else None
    base_host = urlsplit(source.url).netloc
    seen: set[str] = set()
    result: list[tuple[str,str]] = []
    for anchor in soup.find_all("a", href=True):
        title = normalize_title(anchor.get_text(" ", strip=True))
        if len(title) < 18:
            continue
        url = urljoin(source.url, anchor["href"])
        parts = urlsplit(url)
        if parts.netloc != base_host:
            continue
        if pattern and not pattern.search(parts.path):
            continue
        canonical = canonicalize_url(url)
        if canonical in seen or canonical == canonicalize_url(source.url):
            continue
        seen.add(canonical)
        result.append((title,url))
        if len(result) >= limit:
            break
    return result


def collect_html(
    source: Source,
    client: httpx.Client,
    limit: int = 18,
    enrich_limit: int = 6,
) -> list[Item]:
    response = client.get(source.url, follow_redirects=True)
    response.raise_for_status()
    links = _discover_links(source, response.text, limit)
    items: list[Item] = []
    for index,(fallback_title,url) in enumerate(links):
        title,summary,content,published = fallback_title,"","",None
        if index < enrich_limit:
            try:
                page = client.get(url, follow_redirects=True)
                page.raise_for_status()
                title,summary,content,published = extract_article(page.text, fallback_title)
            except Exception:
                pass
        items.append(make_item(source,title,url,summary,published,content))
    return items


def collect_source(
    source: Source,
    timeout: float = 18,
    limit: int = 18,
    enrich_limit: int = 6,
) -> list[Item]:
    if source.type == "rss":
        return collect_rss(source, limit)
    headers = {
        "User-Agent": "TrendRadar-Business/3.0 (+personal research)",
        "Accept-Language": "en-US,en;q=0.8,zh-CN;q=0.6",
    }
    with httpx.Client(timeout=timeout, headers=headers) as client:
        return collect_html(source, client, limit, enrich_limit)
