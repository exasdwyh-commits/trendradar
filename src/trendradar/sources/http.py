from __future__ import annotations

import time

import httpx

from ..core.errors import SourceError

DEFAULT_HEADERS = {
    "User-Agent": "OpportunityRadar/4.0 (+personal research; contact via repo)",
    "Accept-Language": "en-US,en;q=0.8",
}


def client(timeout: float = 20, headers: dict | None = None) -> httpx.Client:
    merged = dict(DEFAULT_HEADERS)
    if headers:
        merged.update(headers)
    return httpx.Client(timeout=timeout, headers=merged, follow_redirects=True)


def get_json(c: httpx.Client, url: str, *, params: dict | None = None, attempts: int = 3) -> dict | list:
    return request_json(c, "GET", url, params=params, attempts=attempts)


def request_json(
    c: httpx.Client,
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
    headers: dict | None = None,
    attempts: int = 3,
) -> dict | list:
    """Bounded retry on 429/5xx/transport errors. Raises SourceError with the last failure."""
    last: str = ""
    for attempt in range(1, attempts + 1):
        try:
            response = c.request(method, url, params=params, json=json, headers=headers)
            if response.status_code == 429 or response.status_code >= 500:
                last = f"HTTP {response.status_code}"
                if attempt < attempts:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after else float(attempt)
                    except ValueError:
                        wait = float(attempt)
                    time.sleep(min(6.0, max(0.5, wait)))
                    continue
                raise SourceError(f"{url}: {last}")
            if response.status_code >= 400:
                raise SourceError(f"{url}: HTTP {response.status_code} {response.text[:200]}")
            return response.json()
        except httpx.TransportError as exc:
            last = str(exc)
            if attempt >= attempts:
                raise SourceError(f"{url}: {last}") from exc
            time.sleep(min(6.0, float(attempt)))
        except ValueError as exc:  # invalid JSON
            raise SourceError(f"{url}: invalid JSON response") from exc
    raise SourceError(f"{url}: {last or 'request failed'}")
