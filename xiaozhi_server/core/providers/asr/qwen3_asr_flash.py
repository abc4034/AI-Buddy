import os
from collections.abc import Mapping
from typing import List, Optional, Tuple

import dashscope

from core.buddy.provider_errors import ASRProviderFailure
from core.providers.asr.base import ASRProviderBase
from core.providers.asr.dto.dto import InterfaceType


_MISSING = object()


class ASRProvider(ASRProviderBase):
    def __init__(self, config: dict, delete_audio_file: bool):
        super().__init__()
        self.interface_type = InterfaceType.NON_STREAM
        self.api_key = config.get("api_key")
        self.model_name = config.get("model_name", "qwen3-asr-flash")
        self.base_url = config.get("base_url")
        self.timeout_seconds = float(config.get("timeout_seconds", 30))
        self.output_dir = config.get("output_dir", "./audio_output")
        self.delete_audio_file = delete_audio_file
        self.enable_lid = config.get("enable_lid", True)
        self.enable_itn = config.get("enable_itn", True)
        self.language = config.get("language")
        self.context = config.get("context", "")

        if not self.api_key or not self.model_name or not self.base_url or self.timeout_seconds <= 0:
            raise ValueError("Qwen ASR requires api_key, model_name, base_url, and a positive timeout_seconds.")
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

        messages = [{"role": "user", "content": [{"audio": artifacts.temp_path}]}]
        if self.context:
            messages.insert(0, {"role": "system", "content": [{"text": self.context}]})
        asr_options = {"enable_lid": self.enable_lid, "enable_itn": self.enable_itn}
        if self.language:
            asr_options["language"] = self.language

        try:
            response = dashscope.MultiModalConversation.call(
                model=self.model_name,
                messages=messages,
                api_key=self.api_key,
                base_address=self.base_url,
                timeout=self.timeout_seconds,
                result_format="message",
                asr_options=asr_options,
                stream=True,
            )
            text = self._collect_transcript(response)
        except ASRProviderFailure:
            raise
        except Exception as exc:
            raise ASRProviderFailure(self._failure_code(exc)) from None

        return text, artifacts.file_path

    def _collect_transcript(self, response) -> str:
        full_text = ""
        try:
            for chunk in response:
                status_code = self._value(chunk, "status_code")
                if status_code is not _MISSING and int(status_code) >= 400:
                    raise ASRProviderFailure(
                        "authentication" if int(status_code) in (401, 403) else "service",
                        provider_status_code=int(status_code),
                    )
                content = self._content(chunk)
                if content is None or content == "":
                    continue
                if isinstance(content, str):
                    full_text = content.strip()
                    continue
                if not isinstance(content, list):
                    raise ASRProviderFailure("malformed_response")
                if not content:
                    continue
                first = content[0]
                text = self._value(first, "text")
                if not isinstance(text, str):
                    raise ASRProviderFailure("malformed_response")
                full_text = text.strip()
        except ASRProviderFailure:
            raise
        except Exception:
            raise ASRProviderFailure("malformed_response") from None
        return full_text

    @staticmethod
    def _value(source, key: str):
        if isinstance(source, Mapping):
            return source.get(key, _MISSING)
        value = getattr(source, key, _MISSING)
        if value is not _MISSING:
            return value
        try:
            return source[key]
        except (KeyError, TypeError, AttributeError):
            return _MISSING

    def _content(self, chunk):
        output = self._value(chunk, "output")
        choices = self._value(output, "choices") if output is not _MISSING else _MISSING
        if not isinstance(choices, list) or not choices:
            raise ASRProviderFailure("malformed_response")
        message = self._value(choices[0], "message")
        content = self._value(message, "content") if message is not _MISSING else _MISSING
        if content is _MISSING:
            raise ASRProviderFailure("malformed_response")
        return content

    @staticmethod
    def _failure_code(exc: Exception) -> str:
        if isinstance(exc, TimeoutError):
            return "timeout"
        status_code = getattr(exc, "status_code", None) or getattr(exc, "http_status_code", None)
        if status_code in (401, 403):
            return "authentication"
        if status_code is not None:
            return "service"
        message = str(exc).lower()
        if "timeout" in message or "timed out" in message:
            return "timeout"
        if any(token in message for token in ("unauthorized", "authentication", "api key", "api_key", "forbidden")):
            return "authentication"
        return "service"
