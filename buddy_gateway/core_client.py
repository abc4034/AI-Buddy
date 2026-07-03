from __future__ import annotations

from typing import Any

import httpx


class BuddyCoreError(RuntimeError):
    pass


class BuddyCoreClient:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8010",
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    async def complete_debug_text(
        self,
        *,
        device_id: str | None,
        client_id: str | None,
        session_id: str,
        text: str,
    ) -> str:
        metadata: dict[str, Any] = {
            "device_id": device_id,
            "client_id": client_id,
            "session_id": session_id,
            "source": "buddy_gateway_debug",
        }
        payload = {
            "stream": False,
            "messages": [{"role": "user", "content": text}],
            "metadata": metadata,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.post("/v1/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise BuddyCoreError(f"Buddy Core request failed: {exc}") from exc

        if response.status_code >= 400:
            raise BuddyCoreError(f"Buddy Core returned HTTP {response.status_code}: {response.text}")

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise BuddyCoreError("Buddy Core returned an invalid chat completion payload") from exc

        if not isinstance(content, str):
            raise BuddyCoreError("Buddy Core returned a non-text assistant response")
        return content
