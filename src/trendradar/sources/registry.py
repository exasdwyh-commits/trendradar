"""Source registry: config/sources.yml (v5) → SourceConfig → adapter instances."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import yaml

from ..core.config import sources_path
from ..core.errors import ValidationFailed
from .base import BaseAdapter, SourceConfig
from .github import GitHubIssuesAdapter, GitHubReposAdapter
from .hackernews import HackerNewsAdapter
from .hotlist import HotlistAdapter
from .html import HtmlListAdapter
from .mock import MockAdapter
from .producthunt import ProductHuntAdapter
from .reddit import RedditAdapter
from .rss import RssAdapter

ADAPTERS: dict[str, type[BaseAdapter]] = {
    "hackernews": HackerNewsAdapter,
    "reddit": RedditAdapter,
    "github_issues": GitHubIssuesAdapter,
    "github_repos": GitHubReposAdapter,
    "producthunt": ProductHuntAdapter,
    "rss": RssAdapter,
    "html": HtmlListAdapter,
    "hotlist": HotlistAdapter,
    "mock": MockAdapter,
}

KNOWN_KEYS = set(SourceConfig.model_fields) - {"extra"}


def load_source_configs(path: str | Path) -> list[SourceConfig]:
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    configs: list[SourceConfig] = []
    seen: set[str] = set()
    for row in raw.get("sources", []):
        if row.get("adapter") not in ADAPTERS:
            raise ValidationFailed(f"unknown adapter '{row.get('adapter')}' for source {row.get('id')}")
        extra = {k: v for k, v in row.items() if k not in KNOWN_KEYS}
        config = SourceConfig(**{k: v for k, v in row.items() if k in KNOWN_KEYS}, extra=extra)
        if config.id in seen:
            raise ValidationFailed(f"duplicate source id: {config.id}")
        seen.add(config.id)
        configs.append(config)
    return configs


def build_adapter(config: SourceConfig) -> BaseAdapter:
    return ADAPTERS[config.adapter](config)


def build_adapters(configs: list[SourceConfig], *, only_enabled: bool = True) -> list[BaseAdapter]:
    return [build_adapter(c) for c in configs if c.enabled or not only_enabled]


def sync_sources(
    conn: sqlite3.Connection, configs: list[SourceConfig], adapters: list[BaseAdapter] | None = None
) -> None:
    """Mirror the YAML registry into the `sources` table (mode reflects the adapter's effective mode).

    `enabled` is seeded from YAML on first insert only; afterwards the DB value wins so that toggles made
    in the UI/API survive restarts and jobs. Sources removed from YAML are disabled.
    """
    modes = {a.id: a.mode for a in (adapters or [])}
    for c in configs:
        conn.execute(
            """
            INSERT INTO sources(id,name,adapter,kind,mode,enabled,reliability,max_per_round,config_json,note)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name,adapter=excluded.adapter,kind=excluded.kind,
              mode=excluded.mode,reliability=excluded.reliability,
              max_per_round=excluded.max_per_round,config_json=excluded.config_json,note=excluded.note,
              updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            """,
            (
                c.id,
                c.name,
                c.adapter,
                c.kind,
                modes.get(c.id, c.mode),
                1 if c.enabled else 0,
                c.reliability,
                c.max_per_round,
                c.model_dump_json(exclude={"id", "name", "adapter", "kind", "mode", "enabled"}),
                c.note,
            ),
        )
    ids = [c.id for c in configs]
    if ids:
        conn.execute(f"UPDATE sources SET enabled=0 WHERE id NOT IN ({','.join('?' * len(ids))})", ids)
    conn.commit()


def enabled_adapters(
    conn: sqlite3.Connection, configs: list[SourceConfig] | None = None, *, mock_only: bool = False
) -> list[BaseAdapter]:
    """Build adapters for sources that are enabled in YAML *and* not disabled in the DB, and sync the registry."""
    configs = configs if configs is not None else load_source_configs(sources_path())
    adapters = build_adapters(configs)
    sync_sources(conn, configs, adapters)
    disabled = {r["id"] for r in conn.execute("SELECT id FROM sources WHERE enabled=0")}
    adapters = [a for a in adapters if a.id not in disabled]
    if mock_only:
        adapters = [a for a in adapters if a.mode == "mock"]
    return adapters
