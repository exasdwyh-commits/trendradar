from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import httpx


@dataclass(frozen=True)
class Slot:
    name: str
    base_url: str
    api_key: str
    model: str
    input_cny_per_million: float = 0.0
    output_cny_per_million: float = 0.0
    rolling_24h_call_limit: int = 0

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


def load_slot(name: str) -> Slot:
    prefix = name.upper()
    return Slot(
        name=name,
        base_url=(os.getenv(f"{prefix}_BASE_URL") or os.getenv("MODEL_BASE_URL","")).rstrip("/"),
        api_key=os.getenv(f"{prefix}_API_KEY") or os.getenv("MODEL_API_KEY",""),
        model=os.getenv(f"{prefix}_MODEL", ""),
        input_cny_per_million=float(os.getenv(f"{prefix}_INPUT_CNY_PER_M", "0") or 0),
        output_cny_per_million=float(os.getenv(f"{prefix}_OUTPUT_CNY_PER_M", "0") or 0),
        rolling_24h_call_limit=int(os.getenv(f"{prefix}_24H_CALL_LIMIT", "0") or 0),
    )


def slot_enabled(name: str) -> bool:
    return load_slot(name).enabled


def slot_status() -> dict[str, dict]:
    names = ["FAST_MODEL","COGNITION_MODEL","RESEARCH_MODEL","WRITING_MODEL","CRITIC_MODEL"]
    result = {}
    for name in names:
        slot = load_slot(name)
        result[name] = {
            "enabled": slot.enabled,
            "model": slot.model or None,
            "input_cny_per_million": slot.input_cny_per_million or None,
            "output_cny_per_million": slot.output_cny_per_million or None,
            "rolling_24h_call_limit": slot.rolling_24h_call_limit or None,
        }
    return result



def _estimate_cost_cny(slot: Slot, input_tokens: int, output_tokens: int) -> float:
    return round(
        max(0,input_tokens) / 1_000_000 * max(0.0,slot.input_cny_per_million)
        + max(0,output_tokens) / 1_000_000 * max(0.0,slot.output_cny_per_million),
        6,
    )


