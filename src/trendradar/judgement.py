from __future__ import annotations

import calendar
import re
import sqlite3
from datetime import datetime, timedelta, timezone


RESULTS={"CORRECT","DIRECTIONALLY_RIGHT","PARTIAL","WRONG","UNKNOWN"}


def _add_months(value: datetime, months: int) -> datetime:
    month_index=(value.month-1)+months
    year=value.year+month_index//12
    month=month_index%12+1
    day=min(value.day,calendar.monthrange(year,month)[1])
    return value.replace(year=year,month=month,day=day)


def horizon_to_review_at(
    horizon: str,
    *,
    now: datetime | None = None,
) -> str | None:
    text=(horizon or "").strip().lower()
    if not text:
        return None
    base=now or datetime.now(timezone.utc)
    match=re.search(
        r"(\d+)\s*(天|日|周|个月|月|年|days?|weeks?|months?|years?)",
        text,
        flags=re.I,
    )
    if not match:
        return None
    amount=max(1,int(match.group(1)))
    unit=match.group(2).lower()
    if unit in {"天","日","day","days"}:
        target=base+timedelta(days=amount)
    elif unit in {"周","week","weeks"}:
        target=base+timedelta(weeks=amount)
    elif unit in {"个月","月","month","months"}:
        target=_add_months(base,amount)
    else:
        target=_add_months(base,amount*12)
    return target.isoformat()


def review_judgement(
    conn: sqlite3.Connection,
    ledger_id: str,
    result: str,
) -> None:
    normalized=(result or "").upper()
    if normalized not in RESULTS:
        raise ValueError("invalid judgement result")
    exists=conn.execute(
        "SELECT id FROM judgement_ledger WHERE id=?",
        (ledger_id,),
    ).fetchone()
    if not exists:
        raise KeyError("judgement not found")
    conn.execute(
        """
        UPDATE judgement_ledger
        SET result=?,reviewed_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (normalized,ledger_id),
    )
    conn.commit()


def list_judgements(conn: sqlite3.Connection) -> list[dict]:
    rows=conn.execute(
        """
        SELECT jl.*,t.name trend_name,th.thesis
        FROM judgement_ledger jl
        LEFT JOIN trends t ON t.id=jl.trend_id
        LEFT JOIN theses th ON th.id=jl.thesis_id
        ORDER BY CASE WHEN jl.reviewed_at IS NULL THEN 0 ELSE 1 END,
                 COALESCE(jl.review_at,'9999-12-31') ASC,
                 jl.created_at DESC
        """
    ).fetchall()
    now=datetime.now(timezone.utc)
    result=[]
    for row in rows:
        item=dict(row)
        if item.get("reviewed_at"):
            item["review_status"]="REVIEWED"
        elif item.get("review_at"):
            try:
                due=datetime.fromisoformat(str(item["review_at"]).replace("Z","+00:00"))
                if due.tzinfo is None:
                    due=due.replace(tzinfo=timezone.utc)
                days=(due-now).total_seconds()/86400
                item["review_status"]="DUE" if days<=0 else "UPCOMING" if days<=30 else "PENDING"
            except ValueError:
                item["review_status"]="PENDING"
        else:
            item["review_status"]="PENDING"
        result.append(item)
    return result
