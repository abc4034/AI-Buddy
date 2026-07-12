from __future__ import annotations

import argparse
import asyncio
import logging
import os

import uvicorn

from buddy_gateway.app import create_http_app, create_websocket_app
from buddy_gateway.asr import build_asr_provider
from buddy_gateway.config import GatewaySettings, require_positive_frame_count
from buddy_gateway.core_client import BuddyCoreClient
from buddy_gateway.state import GatewayState
from buddy_gateway.tts import DEFAULT_TTS_MODEL, DEFAULT_TTS_VOICE, build_tts_provider


logger = logging.getLogger(__name__)


def _positive_frame_count(value: str) -> int:
    parsed = int(value)
    try:
        return require_positive_frame_count("frame count", parsed)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


async def serve(settings: GatewaySettings) -> None:
    state = GatewayState(session_history_limit=settings.session_history_limit)
    core_client = BuddyCoreClient(base_url=settings.buddy_core_base_url)
    asr_provider = build_asr_provider(settings)
    tts_provider = build_tts_provider(settings)
    http_server = uvicorn.Server(
        uvicorn.Config(
            create_http_app(
                settings=settings,
                state=state,
                core_client=core_client,
                asr_provider=asr_provider,
                tts_provider=tts_provider,
            ),
            host=settings.host,
            port=settings.http_port,
            log_level="info",
        )
    )
    websocket_server = uvicorn.Server(
        uvicorn.Config(
            create_websocket_app(
                settings=settings,
                state=state,
                core_client=core_client,
                asr_provider=asr_provider,
                tts_provider=tts_provider,
            ),
            host=settings.host,
            port=settings.websocket_port,
            log_level="info",
        )
    )

    logger.info("Buddy Device Gateway HTTP OTA: http://%s:%s/xiaozhi/ota/", settings.host, settings.http_port)
    logger.info("Buddy Device Gateway WebSocket: %s", settings.websocket_url())
    logger.info("Buddy Core base URL: %s", settings.buddy_core_base_url)
    logger.info("Gateway ASR provider: %s", settings.asr_provider)
    logger.info("Gateway TTS provider: %s", settings.tts_provider)
    await asyncio.gather(http_server.serve(), websocket_server.serve())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Buddy Device Gateway v0.5")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host for HTTP and WebSocket servers.")
    parser.add_argument("--http-port", type=int, default=8003, help="HTTP OTA port.")
    parser.add_argument("--websocket-port", type=int, default=8000, help="WebSocket port.")
    parser.add_argument(
        "--buddy-core-base-url",
        default="http://127.0.0.1:8010",
        help="Buddy Core base URL used for debug text loop requests.",
    )
    parser.add_argument(
        "--advertise-host",
        default=None,
        help="Host/IP returned in OTA websocket.url. Defaults to LAN auto-detection.",
    )
    parser.add_argument("--session-history-limit", type=int, default=50, help="Recent session history size.")
    parser.add_argument("--audio-artifact-dir", default="data/gateway_audio", help="Directory for captured Opus/WAV debug artifacts.")
    parser.add_argument("--audio-session-limit", type=int, default=20, help="Recent audio artifact session limit.")
    parser.add_argument("--vad-provider", default=os.environ.get("VAD_PROVIDER", "silero"), help="VAD provider: silero.")
    parser.add_argument("--vad-threshold", type=float, default=float(os.environ.get("VAD_THRESHOLD", "0.5")), help="VAD speech probability threshold.")
    parser.add_argument("--vad-threshold-low", type=float, default=float(os.environ.get("VAD_THRESHOLD_LOW", "0.2")), help="VAD low speech probability threshold.")
    parser.add_argument("--vad-min-silence-ms", type=int, default=int(os.environ.get("VAD_MIN_SILENCE_MS", "1000")), help="Silence required to end a speech turn.")
    parser.add_argument("--vad-window-size", type=int, default=int(os.environ.get("VAD_WINDOW_SIZE", "5")), help="VAD voting window size in frames.")
    parser.add_argument("--vad-voice-votes", type=int, default=int(os.environ.get("VAD_VOICE_VOTES", "3")), help="Voice votes required within the VAD window.")
    parser.add_argument("--vad-preroll-frames", type=_positive_frame_count, default=int(os.environ.get("VAD_PREROLL_FRAMES", "10")), help="Audio frames retained before speech detection.")
    parser.add_argument("--vad-min-turn-frames", type=_positive_frame_count, default=int(os.environ.get("VAD_MIN_TURN_FRAMES", "16")), help="Minimum audio frames in an automatic turn.")
    parser.add_argument(
        "--asr-provider",
        default=os.environ.get("ASR_PROVIDER", "disabled"),
        help="ASR provider: disabled, http_file, qwen_chat_audio, local_model, asr_server, or streaming_asr.",
    )
    parser.add_argument("--asr-http-url", default=os.environ.get("ASR_HTTP_URL", ""), help="HTTP ASR base URL or endpoint.")
    parser.add_argument("--asr-model", default=os.environ.get("ASR_MODEL", None), help="ASR model name.")
    parser.add_argument("--asr-api-key", default=os.environ.get("ASR_API_KEY", ""), help="ASR API key. Prefer ASR_API_KEY environment variable.")
    parser.add_argument("--asr-timeout-seconds", type=float, default=float(os.environ.get("ASR_TIMEOUT_SECONDS", "60")), help="ASR HTTP request timeout.")
    parser.add_argument("--send-stt-to-device", action="store_true", help="Send recognized text back to ESP32 as a stt message.")
    parser.add_argument(
        "--tts-provider",
        default=os.environ.get("TTS_PROVIDER", "disabled"),
        help="TTS provider: disabled, dashscope_qwen_http, local_model, tts_server, or streaming_tts.",
    )
    parser.add_argument("--tts-http-url", default=os.environ.get("TTS_HTTP_URL", ""), help="DashScope TTS /api/v1 base URL or generation endpoint.")
    parser.add_argument("--tts-model", default=os.environ.get("TTS_MODEL", None), help="TTS model name.")
    parser.add_argument("--tts-api-key", default=os.environ.get("TTS_API_KEY", ""), help="TTS API key. Prefer TTS_API_KEY environment variable.")
    parser.add_argument("--tts-voice", default=os.environ.get("TTS_VOICE", None), help="TTS voice name or custom voice ID.")
    parser.add_argument("--tts-language", default=os.environ.get("TTS_LANGUAGE", None), help="TTS language_type or auto.")
    parser.add_argument("--tts-timeout-seconds", type=float, default=float(os.environ.get("TTS_TIMEOUT_SECONDS", "60")), help="TTS HTTP request timeout.")
    parser.add_argument("--tts-frame-delay-ms", type=int, default=int(os.environ.get("TTS_FRAME_DELAY_MS", "60")), help="Delay between outgoing Opus frames.")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args()
    settings = GatewaySettings(
        host=args.host,
        http_port=args.http_port,
        websocket_port=args.websocket_port,
        advertise_host=args.advertise_host,
        buddy_core_base_url=args.buddy_core_base_url,
        session_history_limit=args.session_history_limit,
        audio_artifact_dir=args.audio_artifact_dir,
        audio_session_limit=args.audio_session_limit,
        vad_provider=args.vad_provider,
        vad_threshold=args.vad_threshold,
        vad_threshold_low=args.vad_threshold_low,
        vad_min_silence_ms=args.vad_min_silence_ms,
        vad_window_size=args.vad_window_size,
        vad_voice_votes=args.vad_voice_votes,
        vad_preroll_frames=args.vad_preroll_frames,
        vad_min_turn_frames=args.vad_min_turn_frames,
        asr_provider=args.asr_provider,
        asr_http_url=args.asr_http_url,
        asr_model=args.asr_model or GatewaySettings().asr_model,
        asr_api_key=args.asr_api_key,
        asr_timeout_seconds=args.asr_timeout_seconds,
        send_stt_to_device=args.send_stt_to_device,
        tts_provider=args.tts_provider,
        tts_http_url=args.tts_http_url,
        tts_model=args.tts_model or DEFAULT_TTS_MODEL,
        tts_api_key=args.tts_api_key,
        tts_voice=args.tts_voice or DEFAULT_TTS_VOICE,
        tts_language=args.tts_language or "auto",
        tts_timeout_seconds=args.tts_timeout_seconds,
        tts_frame_delay_ms=args.tts_frame_delay_ms,
    )
    asyncio.run(serve(settings))


if __name__ == "__main__":
    main()