def _rolling_24h_usage(conn: sqlite3.Connection | None, slot_name: str | None = None) -> dict:
    if conn is None:
        return {"calls":0,"cost":0.0}
    if slot_name:
        row = conn.execute(
            """
            SELECT COUNT(*) calls,COALESCE(SUM(cost),0) cost
            FROM ai_runs
            WHERE run_at >= datetime('now','-24 hours') AND slot=? AND ok=1
            """,
            (slot_name,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT COUNT(*) calls,COALESCE(SUM(cost),0) cost
            FROM ai_runs
            WHERE run_at >= datetime('now','-24 hours') AND ok=1
            """
        ).fetchone()
    return {"calls":int(row["calls"] or 0),"cost":float(row["cost"] or 0.0)}


def _enforce_budget(conn: sqlite3.Connection | None, slot: Slot) -> None:
    if conn is None:
        return
    if slot.rolling_24h_call_limit > 0:
        usage = _rolling_24h_usage(conn,slot.name)
        if usage["calls"] >= slot.rolling_24h_call_limit:
            raise RuntimeError(
                f"{slot.name} rolling 24h call limit reached: "
                f"{usage['calls']}/{slot.rolling_24h_call_limit}"
            )
    global_budget = float(os.getenv("AI_24H_BUDGET_CNY","0") or 0)
    if global_budget > 0:
        usage = _rolling_24h_usage(conn)
        if usage["cost"] >= global_budget:
            raise RuntimeError(
                f"AI rolling 24h budget reached: ¥{usage['cost']:.4f}/¥{global_budget:.4f}"
            )


def _json_from_text(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _retry_after_seconds(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        value = response.headers.get("Retry-After")
        if value:
            try:
                return max(0.0, min(30.0, float(value)))
            except ValueError:
                try:
                    dt = parsedate_to_datetime(value)
                    return max(0.0, min(30.0, dt.timestamp() - time.time()))
                except (TypeError, ValueError, OverflowError):
                    pass
    return min(8.0, float(2 ** max(0, attempt - 1)))


def _log_ai_run(
    conn: sqlite3.Connection | None,
    *,
    task: str,
    slot: str,
    model: str | None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: int = 0,
    ok: bool,
    error: str | None = None,
    attempts: int = 1,
    retries: int = 0,
    http_status: int | None = None,
    cost: float = 0.0,
) -> None:
    if conn is None:
        return
    try:
        conn.execute(
            """
            INSERT INTO ai_runs(
              task,slot,model,input_tokens,output_tokens,cost,duration_ms,ok,error,
              attempts,retries,http_status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                task,slot,model,input_tokens,output_tokens,cost,duration_ms,
                1 if ok else 0,error[:1000] if error else None,attempts,retries,http_status,
            ),
        )
        conn.commit()
    except sqlite3.Error:
        # Observability must never break the product path.
        pass


def chat_json(
    slot_name: str,
    system: str,
    user: str,
    timeout: float = 90,
    *,
    conn: sqlite3.Connection | None = None,
    task: str | None = None,
    max_attempts: int = 3,
):
    """
    OpenAI-compatible JSON call with bounded retry and durable telemetry.

    Retry only on transient failures: 429 and 5xx, transport errors, or malformed
    JSON. A 400 response caused by unsupported response_format is retried once
    immediately without response_format and does not consume a transient retry.
    """
    slot = load_slot(slot_name)
    task_name = task or slot_name.lower()
    if not slot.enabled:
        error = f"model slot not configured: {slot_name}"
        _log_ai_run(
            conn,task=task_name,slot=slot_name,model=slot.model or None,
            ok=False,error=error,attempts=0,retries=0,
        )
        raise RuntimeError(error)

    try:
        _enforce_budget(conn,slot)
    except RuntimeError as exc:
        _log_ai_run(
            conn,task=task_name,slot=slot_name,model=slot.model or None,
            ok=False,error=str(exc),attempts=0,retries=0,
        )
        raise

    url = slot.base_url
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"

    base_payload = {
        "model": slot.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {"Authorization": f"Bearer {slot.api_key}", "Content-Type": "application/json"}

    started = time.perf_counter()
    last_error: Exception | None = None
    last_status: int | None = None
    attempts = 0
    retries = 0

    with httpx.Client(timeout=timeout) as client:
        for attempt in range(1, max(1, max_attempts) + 1):
            attempts = attempt
            response: httpx.Response | None = None
            try:
                payload = dict(base_payload)
                response = client.post(url, headers=headers, json=payload)
                last_status = response.status_code

                # Some OpenAI-compatible gateways reject response_format.
                if response.status_code == 400 and "response_format" in payload:
                    payload.pop("response_format", None)
                    response = client.post(url, headers=headers, json=payload)
                    last_status = response.status_code

                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"transient model HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )

                response.raise_for_status()
                data = response.json()
                text = data["choices"][0]["message"]["content"]
                parsed = _json_from_text(text)
                usage = data.get("usage") or {}
                input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
                output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
                cost = _estimate_cost_cny(slot,input_tokens,output_tokens)
                duration_ms = int((time.perf_counter() - started) * 1000)
                _log_ai_run(
                    conn,
                    task=task_name,
                    slot=slot_name,
                    model=slot.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost=cost,
                    duration_ms=duration_ms,
                    ok=True,
                    attempts=attempts,
                    retries=retries,
                    http_status=last_status,
                )
                return parsed, slot.model

            except (httpx.TransportError, httpx.HTTPStatusError, json.JSONDecodeError, KeyError, TypeError) as exc:
                last_error = exc
                transient = (
                    isinstance(exc, (httpx.TransportError, json.JSONDecodeError, KeyError, TypeError))
                    or last_status == 429
                    or (last_status is not None and last_status >= 500)
                )
                if not transient or attempt >= max_attempts:
                    break
                retries += 1
                time.sleep(_retry_after_seconds(response, attempt))

    duration_ms = int((time.perf_counter() - started) * 1000)
    error_text = str(last_error or "model call failed")
    _log_ai_run(
        conn,
        task=task_name,
        slot=slot_name,
        model=slot.model,
        duration_ms=duration_ms,
        ok=False,
        error=error_text,
        attempts=attempts,
        retries=retries,
        http_status=last_status,
    )
    raise RuntimeError(
        f"{task_name} failed after {attempts} attempt(s)"
        + (f" (HTTP {last_status})" if last_status else "")
        + f": {error_text}"
    )
