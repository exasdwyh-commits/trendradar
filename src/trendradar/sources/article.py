"""Article metadata/body extraction for HTML pages (ported from TrendRadar 3.1 collect.py).

Used by the html list adapter (to enrich discovered links) and by the material library ("add by URL").
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

_WS = re.compile(r"\s+")
_SUMMARY_META: tuple[dict[str, Any], ...] = (
    {"name": "description"},
    {"property": "og:description"},
    {"name": "twitter:description"},
)
_PUBLISHED_META: tuple[dict[str, Any], ...] = (
    {"property": "article:published_time"},
    {"name": "date"},
    {"name": "pubdate"},
)


def _attr(node: object, name: str) -> str | None:
    """A tag attribute as text (bs4 returns lists for multi-valued attributes)."""
    if not isinstance(node, Tag):
        return None
    value = node.get(name)
    if value is None:
        return None
    return value if isinstance(value, str) else " ".join(value)


def clean_text(value: str | None) -> str:
    return _WS.sub(" ", str(value or "")).strip()


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


_URL_DATE = re.compile(r"/(20\d{2})[/-]?(\d{2})[/-]?(\d{2})(?:/|-|_|\.)")


def parse_url_date(url: str) -> datetime | None:
    match = _URL_DATE.search(url)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=UTC)
    except ValueError:
        return None


def _json_ld(soup: BeautifulSoup) -> list[dict]:
    result: list[dict] = []
    for node in soup.find_all("script", type="application/ld+json"):
        try:
            raw = json.loads(node.get_text(strip=True))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(raw, dict):
            result.append(raw)
        elif isinstance(raw, list):
            result.extend(x for x in raw if isinstance(x, dict))
    return result


@dataclass
class Article:
    title: str
    summary: str
    content: str
    published: datetime | None
    author: str | None = None
    site_name: str | None = None


def extract_article(html_text: str, fallback_title: str = "") -> Article:
    soup = BeautifulSoup(html_text, "html.parser")
    title = clean_text(fallback_title)
    og_title = soup.find("meta", property="og:title")
    if _attr(og_title, "content"):
        title = clean_text(_attr(og_title, "content"))
    elif soup.title and soup.title.string:
        title = clean_text(soup.title.string)

    summary = ""
    for attrs in _SUMMARY_META:
        node = soup.find("meta", attrs=attrs)
        if _attr(node, "content"):
            summary = clean_text(_attr(node, "content"))
            break

    published = None
    for attrs in _PUBLISHED_META:
        node = soup.find("meta", attrs=attrs)
        if _attr(node, "content"):
            published = parse_datetime(_attr(node, "content"))
            if published:
                break
    if not published:
        time_node = soup.find("time", attrs={"datetime": True})
        if time_node:
            published = parse_datetime(_attr(time_node, "datetime"))

    author = None
    node = soup.find("meta", attrs={"name": "author"})
    if _attr(node, "content"):
        author = clean_text(_attr(node, "content"))
    site_name = None
    node = soup.find("meta", property="og:site_name")
    if _attr(node, "content"):
        site_name = clean_text(_attr(node, "content"))

    for obj in _json_ld(soup):
        if not published and obj.get("datePublished"):
            published = parse_datetime(str(obj.get("datePublished")))
        if not summary and obj.get("description"):
            summary = clean_text(str(obj.get("description")))
        if not author and isinstance(obj.get("author"), dict) and obj["author"].get("name"):
            author = clean_text(obj["author"]["name"])

    container = soup.find("article") or soup.find("main") or soup.body
    content = ""
    if container:
        for tag in container.find_all(["script", "style", "nav", "footer", "form", "aside", "noscript"]):
            tag.decompose()
        paragraphs = [clean_text(p.get_text(" ", strip=True)) for p in container.find_all(["p", "li"])]
        paragraphs = [p for p in paragraphs if len(p) >= 35]
        content = "\n".join(paragraphs[:80])[:12000]
    return Article(
        title=title, summary=summary, content=content, published=published, author=author, site_name=site_name
    )


def _root_domain(host: str) -> str:
    parts = host.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def discover_links(
    base_url: str, html_text: str, *, include: str | None, limit: int
) -> list[tuple[str, str]]:
    """Return (title, url) pairs for same-site links on a listing page, optionally filtered by a path regex."""
    soup = BeautifulSoup(html_text, "html.parser")
    pattern = re.compile(include) if include else None
    base_root = _root_domain(urlsplit(base_url).netloc)
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        text_title = clean_text(anchor.get_text(" ", strip=True))
        attr_title = clean_text(_attr(anchor, "title"))
        title = attr_title if len(attr_title) >= len(text_title) else text_title
        if len(title) < 12:
            continue
        url = urljoin(base_url, _attr(anchor, "href") or "").split("#", 1)[0]
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or _root_domain(parts.netloc) != base_root:
            continue
        if pattern and not pattern.search(parts.path):
            continue
        key = url.rstrip("/")
        if key in seen or key == base_url.rstrip("/"):
            continue
        seen.add(key)
        result.append((title, url))
        if len(result) >= limit:
            break
    return result
