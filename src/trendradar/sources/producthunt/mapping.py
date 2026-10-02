from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from ...core.timeutil import parse_datetime, utcnow
from ..base import RawProduct

PRICING_HINTS = {
    "free": ["free forever", "100% free", "completely free", "free and open"],
    "freemium": ["free plan", "free tier", "freemium", "upgrade to pro", "pro plan"],
    "paid": ["per month", "/month", "/mo", "one-time", "lifetime deal", "pricing starts", "$"],
    "open_source": ["open source", "open-source", "mit license", "self-host"],
}


def infer_pricing(text: str) -> tuple[str | None, Literal["inferred", "unknown"]]:
    """Very rough pricing inference from marketing copy. Always labelled `inferred`."""
    lowered = (text or "").lower()
    for label in ("open_source", "freemium", "paid", "free"):
        if any(h in lowered for h in PRICING_HINTS[label]):
            return label, "inferred"
    return None, "unknown"


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host or None


def post_to_product(node: dict, *, source_id: str, origin: str = "live") -> RawProduct:
    topics = [e["node"]["name"] for e in (node.get("topics") or {}).get("edges", []) if e.get("node")]
    comments = [
        e["node"]["body"]
        for e in (node.get("comments") or {}).get("edges", [])
        if e.get("node") and e["node"].get("body")
    ]
    makers = [
        {
            "id": m.get("id"),
            "name": m.get("name"),
            "username": m.get("username"),
            "headline": m.get("headline"),
        }
        for m in node.get("makers") or []
    ]
    website = node.get("website")
    pricing, pricing_origin = infer_pricing(f"{node.get('tagline', '')} {node.get('description', '')}")
    launched = parse_datetime(node.get("featuredAt") or node.get("createdAt"))
    return RawProduct(
        external_id=str(node.get("id")),
        source=source_id,
        adapter="producthunt",
        name=node.get("name") or "",
        slug=node.get("slug"),
        tagline=node.get("tagline"),
        description=node.get("description"),
        url=node.get("url") or f"https://www.producthunt.com/posts/{node.get('slug')}",
        website=website,
        categories=topics,
        votes=int(node.get("votesCount") or 0),
        comments=int(node.get("commentsCount") or 0),
        rating=float(node["reviewsRating"]) if node.get("reviewsRating") not in (None, "") else None,
        review_count=int(node.get("reviewsCount") or 0),
        launched_at=launched,
        makers=makers,
        credibility={"maker_count": len(makers), "featured": bool(node.get("featuredAt"))},
        pricing=pricing,
        pricing_origin=pricing_origin,
        comment_samples=[c[:600] for c in comments[:8]],
        raw={k: node.get(k) for k in ("id", "slug", "productLinks")},
        fetched_at=utcnow(),
        origin=origin,  # type: ignore[arg-type]
    )
