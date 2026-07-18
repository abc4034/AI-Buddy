import base64
import math
import os
from pathlib import Path
from typing import List, Optional, Tuple

import httpx

from core.buddy.provider_errors import ASRProviderFailure
from core.providers.asr.base import ASRProviderBase
from core.providers.asr.dto.dto import InterfaceType


class ASRProvider(ASRProviderBase):
    def __init__(self, config: dict, delete_audio_file: bool):
        super().__init__()
        self.interface_type = InterfaceType.NON_STREAM
        self.api_key = config.get("api_key")
        self.model_name = config.get("model_name")
        self.base_url = config.get("base_url")
        self.timeout_seconds = float(config.get("timeout_seconds", 30))
        self.output_dir = config.get("output_dir", "./audio_output")
        self.delete_audio_file = delete_audio_file

        if (
            not self.api_key
            or not self.model_name
            or not self.base_url
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("Buddy Qwen ASR requires api_key, model_name, base_url, and a positive timeout_seconds.")
        os.makedirs(self.output_dir, exist_ok=True)

    def prefers_temp_file(self) -> bool:
        return True

    def requires_file(self) -> bool:
        return True

    async def speech_to_text(
        self, opus_data: List[bytes], session_id: str, artifacts=None
    ) -> Tuple[Optional[str], Optional[str]]:
        del opus_data, session_id
        if artifacts is None or not artifacts.temp_path:
            return "", None if artifacts is None else artifacts.file_path

        try:
            audio_data = Path(artifacts.temp_path).read_bytes()
            response = await self._request(audio_data)
        except ASRProviderFailure:
            raise
        except (OSError, httpx.TimeoutException):
            raise ASRProviderFailure("timeout") from None
        except httpx.HTTPError:
            raise ASRProviderFailure("service") from None

        if response.status_code >= 400:
            raise ASRProviderFailure(
                "authentication" if response.status_code in (401, 403) else "service",
                provider_status_code=response.status_code,
            )
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError, ValueError):
            raise ASRProviderFailure("malformed_response") from None
        if not isinstance(content, str):
            raise ASRProviderFailure("malformed_response")
        return content.strip(), artifacts.file_path

    async def _request(self, audio_data: bytes):
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        data_uri = "data:audio/wav;base64," + base64.b64encode(audio_data).decode("ascii")
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "input_audio", "input_audio": {"data": data_uri}}],
                }
            ],
            "stream": False,
            "asr_options": {"enable_itn": False},
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            return await client.post(self._chat_completions_url(), headers=headers, json=payload)

    def _chat_completions_url(self) -> str:
        base_url = self.base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        if base_url.endswith("/v1"):
            return base_url + "/chat/completions"
        return base_url + "/v1/chat/completions"
