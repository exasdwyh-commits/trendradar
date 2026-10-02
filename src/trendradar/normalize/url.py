from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

_TRACKING_PREFIXES = (
    "utm_",
    "ref=",
    "source=",
    "fbclid=",
    "gclid=",
    "mc_",
    "igshid=",
    "ref_src=",
    "share_id=",
)


def canonicalize_url(url: str) -> str:
    """Dedup key for URLs: https, lowercase host without www, no tracking params, sorted query, no fragment, no trailing slash."""
    parts = urlsplit((url or "").strip())
    params = sorted(p for p in parts.query.split("&") if p and not p.lower().startswith(_TRACKING_PREFIXES))
    host = parts.netloc.lower()
    if host.startswith("www.") and host.count(".") >= 2:
        host = host[4:]
    scheme = parts.scheme.lower() or "https"
    if scheme == "http":
        scheme = "https"
    return urlunsplit((scheme, host, parts.path.rstrip("/"), "&".join(params), ""))
