from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

LANES = {"TECHNOLOGY", "BUSINESS", "LIVELIHOOD", "SOCIETY"}
ROLES = {"PRIMARY", "VERIFIER", "DISCOVERY"}
TYPES = {"rss", "page"}


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    lane: str
    role: str
    type: str
    url: str
    enabled: bool = True


def load_sources(path: str | Path) -> list[Source]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    items = raw.get("sources", [])
    result: list[Source] = []
    seen: set[str] = set()
    for item in items:
        src = Source(
            id=str(item["id"]),
            name=str(item["name"]),
            lane=str(item["lane"]).upper(),
            role=str(item["role"]).upper(),
            type=str(item["type"]).lower(),
            url=str(item["url"]),
            enabled=bool(item.get("enabled", True)),
        )
        if src.id in seen:
            raise ValueError(f"duplicate source id: {src.id}")
        if src.lane not in LANES:
            raise ValueError(f"invalid lane for {src.id}: {src.lane}")
        if src.role not in ROLES:
            raise ValueError(f"invalid role for {src.id}: {src.role}")
        if src.type not in TYPES:
            raise ValueError(f"invalid type for {src.id}: {src.type}")
        if not src.url.startswith(("http://", "https://")):
            raise ValueError(f"invalid url for {src.id}: {src.url}")
        seen.add(src.id)
        result.append(src)
    return result


def enabled_sources(sources: Iterable[Source]) -> list[Source]:
    return [s for s in sources if s.enabled]
