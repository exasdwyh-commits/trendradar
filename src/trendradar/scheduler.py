from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo


def local_date(timezone_name: str) -> str:
    return datetime.now(ZoneInfo(timezone_name)).date().isoformat()


def should_run_daily(conn, timezone_name: str = "Asia/Shanghai", hour: int = 13) -> bool:
    now = datetime.now(ZoneInfo(timezone_name))
    if now.hour < hour:
        return False
    today = now.date().isoformat()
    row = conn.execute(
        """
        SELECT 1 FROM runs
        WHERE run_type='daily' AND status='SUCCESS'
          AND substr(datetime(started_at, '+8 hours'),1,10)=?
        LIMIT 1
        """,
        (today,),
    ).fetchone()
    return row is None


def daemon(tick, conn, timezone_name: str = "Asia/Shanghai", hour: int = 13, poll_seconds: int = 60):
    while True:
        if should_run_daily(conn, timezone_name, hour):
            tick()
        time.sleep(poll_seconds)
