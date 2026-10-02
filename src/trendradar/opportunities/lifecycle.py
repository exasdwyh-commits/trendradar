"""Opportunity lifecycle: discovered → watching → promising → researching → validated → building; rejected/archived from anywhere."""

from __future__ import annotations

import sqlite3

from ..core.errors import NotFound, ValidationFailed
from ..core.timeutil import iso, utcnow

STATUSES = [
    "discovered",
    "watching",
    "promising",
    "researching",
    "validated",
    "building",
    "rejected",
    "archived",
]
FORWARD = {
    "discovered": {"watching", "promising"},
    "watching": {"promising", "researching"},
    "promising": {"researching", "validated"},
    "researching": {"validated", "promising"},
    "validated": {"building", "researching"},
    "building": set(),
}
TERMINAL = {"rejected", "archived"}


def allowed_transitions(status: str) -> set[str]:
    if status in TERMINAL:
        return {"discovered"}  # un-archive
    return FORWARD.get(status, set()) | TERMINAL


def set_status(
    conn: sqlite3.Connection, opportunity_id: str, to_status: str, *, note: str | None = None
) -> dict:
    row = conn.execute("SELECT status FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
    if row is None:
        raise NotFound("opportunity not found", details={"id": opportunity_id})
    if to_status not in STATUSES:
        raise ValidationFailed(f"unknown status {to_status}")
    if to_status not in allowed_transitions(row["status"]) and to_status != row["status"]:
        raise ValidationFailed(
            f"cannot move from {row['status']} to {to_status}",
            details={"allowed": sorted(allowed_transitions(row["status"]))},
        )
    conn.execute(
        "UPDATE opportunities SET status=?, updated_at=? WHERE id=?",
        (to_status, iso(utcnow()), opportunity_id),
    )
    conn.execute(
        "INSERT INTO opportunity_status_log(opportunity_id,from_status,to_status,note) VALUES(?,?,?,?)",
        (opportunity_id, row["status"], to_status, note),
    )
    conn.commit()
    return {"id": opportunity_id, "from": row["status"], "to": to_status}
