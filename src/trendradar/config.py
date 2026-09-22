from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

LANES = {"COMPANY", "INDUSTRY", "BUSINESS_MODEL", "AI_COMMERCIALIZATION", "GLOBALIZATION"}
ROLES = {"PRIMARY", "VERIFIER", "DISCOVERY"}
TYPES = {"rss", "html"}

DEFAULT_TIER = {"PRIMARY": 1, "VERIFIER": 2, "DISCOVERY": 4}
DEFAULT_RELIABILITY = {"PRIMARY": 88, "VERIFIER": 80, "DISCOVERY": 60}
DEFAULT_BUSINESS_VALUE = {"PRIMARY": 72, "VERIFIER": 76, "DISCOVERY": 58}
DEFAULT_NOISE = {"PRIMARY": 16, "VERIFIER": 24, "DISCOVERY": 58}
DEFAULT_ACCURACY = {"PRIMARY": 88, "VERIFIER": 80, "DISCOVERY": 62}


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    lane: str
    role: str
    type: str
    url: str
    include_pattern: str | None = None
    tier: int = 3
    reliability: int = 70
    business_value: int = 65
    noise: int = 30
    accuracy: int = 70
    window_days: int | None = None
    scan_limit: int | None = None
    max_per_round: int | None = None
    enabled: bool = True
    note: str | None = None


def load_yaml(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _bounded_int(value: Any, default: int, low: int = 0, high: int = 100) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < low or parsed > high:
        raise ValueError(f"value {parsed} outside [{low}, {high}]")
    return parsed


def load_sources(path: str | Path) -> list[Source]:
    raw = load_yaml(path)
    result: list[Source] = []
    seen: set[str] = set()
    for row in raw.get("sources", []):
        role = str(row["role"]).upper()
        tier = _bounded_int(row.get("tier"), DEFAULT_TIER.get(role, 3), 1, 4)
        max_per_round = row.get("max_per_round")
        if max_per_round is not None:
            max_per_round = _bounded_int(max_per_round, 18, 1, 100)
        window_days = row.get("window_days")
        if window_days is not None:
            window_days = _bounded_int(window_days, 7, 1, 365)
        scan_limit = row.get("scan_limit")
        if scan_limit is not None:
            scan_limit = _bounded_int(scan_limit, 80, 1, 500)

        source = Source(
            id=str(row["id"]),
            name=str(row["name"]),
            lane=str(row["lane"]).upper(),
            role=role,
            type=str(row["type"]).lower(),
            url=str(row["url"]),
            include_pattern=row.get("include"),
            tier=tier,
            reliability=_bounded_int(
                row.get("reliability"), DEFAULT_RELIABILITY.get(role, 70)
            ),
            business_value=_bounded_int(
                row.get("business_value"), DEFAULT_BUSINESS_VALUE.get(role, 65)
            ),
            noise=_bounded_int(row.get("noise"), DEFAULT_NOISE.get(role, 30)),
            accuracy=_bounded_int(
                row.get("accuracy"), DEFAULT_ACCURACY.get(role, 70)
            ),
            window_days=window_days,
            scan_limit=scan_limit,
            max_per_round=max_per_round,
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
