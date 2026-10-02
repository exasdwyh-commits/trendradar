from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def model_environment() -> dict[str, str]:
    """Read model settings from .env without mutating the process environment.

    Explicit process variables, including empty values, take precedence.
    """
    return {**{key: value or "" for key, value in dotenv_values(".env").items()}, **os.environ}


class Settings(BaseSettings):
    """Process-wide configuration loaded from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    root: Path = Field(default_factory=Path.cwd)
    data_dir: str = "data"
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8787
    # 安全（api/security.py）：额外信任的 Host（逗号分隔，* = 不校验）与浏览器来源
    allowed_hosts: str = ""
    cors_origins: str = ""
    timezone: str = "Asia/Shanghai"
    daily_hour: int = 1

    # Easel 发布桥接（docs/EASEL_BRIDGE.md）：handoff 包目录；留空 = <data_dir>/easel_outbox
    easel_outbox: str = ""

    producthunt_mode: Literal["graphql", "mcp", "mock"] = "mock"
    producthunt_token: str = ""
    github_token: str = ""
    reddit_user_agent: str = ""
    reddit_enabled: bool = False

    ai_24h_budget_cny: float = 0.0

    # Pipeline knobs (also overridable in config/settings.yml)
    cluster_gate_min_signals: int = 3
    cluster_gate_min_sources: int = 2
    today_min_score: float = 70.0
    today_min_confidence: float = 60.0
    today_max_items: int = 5

    @property
    def db_path(self) -> Path:
        return self.root / self.data_dir / "trendradar.db"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    get_settings.cache_clear()
