"""Thin Product Hunt API v2 (GraphQL) client with complexity-budget awareness.

Facts about the API that shape this design (verified against the public schema docs):
  * Endpoint: https://api.producthunt.com/v2/api/graphql, Bearer developer token.
  * Rate limit: 6,250 complexity points / 15 minutes, surfaced in X-Rate-Limit-* headers.
  * `posts` supports topic / order / postedAfter / postedBefore / featured — there is NO keyword
    search. Keyword search is therefore implemented locally over the ingested corpus
    (see market/competition.py) with `topics(query:)` as an API-side fallback.
  * Reviews text, pricing and funding are not exposed; we only read counts/ratings and derive the
    rest from comments, always flagged as derived/inferred.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

import httpx

from ...core.errors import NotConfigured, SourceError
from ..http import DEFAULT_HEADERS

ENDPOINT = "https://api.producthunt.com/v2/api/graphql"

POST_FIELDS_FULL = """
  id name slug tagline description url website votesCount commentsCount reviewsCount reviewsRating
  createdAt featuredAt
  topics(first: 6) { edges { node { name slug } } }
  makers { id name username headline }
  comments(first: 8, order: VOTES_COUNT) { edges { node { body votesCount } } }
  productLinks { type url }
"""

# Some fields are occasionally unavailable on older tokens/apps; keep a minimal variant.
POST_FIELDS_MIN = """
  id name slug tagline description url website votesCount commentsCount createdAt featuredAt
  topics(first: 6) { edges { node { name slug } } }
  makers { id name username headline }
"""

POSTS_QUERY = """
query Posts($first: Int!, $after: String, $order: PostsOrder, $postedAfter: DateTime, $postedBefore: DateTime, $topic: String) {
  posts(first: $first, after: $after, order: $order, postedAfter: $postedAfter, postedBefore: $postedBefore, topic: $topic) {
    pageInfo { hasNextPage endCursor }
    edges { node { %s } }
  }
}
"""

TOPICS_QUERY = """
query Topics($query: String!) {
  topics(first: 5, query: $query) { edges { node { id name slug postsCount } } }
}
"""

VIEWER_QUERY = "query { viewer { user { id username } } }"


class ProductHuntClient:
    def __init__(self, token: str, *, timeout: float = 30, min_remaining: int = 400):
        if not token:
            raise NotConfigured("PRODUCTHUNT_TOKEN is not set")
        self._token = token
        self._timeout = timeout
        self._min_remaining = min_remaining
        self.remaining: int | None = None
        self.reset_in: int | None = None
        self.calls = 0
        self._fields = POST_FIELDS_FULL

    def _headers(self) -> dict:
        return {
            **DEFAULT_HEADERS,
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def graphql(self, query: str, variables: dict | None = None) -> dict[str, Any]:
        if self.remaining is not None and self.remaining < self._min_remaining:
            raise SourceError(
                f"Product Hunt complexity budget nearly exhausted ({self.remaining} left, resets in {self.reset_in}s)"
            )
        with httpx.Client(timeout=self._timeout) as c:
            for attempt in range(1, 4):
                try:
                    response = c.post(
                        ENDPOINT, headers=self._headers(), json={"query": query, "variables": variables or {}}
                    )
                except httpx.TransportError as exc:
                    if attempt == 3:
                        raise SourceError(f"Product Hunt transport error: {exc}") from exc
                    time.sleep(attempt)
                    continue
                self.calls += 1
                self._read_limits(response)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 3:
                        raise SourceError(f"Product Hunt HTTP {response.status_code}")
                    time.sleep(min(10, 2 * attempt))
                    continue
                if response.status_code == 401:
                    raise SourceError("Product Hunt token rejected (401)")
                if response.status_code >= 400:
                    raise SourceError(f"Product Hunt HTTP {response.status_code}: {response.text[:200]}")
                payload = response.json()
                if payload.get("errors"):
                    raise SourceError(
                        "Product Hunt GraphQL error: "
                        + "; ".join(str(e.get("message")) for e in payload["errors"])[:300]
                    )
                return payload.get("data") or {}
        raise SourceError("Product Hunt request failed")

    def _read_limits(self, response: httpx.Response) -> None:
        for key in ("X-Rate-Limit-Remaining", "X-RateLimit-Remaining"):
            if key in response.headers:
                with contextlib.suppress(ValueError):
                    self.remaining = int(response.headers[key])
        for key in ("X-Rate-Limit-Reset", "X-RateLimit-Reset"):
            if key in response.headers:
                with contextlib.suppress(ValueError):
                    self.reset_in = int(response.headers[key])

    def whoami(self) -> dict:
        return self.graphql(VIEWER_QUERY)

    def posts(
        self,
        *,
        first: int = 20,
        order: str = "VOTES",
        posted_after: str | None = None,
        posted_before: str | None = None,
        topic: str | None = None,
        max_pages: int = 3,
    ) -> list[dict]:
        nodes: list[dict] = []
        after: str | None = None
        for _ in range(max_pages):
            variables = {
                "first": min(first, 50),
                "after": after,
                "order": order,
                "postedAfter": posted_after,
                "postedBefore": posted_before,
                "topic": topic,
            }
            try:
                data = self.graphql(POSTS_QUERY % self._fields, variables)
            except SourceError as exc:
                # Fall back to the minimal field set once if the schema rejects a field.
                if self._fields is POST_FIELDS_FULL and "GraphQL error" in str(exc):
                    self._fields = POST_FIELDS_MIN
                    data = self.graphql(POSTS_QUERY % self._fields, variables)
                else:
                    raise
            posts = data.get("posts") or {}
            for edge in posts.get("edges", []):
                if edge.get("node"):
                    nodes.append(edge["node"])
            page = posts.get("pageInfo") or {}
            if not page.get("hasNextPage") or len(nodes) >= first:
                break
            after = page.get("endCursor")
        return nodes[:first]

    def topics(self, query: str) -> list[dict]:
        data = self.graphql(TOPICS_QUERY, {"query": query})
        return [e["node"] for e in (data.get("topics") or {}).get("edges", []) if e.get("node")]
