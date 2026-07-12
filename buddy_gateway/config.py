from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field

from buddy_gateway.asr import DEFAULT_ASR_MODEL
from buddy_gateway.tts import DEFAULT_TTS_MODEL, DEFAULT_TTS_VOICE


WEBSOCKET_PATH = "/xiaozhi/v1/"


def require_positive_frame_count(name: str, value: int) -> int:
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class GatewaySettings:
    host: str = "0.0.0.0"
    http_port: int = 8003
    websocket_port: int = 8000
    advertise_host: str | None = None
    buddy_core_base_url: str = "http://127.0.0.1:8010"
    session_history_limit: int = 50
    audio_artifact_dir: str = "data/gateway_audio"
    audio_session_limit: int = 20
    vad_provider: str = "silero"
    vad_threshold: float = 0.5
    vad_threshold_low: float = 0.2
    vad_min_silence_ms: int = 1000
    vad_window_size: int = 5
    vad_voice_votes: int = 3
    vad_preroll_frames: int = 10
    vad_min_turn_frames: int = 16
    asr_provider: str = "disabled"
    asr_http_url: str = field(default_factory=lambda: os.environ.get("ASR_HTTP_URL", ""))
    asr_model: str = field(default_factory=lambda: os.environ.get("ASR_MODEL", DEFAULT_ASR_MODEL))
    asr_api_key: str = field(default_factory=lambda: os.environ.get("ASR_API_KEY", ""))
    asr_timeout_seconds: float = 60.0
    send_stt_to_device: bool = False
    tts_provider: str = "disabled"
    tts_http_url: str = field(default_factory=lambda: os.environ.get("TTS_HTTP_URL", ""))
    tts_model: str = field(default_factory=lambda: os.environ.get("TTS_MODEL", DEFAULT_TTS_MODEL))
    tts_api_key: str = field(default_factory=lambda: os.environ.get("TTS_API_KEY", ""))
    tts_voice: str = field(default_factory=lambda: os.environ.get("TTS_VOICE", DEFAULT_TTS_VOICE))
    tts_language: str = field(default_factory=lambda: os.environ.get("TTS_LANGUAGE", "auto"))
    tts_timeout_seconds: float = 60.0
    tts_frame_delay_ms: int = 60

    def __post_init__(self) -> None:
        require_positive_frame_count("vad_preroll_frames", self.vad_preroll_frames)
        require_positive_frame_count("vad_min_turn_frames", self.vad_min_turn_frames)

    def advertised_host(self) -> str:
        if self.advertise_host:
            return self.advertise_host
        if self.host and self.host not in {"0.0.0.0", "::"}:
            return self.host
        return _detect_lan_ip() or "127.0.0.1"

    def websocket_url(self) -> str:
        return f"ws://{self.advertised_host()}:{self.websocket_port}{WEBSOCKET_PATH}"


def _detect_lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    except OSError:
        return None
