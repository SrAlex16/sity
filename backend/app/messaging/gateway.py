"""HTTP gateway — calls the Sity backend REST API."""
from __future__ import annotations

from typing import Any

import httpx

_PRESET_SPEAKER_SOURCE = "telegram"
_PRESET_SPEAKER_LABEL = "alex"


class SityGateway:
    """Async HTTP client wrapper for the Sity backend.

    All methods raise httpx.HTTPStatusError on non-2xx responses.
    """

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self._base = base_url.rstrip("/")

    async def send_message(self, text: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{self._base}/chat/message",
                json={"message": text},
            )
            r.raise_for_status()
            return r.json()

    async def get_capture_status(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{self._base}/debug/dataset-capture")
            r.raise_for_status()
            return r.json()

    async def set_preset(self, source: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.put(
                f"{self._base}/debug/dataset-capture",
                json={
                    "enabled": True,
                    "dataset_source": source,
                    "speaker_source": _PRESET_SPEAKER_SOURCE,
                    "speaker_label": _PRESET_SPEAKER_LABEL,
                    "dataset_eligible": True,
                    "dataset_tags": [],
                },
            )
            r.raise_for_status()
            return r.json()

    async def reset_personality(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{self._base}/settings/personality/reset")
            r.raise_for_status()
            return r.json()

    async def get_daily_tokens(self) -> int:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{self._base}/debug/budget")
            r.raise_for_status()
            data = r.json()
            return int(data.get("daily_used", 0))
