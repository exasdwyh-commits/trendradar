from __future__ import annotations

import time
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo


def _today_utc_window(timezone_name: str) -> tuple[str, str]:
    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)
    start_local = datetime.combine(now.date(), dtime.min, tzinfo=tz)
    end_local = datetime.combine(now.date(), dtime.max, tzinfo=tz)
    return (
        start_local.astimezone(timezone.utc).isoformat(),
        end_local.astimezone(timezone.utc).isoformat(),
    )


def should_run_daily(conn, timezone_name: str = "Asia/Shanghai", hour: int = 13) -> bool:
    now = datetime.now(ZoneInfo(timezone_name))
    if now.hour < hour:
        return False
    start_utc,end_utc = _today_utc_window(timezone_name)
    row = conn.execute(
        """
        SELECT 1 FROM runs
        WHERE run_type='daily' AND status='SUCCESS'
          AND started_at>=? AND started_at<=?
        LIMIT 1
        """,
        (start_utc,end_utc),
    ).fetchone()
    return row is None


def daemon(tick, conn, timezone_name: str = "Asia/Shanghai", hour: int = 13, poll_seconds: int = 60):
    while True:
        if should_run_daily(conn, timezone_name, hour):
            tick()
        time.sleep(poll_seconds)
