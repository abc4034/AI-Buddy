from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, AsyncIterator, Protocol

import httpx

from buddy_brain.prompting import detect_language


DEFAULT_TTS_MODEL = "qwen3-tts-instruct-flash"
DEFAULT_TTS_VOICE = "Cherry"
IMPLEMENTED_TTS_PROVIDERS = ("disabled", "dashscope_qwen_http")
PLANNED_TTS_PROVIDERS = ("local_model", "tts_server", "streaming_tts")


class TTSProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class TTSResult:
    audio_bytes: bytes
    audio_format: str
    provider: str
    sample_rate: int = 24000
    channels: int = 1
    raw_response: dict[str, Any] | None = None


@dataclass(frozen=True)
class TTSPcmChunk:
    pcm16_mono: bytes
    sample_rate: int
    is_final: bool


class TTSProvider(Protocol):
    provider_name: str

    async def synthesize(self, text: str) -> TTSResult:
        ...


class TTSStream(Protocol):
    async def push_text(self, text: str) -> None:
        ...

    async def finish(self) -> None:
        ...

    async def abort(self) -> None:
        ...

    async def close(self) -> None:
        ...

    def __aiter__(self) -> AsyncIterator[TTSPcmChunk]:
        ...


class StreamingTTSProvider(Protocol):
    provider_name: str

    async def open_stream(self, session_id: str) -> TTSStream:
        ...


class DisabledTTSProvider:
    provider_name = "disabled"

    async def synthesize(self, text: str) -> TTSResult:
        raise TTSProviderError("TTS provider is disabled")


class TTSProviderNotImplemented:
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    async def synthesize(self, text: str) -> TTSResult:
        raise TTSProviderError(f"TTS provider '{self.provider_name}' is planned but not implemented")


class StreamingTTSProviderNotImplemented(TTSProviderNotImplemented):
    async def open_stream(self, session_id: str) -> TTSStream:
        raise TTSProviderError(f"TTS provider '{self.provider_name}' is planned but not implemented")


class DashScopeQwenHttpTTSProvider:
    provider_name = "dashscope_qwen_http"

    def __init__(
        self,
        *,
        url: str,
        api_key: str | None,
        model: str = DEFAULT_TTS_MODEL,
        voice: str = DEFAULT_TTS_VOICE,
        language: str = "auto",
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = _generation_url(url)
        self.api_key = api_key or ""
        self.model = model or DEFAULT_TTS_MODEL
        self.voice = voice or DEFAULT_TTS_VOICE
        self.language = language or "auto"
        self.timeout = timeout
        self.transport = transport

    async def synthesize(self, text: str) -> TTSResult:
        if not self.api_key:
            raise TTSProviderError("TTS API key is required for dashscope_qwen_http provider")
        clean_text = text.strip()
        if not clean_text:
            raise TTSProviderError("TTS text must be a non-empty string")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": {
                "text": clean_text,
                "voice": self.voice,
            },
        }
        language_type = _language_type(self.language, clean_text)
        if language_type:
            payload["input"]["language_type"] = language_type

        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(self.url, headers=headers, json=payload)
                if response.status_code >= 400:
                    raise TTSProviderError(f"TTS HTTP {response.status_code}: {response.text}")
                if _is_audio_response(response):
                    return TTSResult(
                        audio_bytes=response.content,
                        audio_format=_format_from_content_type(response.headers.get("content-type", "")),
                        provider=self.provider_name,
                    )
                data = _response_json(response)
                audio_bytes, audio_format = await self._audio_from_payload(data, client)
        except httpx.HTTPError as exc:
            raise TTSProviderError(f"TTS HTTP request failed: {exc}") from exc

        return TTSResult(
            audio_bytes=audio_bytes,
            audio_format=audio_format,
            provider=self.provider_name,
            raw_response=data,
        )

    async def _audio_from_payload(self, data: dict[str, Any], client: httpx.AsyncClient) -> tuple[bytes, str]:
        audio = _audio_payload(data)
        if not audio:
            raise TTSProviderError("TTS response did not contain output.audio")

        encoded = audio.get("data")
        if isinstance(encoded, str) and encoded.strip():
            try:
                return base64.b64decode(encoded), str(audio.get("format") or "wav").lower()
            except ValueError as exc:
                raise TTSProviderError("TTS response audio.data was not valid base64") from exc

        url = _audio_url(audio, data)
        if not url:
            raise TTSProviderError("TTS response did not contain audio data or audio URL")
        response = await client.get(url)
        if response.status_code >= 400:
            raise TTSProviderError(f"TTS audio download HTTP {response.status_code}: {response.text}")
        return response.content, _format_from_url_or_content_type(url, response.headers.get("content-type", ""))


