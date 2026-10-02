"""Minimal in-process scheduler: run the daily pipeline once per day at DAILY_HOUR (local timezone)."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..core.logging import get_logger
from ..core.settings import get_settings
from ..db.connection import connect
from .pipeline import run_daily
from .state import active_job

log = get_logger("scheduler")
BUSY_RETRY_SECONDS = 300
BUSY_MAX_RETRIES = 12


def seconds_until_next_run(now: datetime, hour: int) -> float:
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


def run_forever(stop: threading.Event | None = None) -> None:
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    stop = stop or threading.Event()
    while not stop.is_set():
        wait = seconds_until_next_run(datetime.now(tz), settings.daily_hour)
        log.info("next daily run in %.0f minutes", wait / 60)
        if stop.wait(wait):
            break
        conn = connect(settings.db_path)
        try:
            for _ in range(BUSY_MAX_RETRIES):
                busy = active_job(conn)
                if not busy:
                    break
                log.info("daily run waits: %s job %s is still running", busy["type"], busy["id"])
                if stop.wait(BUSY_RETRY_SECONDS):
                    return
            else:
                log.warning("skipping today's daily run: another job kept running for an hour")
                continue
            result = run_daily(conn)
            log.info("daily job %s finished: %s", result["job_id"], result["status"])
        except Exception:
            log.exception("daily job crashed")
        finally:
            conn.close()
        time.sleep(61)  # never double-fire within the same minute


def start_background(stop: threading.Event | None = None) -> threading.Thread:
    t = threading.Thread(target=run_forever, args=(stop,), name="scheduler", daemon=True)
    t.start()
    return t
