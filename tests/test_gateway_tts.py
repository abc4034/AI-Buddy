import base64
import io
import json
import wave
from pathlib import Path

import httpx
import opuslib_next
import pytest
from fastapi.testclient import TestClient

from buddy_gateway.app import create_http_app, create_websocket_app
from buddy_gateway.asr import ASRAudioArtifact, ASRResult
from buddy_gateway.audio_store import AudioArtifactStore
from buddy_gateway.config import GatewaySettings
from buddy_gateway.opus_codec import encode_pcm16_mono_to_opus_frames, wav_bytes_to_pcm16_mono
from buddy_gateway.state import GatewayState
from buddy_gateway.tts import (
    DashScopeQwenHttpTTSProvider,
    TTSProviderError,
    TTSProviderNotImplemented,
    TTSResult,
    build_tts_provider,
    tts_provider_catalog,
)


def encoded_silence_frame() -> bytes:
    encoder = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO)
    return encoder.encode(b"\x00" * 1920, 960)


def wav_bytes(*, sample_rate: int = 16000, duration_ms: int = 120, channels: int = 1) -> bytes:
    sample_count = int(sample_rate * duration_ms / 1000)
    frame = b"\x00\x00" * channels
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frame * sample_count)
    return buffer.getvalue()


class FakeASRProvider:
    provider_name = "fake_asr"

    async def transcribe(self, artifact: ASRAudioArtifact) -> ASRResult:
        return ASRResult(text="I like apples", provider=self.provider_name)


class FakeBuddyCoreClient:
    async def complete_text(self, *, device_id, client_id, session_id, text, source, metadata=None):
        return "Great job. Apple means ping guo."


class FakeTTSProvider:
    provider_name = "fake_tts"

    def __init__(self, audio: bytes | None = None) -> None:
        self.audio = audio or wav_bytes(duration_ms=120)
        self.calls = []

    async def synthesize(self, text: str) -> TTSResult:
        self.calls.append(text)
        return TTSResult(audio_bytes=self.audio, audio_format="wav", provider=self.provider_name)


