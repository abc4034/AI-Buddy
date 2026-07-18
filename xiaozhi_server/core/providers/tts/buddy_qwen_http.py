import asyncio
import base64
import binascii
import math
from pathlib import Path

import requests

from core.providers.tts.base import TTSProviderBase
from core.buddy.provider_errors import TTSProviderFailure


class TTSProviderError(TTSProviderFailure):
    pass


class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        self.api_key = str(config.get("api_key") or "").strip()
        self.api_url = _generation_url(config.get("api_url") or config.get("base_url") or "")
        self.model = str(config.get("model") or "").strip()
        self.voice = str(config.get("voice") or "").strip()
        self.language = str(config.get("language") or "auto").strip()
        self.timeout_seconds = _positive_timeout(config.get("timeout_seconds", config.get("tts_timeout", 15)))
        self.audio_file_type = str(config.get("format") or "wav").strip().lower()

        missing = [name for name, value in (("api_key", self.api_key), ("model", self.model), ("voice", self.voice)) if not value]
        if missing:
            raise ValueError(f"buddy_qwen_http requires {', '.join(missing)}")

    async def text_to_speak(self, text, output_file):
        return await asyncio.to_thread(self._synthesize, text, output_file)

    def _synthesize(self, text, output_file):
        clean_text = str(text or "").strip()
        if not clean_text:
            raise ValueError("TTS text must be a non-empty string")

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "input": {
                "text": clean_text,
                "voice": self.voice,
                "language_type": _language_type(self.language, clean_text),
            },
        }

        try:
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=self.timeout_seconds)
        except requests.Timeout as exc:
            raise TTSProviderError("tts_timeout", "TTS request timeout") from exc
        except requests.RequestException as exc:
            raise TTSProviderError("tts_failed", "TTS service request failed") from exc

        _raise_for_status(response, "TTS synthesis")
        audio = _audio_from_response(response, self.timeout_seconds)
        if output_file:
            Path(output_file).write_bytes(audio)
            return None
        return audio


def _generation_url(url):
    clean = str(url or "").strip().rstrip("/")
    if not clean:
        raise ValueError("buddy_qwen_http requires api_url")
    if clean.endswith("/services/aigc/multimodal-generation/generation"):
        return clean
    if clean.endswith("/api/v1"):
        return f"{clean}/services/aigc/multimodal-generation/generation"
    return f"{clean}/api/v1/services/aigc/multimodal-generation/generation"


def _positive_timeout(value):
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("buddy_qwen_http requires a positive timeout_seconds") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("buddy_qwen_http requires a positive timeout_seconds")
    return timeout


def _language_type(language, text):
    normalized = str(language or "auto").strip()
    if normalized.casefold() != "auto":
        return normalized
    return "Chinese" if any(0x4E00 <= ord(character) <= 0x9FFF for character in text) else "English"


def _raise_for_status(response, action):
    if response.status_code < 400:
        return
    if response.status_code in (401, 403):
        raise TTSProviderError("tts_authentication", f"{action} authentication failed")
    raise TTSProviderError("tts_failed", f"{action} service failed")


def _audio_from_response(response, timeout_seconds):
    content_type = str(response.headers.get("content-type") or "").casefold()
    if content_type.startswith("audio/"):
        return response.content

    try:
        payload = response.json()
    except ValueError as exc:
        raise TTSProviderError("tts_malformed_response", "TTS synthesis returned malformed JSON") from exc
    if not isinstance(payload, dict):
        raise TTSProviderError("tts_malformed_response", "TTS synthesis returned malformed JSON")

    audio = _audio_payload(payload)
    if not audio:
        raise TTSProviderError("tts_malformed_response", "TTS synthesis response did not contain audio")
    encoded = audio.get("data")
    if isinstance(encoded, str) and encoded.strip():
        try:
            return base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise TTSProviderError("tts_malformed_response", "TTS synthesis audio was malformed") from exc

    audio_url = _audio_url(audio, payload)
    if not audio_url:
        raise TTSProviderError("tts_malformed_response", "TTS synthesis response did not contain audio")
    try:
        download = requests.get(audio_url, timeout=timeout_seconds)
    except requests.Timeout as exc:
        raise TTSProviderError("tts_timeout", "TTS audio download timeout") from exc
    except requests.RequestException as exc:
        raise TTSProviderError("tts_failed", "TTS audio download failed") from exc
    _raise_for_status(download, "TTS audio download")
    return download.content


def _audio_payload(payload):
    output = payload.get("output")
    if isinstance(output, dict):
        audio = output.get("audio")
        if isinstance(audio, dict):
            return audio
        if isinstance(output.get("url"), str):
            return {"url": output["url"]}
    audio = payload.get("audio")
    if isinstance(audio, dict):
        return audio
    if isinstance(payload.get("url"), str):
        return {"url": payload["url"]}
    return None


def _audio_url(audio, payload):
    output = payload.get("output")
    for source in (audio, output if isinstance(output, dict) else {}, payload):
        for key in ("url", "audio_url"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None
