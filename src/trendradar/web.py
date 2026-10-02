"""ASGI entrypoint: `uvicorn trendradar.web:app` (or `trendradar serve`)."""

from __future__ import annotations

from .api import create_app
from .core.logging import setup_logging
from .core.settings import get_settings

setup_logging(get_settings().log_level)
app = create_app()