@pytest.mark.asyncio
async def test_dashscope_qwen_tts_provider_posts_text_and_downloads_audio_url():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url) == "https://tts.example.test/api/v1/services/aigc/multimodal-generation/generation":
            return httpx.Response(
                200,
                json={
                    "output": {
                        "audio": {
                            "url": "https://audio.example.test/output.wav",
                        }
                    }
                },
            )
        if str(request.url) == "https://audio.example.test/output.wav":
            return httpx.Response(200, content=b"RIFF0000WAVE", headers={"content-type": "audio/wav"})
        return httpx.Response(404, text="not found")

    provider = DashScopeQwenHttpTTSProvider(
        url="https://tts.example.test/api/v1",
        api_key="secret-key",
        model="qwen3-tts-instruct-flash",
        voice="Cherry",
        language="auto",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.synthesize("Hello, I like apples.")

    assert result.audio_bytes == b"RIFF0000WAVE"
    assert result.audio_format == "wav"
    assert result.provider == "dashscope_qwen_http"
    assert len(requests) == 2
    generation_payload = json.loads(requests[0].content)
    assert requests[0].headers["authorization"] == "Bearer secret-key"
    assert generation_payload == {
        "model": "qwen3-tts-instruct-flash",
        "input": {
            "text": "Hello, I like apples.",
            "voice": "Cherry",
            "language_type": "English",
        },
    }


@pytest.mark.asyncio
async def test_dashscope_qwen_tts_provider_accepts_base64_audio_data_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": {
                    "audio": {
                        "data": base64.b64encode(b"RIFFbase64WAVE").decode("ascii"),
                        "format": "wav",
                    }
                }
            },
        )

    provider = DashScopeQwenHttpTTSProvider(
        url="https://tts.example.test/api/v1",
        api_key="secret-key",
        model="qwen3-tts-instruct-flash",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.synthesize("你好")

    assert result.audio_bytes == b"RIFFbase64WAVE"
    assert result.audio_format == "wav"


@pytest.mark.asyncio
async def test_dashscope_qwen_tts_provider_requires_api_key():
    provider = DashScopeQwenHttpTTSProvider(
        url="https://tts.example.test/api/v1",
        api_key="",
        model="qwen3-tts-instruct-flash",
    )

    with pytest.raises(TTSProviderError, match="TTS API key"):
        await provider.synthesize("hello")


def test_tts_provider_factory_exposes_planned_not_implemented_providers():
    provider = build_tts_provider(
        GatewaySettings(
            tts_provider="local_model",
            tts_http_url="https://tts.example.test/api/v1",
        )
    )

    assert isinstance(provider, TTSProviderNotImplemented)
    assert provider.provider_name == "local_model"


def test_tts_provider_catalog_hides_api_key_and_lists_provider_slots():
    catalog = tts_provider_catalog(
        GatewaySettings(
            tts_provider="dashscope_qwen_http",
            tts_http_url="https://tts.example.test/api/v1",
            tts_api_key="secret-key",
            tts_model="qwen3-tts-instruct-flash",
            tts_voice="Cherry",
            tts_language="auto",
        )
    )

    assert catalog["current_provider"] == "dashscope_qwen_http"
    assert catalog["dashscope_qwen_http"]["api_key_configured"] is True
    assert "secret-key" not in json.dumps(catalog)
    assert "local_model" in catalog["planned"]
    assert "tts_server" in catalog["planned"]
    assert "streaming_tts" in catalog["planned"]


def test_wav_bytes_to_pcm16_mono_resamples_to_device_format():
    pcm = wav_bytes_to_pcm16_mono(wav_bytes(sample_rate=24000, duration_ms=120, channels=2), target_sample_rate=16000)

    assert len(pcm) == 16000 * 120 // 1000 * 2


def test_encode_pcm16_mono_to_opus_frames_uses_60ms_device_frames():
    pcm = b"\x00\x00" * (16000 * 120 // 1000)

    frames = encode_pcm16_mono_to_opus_frames(pcm, sample_rate=16000, frame_duration_ms=60)

    assert len(frames) == 2
    decoder = opuslib_next.Decoder(16000, 1)
    decoded = decoder.decode(frames[0], 960)
    assert len(decoded) == 1920


def test_gateway_asr_core_tts_loop_sends_tts_messages_and_opus_audio_to_device(tmp_path: Path):
    settings = GatewaySettings(
        advertise_host="127.0.0.1",
        http_port=18003,
        websocket_port=18000,
        audio_artifact_dir=str(tmp_path),
        asr_provider="http_file",
        tts_provider="dashscope_qwen_http",
        send_stt_to_device=True,
        tts_frame_delay_ms=0,
    )
    state = GatewayState()
    tts_provider = FakeTTSProvider()
    client = TestClient(
        create_websocket_app(
            settings=settings,
            state=state,
            core_client=FakeBuddyCoreClient(),
            audio_store=AudioArtifactStore(base_dir=tmp_path, session_limit=20),
            asr_provider=FakeASRProvider(),
            tts_provider=tts_provider,
        )
    )

    with client.websocket_connect("/xiaozhi/v1/", headers={"device-id": "fc:01", "client-id": "client-a"}) as websocket:
        websocket.send_json({"type": "hello"})
        session_id = websocket.receive_json()["session_id"]
        websocket.send_json({"type": "listen", "state": "start", "mode": "manual"})
        websocket.send_bytes(encoded_silence_frame())
        websocket.send_json({"type": "listen", "state": "stop", "mode": "manual"})
        assert websocket.receive_json() == {"type": "stt", "text": "I like apples", "session_id": session_id}
        assert websocket.receive_json() == {"type": "tts", "state": "start", "session_id": session_id}
        sentence_start = websocket.receive_json()
        first_audio = websocket.receive()
        second_audio = websocket.receive()
        tts_stop = websocket.receive_json()

    assert sentence_start == {
        "type": "tts",
        "state": "sentence_start",
        "session_id": session_id,
        "text": "Great job. Apple means ping guo.",
    }
    assert first_audio["bytes"]
    assert second_audio["bytes"]
    assert tts_stop == {"type": "tts", "state": "stop", "session_id": session_id}
    assert tts_provider.calls == ["Great job. Apple means ping guo."]
    summary = state.session_summaries()[0]
    assert summary["asr_turns"][0]["status"] == "ok"
    assert summary["tts_turns"][0]["status"] == "ok"
    assert summary["tts_turns"][0]["provider"] == "fake_tts"
    assert summary["tts_turns"][0]["audio_frame_count"] == 2


def test_gateway_abort_sends_tts_stop_for_current_session(tmp_path: Path):
    settings = GatewaySettings(
        advertise_host="127.0.0.1",
        http_port=18003,
        websocket_port=18000,
        audio_artifact_dir=str(tmp_path),
        tts_provider="dashscope_qwen_http",
    )
    state = GatewayState()
    client = TestClient(
        create_websocket_app(
            settings=settings,
            state=state,
            audio_store=AudioArtifactStore(base_dir=tmp_path, session_limit=20),
            tts_provider=FakeTTSProvider(),
        )
    )

    with client.websocket_connect("/xiaozhi/v1/", headers={"device-id": "fc:01"}) as websocket:
        websocket.send_json({"type": "hello"})
        session_id = websocket.receive_json()["session_id"]
        websocket.send_json({"type": "abort"})
        assert websocket.receive_json() == {"type": "tts", "state": "stop", "session_id": session_id}

    assert state.session_summaries()[0]["message_counts"]["abort"] == 1
