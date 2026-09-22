from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

LANES = {"COMPANY", "INDUSTRY", "BUSINESS_MODEL", "AI_COMMERCIALIZATION", "GLOBALIZATION"}
ROLES = {"PRIMARY", "VERIFIER", "DISCOVERY"}
TYPES = {"rss", "html"}


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    lane: str
    role: str
    type: str
    url: str
    include_pattern: str | None = None
    enabled: bool = True
    note: str | None = None


def load_yaml(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_sources(path: str | Path) -> list[Source]:
    raw = load_yaml(path)
    result: list[Source] = []
    seen: set[str] = set()
    for row in raw.get("sources", []):
        source = Source(
            id=str(row["id"]),
            name=str(row["name"]),
            lane=str(row["lane"]).upper(),
            role=str(row["role"]).upper(),
            type=str(row["type"]).lower(),
            url=str(row["url"]),
            include_pattern=row.get("include"),
            enabled=bool(row.get("enabled", True)),
            note=row.get("note"),
        )
        if source.id in seen:
            raise ValueError(f"duplicate source id: {source.id}")
        if source.lane not in LANES:
            raise ValueError(f"invalid lane {source.lane} for {source.id}")
        if source.role not in ROLES:
            raise ValueError(f"invalid role {source.role} for {source.id}")
        if source.type not in TYPES:
            raise ValueError(f"invalid type {source.type} for {source.id}")
        if not source.url.startswith(("http://", "https://")):
            raise ValueError(f"invalid url for {source.id}")
        seen.add(source.id)
        result.append(source)
    return result


def enabled_sources(sources: list[Source]) -> list[Source]:
    return [s for s in sources if s.enabled]
