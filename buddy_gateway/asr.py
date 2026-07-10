from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


DEFAULT_ASR_MODEL = "qwen3-asr-flash-2025-09-08"
IMPLEMENTED_ASR_PROVIDERS = ("disabled", "http_file", "qwen_chat_audio")
PLANNED_ASR_PROVIDERS = ("local_model", "asr_server", "streaming_asr")


class ASRProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ASRAudioArtifact:
    session_id: str
    turn_id: str
    device_id: str | None
    client_id: str | None
    opus_frames: list[bytes]
    wav_bytes: bytes
    wav_path: str | None
    sample_rate: int
    channels: int
    frame_duration_ms: int


@dataclass(frozen=True)
class ASRResult:
    text: str
    provider: str
    raw_response: dict[str, Any] | None = None


class ASRProvider(Protocol):
    provider_name: str

    async def transcribe(self, artifact: ASRAudioArtifact) -> ASRResult:
        ...


class DisabledASRProvider:
    provider_name = "disabled"

    async def transcribe(self, artifact: ASRAudioArtifact) -> ASRResult:
        raise ASRProviderError("ASR provider is disabled")


class ASRProviderNotImplemented:
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    async def transcribe(self, artifact: ASRAudioArtifact) -> ASRResult:
        raise ASRProviderError(f"ASR provider '{self.provider_name}' is planned but not implemented")


class HttpFileASRProvider:
    provider_name = "http_file"

    def __init__(
        self,
        *,
        url: str,
        api_key: str | None,
        model: str = DEFAULT_ASR_MODEL,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = _transcription_url(url)
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout
        self.transport = transport

    async def transcribe(self, artifact: ASRAudioArtifact) -> ASRResult:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        files = {
            "file": (
                f"{artifact.turn_id}.wav",
                artifact.wav_bytes,
                "audio/wav",
            )
        }
        data = {"model": self.model}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(self.url, headers=headers, data=data, files=files)
        except httpx.HTTPError as exc:
            raise ASRProviderError(f"ASR HTTP request failed: {exc}") from exc

        if response.status_code >= 400:
            raise ASRProviderError(f"ASR HTTP {response.status_code}: {response.text}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ASRProviderError("ASR HTTP response was not valid JSON") from exc

        text = payload.get("text")
        if not isinstance(text, str):
            raise ASRProviderError("ASR HTTP response did not contain string field 'text'")
        return ASRResult(text=text, provider=self.provider_name, raw_response=payload)


class QwenChatAudioASRProvider:
    provider_name = "qwen_chat_audio"

    def __init__(
        self,
        *,
        url: str,
        api_key: str | None,
        model: str = DEFAULT_ASR_MODEL,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = _chat_completions_url(url)
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout
        self.transport = transport

    async def transcribe(self, artifact: ASRAudioArtifact) -> ASRResult:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data_uri = "data:audio/wav;base64," + base64.b64encode(artifact.wav_bytes).decode("ascii")
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": data_uri,
                            },
                        }
                    ],
                }
            ],
            "stream": False,
            "asr_options": {
                "enable_itn": False,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(self.url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise ASRProviderError(f"Qwen ASR HTTP request failed: {exc}") from exc

        if response.status_code >= 400:
            raise ASRProviderError(f"Qwen ASR HTTP {response.status_code}: {response.text}")

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ASRProviderError("Qwen ASR response did not contain choices[0].message.content") from exc

        if not isinstance(content, str):
            raise ASRProviderError("Qwen ASR response content was not text")
        return ASRResult(text=content, provider=self.provider_name, raw_response=data)


def build_asr_provider(settings: Any, *, transport: httpx.AsyncBaseTransport | None = None) -> ASRProvider:
    provider_name = str(getattr(settings, "asr_provider", "disabled") or "disabled").strip().lower()
    if provider_name == "disabled":
        return DisabledASRProvider()
    if provider_name == "http_file":
        return HttpFileASRProvider(
            url=getattr(settings, "asr_http_url", ""),
            api_key=getattr(settings, "asr_api_key", ""),
            model=getattr(settings, "asr_model", DEFAULT_ASR_MODEL),
            timeout=float(getattr(settings, "asr_timeout_seconds", 60.0)),
            transport=transport,
        )
    if provider_name == "qwen_chat_audio":
        return QwenChatAudioASRProvider(
            url=getattr(settings, "asr_http_url", ""),
            api_key=getattr(settings, "asr_api_key", ""),
            model=getattr(settings, "asr_model", DEFAULT_ASR_MODEL),
            timeout=float(getattr(settings, "asr_timeout_seconds", 60.0)),
            transport=transport,
        )
    if provider_name in PLANNED_ASR_PROVIDERS:
        return ASRProviderNotImplemented(provider_name)
    raise ASRProviderError(f"Unknown ASR provider '{provider_name}'")


def asr_provider_catalog(settings: Any) -> dict[str, Any]:
    return {
        "current_provider": str(getattr(settings, "asr_provider", "disabled") or "disabled"),
        "implemented": list(IMPLEMENTED_ASR_PROVIDERS),
        "planned": list(PLANNED_ASR_PROVIDERS),
        "http_file": {
            "url": getattr(settings, "asr_http_url", ""),
            "model": getattr(settings, "asr_model", DEFAULT_ASR_MODEL),
            "api_key_configured": bool(getattr(settings, "asr_api_key", "")),
        },
        "qwen_chat_audio": {
            "url": getattr(settings, "asr_http_url", ""),
            "model": getattr(settings, "asr_model", DEFAULT_ASR_MODEL),
            "api_key_configured": bool(getattr(settings, "asr_api_key", "")),
        },
    }


def _transcription_url(url: str) -> str:
    clean = (url or "").strip().rstrip("/")
    if not clean:
        raise ASRProviderError("ASR HTTP URL is required for http_file provider")
    if clean.endswith("/audio/transcriptions"):
        return clean
    if clean.endswith("/v1"):
        return f"{clean}/audio/transcriptions"
    return f"{clean}/v1/audio/transcriptions"


def _chat_completions_url(url: str) -> str:
    clean = (url or "").strip().rstrip("/")
    if not clean:
        raise ASRProviderError("ASR HTTP URL is required for qwen_chat_audio provider")
    if clean.endswith("/chat/completions"):
        return clean
    if clean.endswith("/v1"):
        return f"{clean}/chat/completions"
    return f"{clean}/v1/chat/completions"
