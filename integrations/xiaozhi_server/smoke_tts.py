from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_ROOT / "xiaozhi_server"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from core.handle.sendAudioHandle import sendAudioMessage, send_tts_message
from core.providers.tts.dto.dto import SentenceType
from core.utils.tts import create_instance


@dataclass(frozen=True)
class SmokeResult:
    provider_type: str
    opus_frame_count: int
    tts_start_count: int


class _Logger:
    def bind(self, **_):
        return self

    def debug(self, *_):
        return None

    def info(self, *_):
        return None

    def error(self, *_):
        return None


class _WebSocket:
    def __init__(self) -> None:
        self.messages: list[str | bytes] = []

    async def send(self, message: str | bytes) -> None:
        self.messages.append(message)


class _Connection:
    def __init__(self, config: dict, provider) -> None:
        self.config = dict(config, tts_audio_send_delay=1)
        self.tts = provider
        self.websocket = _WebSocket()
        self.logger = _Logger()
        self.session_id = "xiaozhi-tts-smoke"
        self.sentence_id = "xiaozhi-tts-smoke-sentence"
        self.sample_rate = 16000
        self.client_abort = False
        self.client_aec = False
        self.client_is_speaking = True
        self.last_activity_time = 0
        self.conn_from_mqtt_gateway = False
        self.calling = True
        self.close_after_chat = False

    def clearSpeakStatus(self) -> None:
        self.client_is_speaking = False


@contextmanager
def _runtime_working_directory() -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(RUNTIME_DIR)
    try:
        yield
    finally:
        os.chdir(previous)


def _load_selected_provider(config_path: Path) -> tuple[dict, str, dict]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Rendered XiaoZhi config must be a mapping.")
    selected = config.get("selected_module") or {}
    if selected.get("TTS") != "BuddyQwenTTS":
        raise ValueError("Rendered XiaoZhi config must select BuddyQwenTTS.")
    provider_config = (config.get("TTS") or {}).get("BuddyQwenTTS") or {}
    provider_type = provider_config.get("type")
    if provider_type != "buddy_qwen_http":
        raise ValueError("BuddyQwenTTS.type must be buddy_qwen_http.")
    return config, provider_type, provider_config


async def _send_through_native_path(connection: _Connection, opus_frames: list[bytes], text: str) -> None:
    await send_tts_message(connection, "start")
    await sendAudioMessage(connection, SentenceType.FIRST, opus_frames, text)
    controller = getattr(connection, "audio_rate_controller", None)
    if controller:
        controller.stop_sending()
        await asyncio.sleep(0)


def run_smoke(config_path: Path, text: str) -> SmokeResult:
    clean_text = str(text or "").strip()
    if not clean_text:
        raise ValueError("Smoke text must be non-empty.")
    config, provider_type, provider_config = _load_selected_provider(Path(config_path))

    with _runtime_working_directory():
        provider = create_instance(provider_type, provider_config, True)
        connection = _Connection(config, provider)
        provider.conn = connection
        opus_frames = provider.to_tts(clean_text)
        if not opus_frames or not all(isinstance(frame, bytes) and frame for frame in opus_frames):
            raise RuntimeError("TTS provider did not produce non-empty Opus frames.")
        asyncio.run(_send_through_native_path(connection, list(opus_frames), clean_text))

    binary_frames = [message for message in connection.websocket.messages if isinstance(message, bytes) and message]
    control_messages = [
        json.loads(message)
        for message in connection.websocket.messages
        if isinstance(message, str)
    ]
    tts_starts = [message for message in control_messages if message.get("type") == "tts" and message.get("state") == "start"]
    if not binary_frames or not tts_starts:
        raise RuntimeError("Native XiaoZhi send path did not emit TTS start and Opus frames.")
    return SmokeResult(provider_type, len(binary_frames), len(tts_starts))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--text", required=True)
    args = parser.parse_args()
    result = run_smoke(args.config, args.text)
    print(
        f"XiaoZhi TTS smoke passed: provider={result.provider_type} "
        f"tts_start={result.tts_start_count} opus_frames={result.opus_frame_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
