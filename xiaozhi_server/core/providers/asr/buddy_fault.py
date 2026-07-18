from __future__ import annotations

import math
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from core.buddy.provider_errors import ASRProviderFailure
from core.providers.asr.base import ASRProviderBase
from core.providers.asr.dto.dto import InterfaceType


class ASRProvider(ASRProviderBase):
    """Loopback-only ASR provider used by deterministic recovery tests."""

    def __init__(self, config: dict, delete_audio_file: bool):
        super().__init__()
        self.interface_type = InterfaceType.NON_STREAM
        self.delete_audio_file = delete_audio_file
        self.base_url = str(config.get("base_url") or "").rstrip("/")
        self.timeout_seconds = float(config.get("timeout_seconds", 1))
        parsed = urlparse(self.base_url)
        if parsed.hostname not in {"127.0.0.1", "::1"} or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("buddy_fault requires a loopback base_url and positive timeout_seconds")

    async def speech_to_text(
        self, opus_data: List[bytes], session_id: str, artifacts=None
    ) -> Tuple[Optional[str], Optional[str]]:
        del opus_data
        file_path = None if artifacts is None else artifacts.file_path
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(f"{self.base_url}/asr", json={"session_id": session_id})
        except httpx.TimeoutException:
            raise ASRProviderFailure("asr_timeout") from None
        except httpx.HTTPError:
            raise ASRProviderFailure("asr_failed") from None
        if response.status_code >= 400:
            raise ASRProviderFailure("asr_failed")
        try:
            payload = response.json()
            text = payload["text"]
        except (KeyError, TypeError, ValueError):
            raise ASRProviderFailure("asr_malformed_response") from None
        if not isinstance(text, str):
            raise ASRProviderFailure("asr_malformed_response")
        return text, file_path
