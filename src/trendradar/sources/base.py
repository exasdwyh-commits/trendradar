"""Source adapter contract.

Every source (Reddit, Hacker News, GitHub, Product Hunt, RSS, mock fixtures…) produces the same two
shapes: RawSignal (demand side — a person saying something) and RawProduct (supply side — a product
that exists). Nothing downstream is allowed to depend on a provider's native payload.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

SourceKind = Literal["demand", "supply", "hybrid", "story"]
StoryLane = Literal["AI_COMMERCIALIZATION", "INDUSTRY", "COMPANY", "BUSINESS_MODEL", "GLOBALIZATION", "OTHER"]
SourceMode = Literal["live", "mock"]
TrendingWindow = Literal["7d", "30d", "month"]


class Engagement(BaseModel):
    votes: int = 0
    comments: int = 0
    likes: int = 0
    reviews: int = 0

    def total(self) -> int:
        return self.votes + self.comments + self.likes + self.reviews


class SearchQuery(BaseModel):
    text: str
    window_days: int = 90
    limit: int = 50
    kind: Literal["pain", "product", "any"] = "any"


class RawSignal(BaseModel):
    """A single demand-side utterance: post, comment, issue, review."""

    external_id: str
    source: str  # source id from sources.yml (e.g. 'hn', 'reddit-saas')
    adapter: str  # adapter implementation id (e.g. 'hackernews')
    source_type: SourceKind = "demand"
    url: str
    title: str = ""
    content: str = ""
    author: str | None = None
    author_id: str | None = None
    created_at: datetime | None = None
    fetched_at: datetime
    engagement: Engagement = Field(default_factory=Engagement)
    metadata: dict[str, Any] = Field(default_factory=dict)
    origin: SourceMode = "live"


class RawProduct(BaseModel):
    """A supply-side entity: a launched product, an app, an open-source project."""

    external_id: str
    source: str
    adapter: str
    name: str
    slug: str | None = None
    tagline: str | None = None
    description: str | None = None
    url: str
    website: str | None = None
    categories: list[str] = Field(default_factory=list)
    votes: int = 0
    comments: int = 0
    rating: float | None = None
    review_count: int = 0
    launched_at: datetime | None = None
    makers: list[dict[str, Any]] = Field(default_factory=list)
    credibility: dict[str, Any] = Field(default_factory=dict)
    pricing: str | None = None
    pricing_origin: Literal["api", "inferred", "unknown"] = "unknown"
    comment_samples: list[str] = Field(default_factory=list)  # used for derived insights
    raw: dict[str, Any] = Field(default_factory=dict)
    fetched_at: datetime
    origin: SourceMode = "live"


class FetchResult(BaseModel):
    signals: list[RawSignal] = Field(default_factory=list)
    products: list[RawProduct] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def extend(self, other: FetchResult) -> None:
        self.signals.extend(other.signals)
        self.products.extend(other.products)
        self.warnings.extend(other.warnings)

    @property
    def count(self) -> int:
        return len(self.signals) + len(self.products)


class AdapterHealth(BaseModel):
    ok: bool
    mode: SourceMode
    detail: str = ""


class SourceConfig(BaseModel):
    """Row of config/sources.yml (v5)."""

    id: str
    name: str
    adapter: str
    kind: SourceKind
    mode: SourceMode = "live"
    enabled: bool = True
    reliability: int = Field(default=70, ge=0, le=100)
    max_per_round: int = Field(default=100, ge=1, le=2000)
    queries: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    subreddits: list[str] = Field(default_factory=list)
    url: str | None = None
    window_days: int = Field(default=30, ge=1, le=365)
    note: str | None = None
    # story sources (editorial feeds for the brief)
    lane: str | None = None  # StoryLane
    tier: int = Field(default=2, ge=1, le=4)
    include: str | None = None  # regex on the URL path for html list pages
    enrich_limit: int = Field(default=6, ge=0, le=30)  # html: how many articles to open for body/date
    extra: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    id: str
    name: str
    type: SourceKind
    mode: SourceMode

    def search(self, query: SearchQuery) -> FetchResult: ...

    def fetch_latest(self) -> FetchResult:
        """Daily ingestion entry point: whatever this source considers new/relevant."""
        ...

    def health(self) -> AdapterHealth: ...


class BaseAdapter:
    """Convenience base with sane defaults; concrete adapters override what they support."""

    adapter_id: str = "base"
    type: SourceKind = "demand"
    supports_trending: bool = False

    def __init__(self, config: SourceConfig):
        self.config = config
        self.id = config.id
        self.name = config.name
        self.mode: SourceMode = config.mode
        if config.kind == "story":  # generic feed adapters take their role from the registry row
            self.type = "story"

    def search(self, query: SearchQuery) -> FetchResult:  # pragma: no cover - default
        return FetchResult(warnings=[f"{self.id}: search not supported"])

    def fetch_latest(self) -> FetchResult:
        result = FetchResult()
        for text in self.config.queries:
            result.extend(
                self.search(
                    SearchQuery(
                        text=text, window_days=self.config.window_days, limit=self.config.max_per_round
                    )
                )
            )
        return result

    def fetch_trending(self, window: TrendingWindow = "7d") -> FetchResult:  # pragma: no cover - default
        return FetchResult(warnings=[f"{self.id}: trending not supported"])

    def health(self) -> AdapterHealth:
        return AdapterHealth(ok=True, mode=self.mode)
