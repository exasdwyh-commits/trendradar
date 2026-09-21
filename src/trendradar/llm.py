from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Slot:
    name: str
    base_url: str
    api_key: str
    model: str

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


def load_slot(name: str) -> Slot:
    prefix = name.upper()
    return Slot(
        name=name,
        base_url=os.getenv(f"{prefix}_BASE_URL", "").rstrip("/"),
        api_key=os.getenv(f"{prefix}_API_KEY", ""),
        model=os.getenv(f"{prefix}_MODEL", ""),
    )


def _json_from_text(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^\`\`\`(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*\`\`\`$", "", text)
    return json.loads(text)


def chat_json(slot_name: str, system: str, user: str, timeout: float = 90) -> tuple[dict, str]:
    slot = load_slot(slot_name)
    if not slot.enabled:
        raise RuntimeError(f"model slot not configured: {slot_name}")
    url = slot.base_url
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    payload = {
        "model": slot.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {"Authorization": f"Bearer {slot.api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
    text = data["choices"][0]["message"]["content"]
    return _json_from_text(text), slot.model
