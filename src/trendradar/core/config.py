"""Tunable pipeline configuration from config/settings.yml (with safe defaults)."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .settings import get_settings

DEFAULT_WEIGHTS = {
    "pain": 0.15,
    "demand": 0.15,
    "growth": 0.10,
    "competition": 0.15,
    "gap": 0.15,
    "monetization": 0.10,
    "build_ease": 0.10,
    "distribution": 0.05,
}


@dataclass
class PipelineConfig:
    rule_filter_min_score: float = 0.15
    classifier_min_relevance: int = 40
    cluster_threshold_api: float = 0.45
    cluster_threshold_local: float = 0.10
    product_cluster_threshold_api: float = 0.50
    product_cluster_threshold_local: float = 0.15
    gate_min_signals: int = 3
    gate_min_sources: int = 2
    gate_min_velocity: float = 3.0
    max_clusters_analyzed_per_run: int = 8
    competitors_per_cluster: int = 8
    max_workers: int = 6
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    today_min_score: float = 70.0
    today_min_confidence: float = 60.0
    today_max_items: int = 5
    app_name: str = "TrendRadar 写作台"

    def cluster_threshold(self, embedder_name: str) -> float:
        return (
            self.cluster_threshold_local if embedder_name.startswith("local") else self.cluster_threshold_api
        )

    def product_cluster_threshold(self, embedder_name: str) -> float:
        return (
            self.product_cluster_threshold_local
            if embedder_name.startswith("local")
            else self.product_cluster_threshold_api
        )


def config_dir(root: Path | None = None) -> Path:
    root = root or get_settings().root
    for candidate in (root / "config", Path(__file__).resolve().parents[3] / "config"):
        if candidate.exists():
            return candidate
    return root / "config"


def sources_path(root: Path | None = None) -> Path:
    return config_dir(root) / "sources.yml"


def load_pipeline_config(path: Path | None = None) -> PipelineConfig:
    path = path or (config_dir() / "settings.yml")
    cfg = PipelineConfig()
    if not path.exists():
        return cfg
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    pipeline = data.get("pipeline") or {}
    for key in (
        "rule_filter_min_score",
        "classifier_min_relevance",
        "cluster_threshold_api",
        "cluster_threshold_local",
        "product_cluster_threshold_api",
        "product_cluster_threshold_local",
        "gate_min_signals",
        "gate_min_sources",
        "gate_min_velocity",
        "max_clusters_analyzed_per_run",
        "competitors_per_cluster",
    ):
        if key in pipeline:
            setattr(cfg, key, type(getattr(cfg, key))(pipeline[key]))
    cfg.max_workers = int((data.get("collection") or {}).get("max_workers", cfg.max_workers))
    weights = (data.get("scoring") or {}).get("weights") or {}
    if weights:
        cfg.weights = {k: float(weights.get(k, v)) for k, v in DEFAULT_WEIGHTS.items()}
    today = data.get("today") or {}
    cfg.today_min_score = float(today.get("min_score", cfg.today_min_score))
    cfg.today_min_confidence = float(today.get("min_confidence", cfg.today_min_confidence))
    cfg.today_max_items = int(today.get("max_items", cfg.today_max_items))
    cfg.app_name = str((data.get("app") or {}).get("name", cfg.app_name))
    return cfg


@lru_cache(maxsize=1)
def get_pipeline_config() -> PipelineConfig:
    return load_pipeline_config()