def build_tts_provider(settings: Any, *, transport: httpx.AsyncBaseTransport | None = None) -> TTSProvider:
    provider_name = str(getattr(settings, "tts_provider", "disabled") or "disabled").strip().lower()
    if provider_name == "disabled":
        return DisabledTTSProvider()
    if provider_name == "dashscope_qwen_http":
        return DashScopeQwenHttpTTSProvider(
            url=getattr(settings, "tts_http_url", ""),
            api_key=getattr(settings, "tts_api_key", ""),
            model=getattr(settings, "tts_model", DEFAULT_TTS_MODEL),
            voice=getattr(settings, "tts_voice", DEFAULT_TTS_VOICE),
            language=getattr(settings, "tts_language", "auto"),
            timeout=float(getattr(settings, "tts_timeout_seconds", 60.0)),
            transport=transport,
        )
    if provider_name == "streaming_tts":
        return StreamingTTSProviderNotImplemented(provider_name)
    if provider_name in PLANNED_TTS_PROVIDERS:
        return TTSProviderNotImplemented(provider_name)
    raise TTSProviderError(f"Unknown TTS provider '{provider_name}'")


def tts_provider_catalog(settings: Any) -> dict[str, Any]:
    return {
        "current_provider": str(getattr(settings, "tts_provider", "disabled") or "disabled"),
        "implemented": list(IMPLEMENTED_TTS_PROVIDERS),
        "planned": list(PLANNED_TTS_PROVIDERS),
        "dashscope_qwen_http": {
            "url": getattr(settings, "tts_http_url", ""),
            "model": getattr(settings, "tts_model", DEFAULT_TTS_MODEL),
            "voice": getattr(settings, "tts_voice", DEFAULT_TTS_VOICE),
            "language": getattr(settings, "tts_language", "auto"),
            "api_key_configured": bool(getattr(settings, "tts_api_key", "")),
        },
    }


def _generation_url(url: str) -> str:
    clean = (url or "").strip().rstrip("/")
    if not clean:
        raise TTSProviderError("TTS HTTP URL is required for dashscope_qwen_http provider")
    if clean.endswith("/services/aigc/multimodal-generation/generation"):
        return clean
    if clean.endswith("/api/v1"):
        return f"{clean}/services/aigc/multimodal-generation/generation"
    return f"{clean}/api/v1/services/aigc/multimodal-generation/generation"


def _language_type(language: str, text: str) -> str | None:
    normalized = (language or "auto").strip()
    if not normalized:
        return None
    if normalized.casefold() != "auto":
        return normalized
    detected = detect_language(text)
    if detected == "zh":
        return "Chinese"
    return "English"


def _response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise TTSProviderError("TTS HTTP response was not valid JSON") from exc
    if not isinstance(data, dict):
        raise TTSProviderError("TTS HTTP response was not a JSON object")
    return data


def _audio_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    output = data.get("output")
    if isinstance(output, dict):
        audio = output.get("audio")
        if isinstance(audio, dict):
            return audio
        if isinstance(output.get("url"), str):
            return {"url": output["url"]}
    if isinstance(data.get("audio"), dict):
        return data["audio"]
    if isinstance(data.get("url"), str):
        return {"url": data["url"]}
    return None


def _audio_url(audio: dict[str, Any], data: dict[str, Any]) -> str | None:
    for source in (audio, data.get("output") if isinstance(data.get("output"), dict) else {}, data):
        if not isinstance(source, dict):
            continue
        for key in ("url", "audio_url"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _is_audio_response(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    return content_type.startswith("audio/") or content_type in {"application/octet-stream"}


def _format_from_content_type(content_type: str) -> str:
    clean = content_type.split(";")[0].strip().lower()
    if clean.startswith("audio/"):
        return clean.split("/", 1)[1] or "wav"
    return "wav"


def _format_from_url_or_content_type(url: str, content_type: str) -> str:
    suffix = PurePosixPath(url.split("?", 1)[0]).suffix.lower().lstrip(".")
    if suffix:
        return suffix
    return _format_from_content_type(content_type)
