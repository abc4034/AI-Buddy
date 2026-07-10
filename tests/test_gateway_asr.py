import json
import base64
import inspect
from pathlib import Path

import httpx
import opuslib_next
import pytest
from fastapi.testclient import TestClient

from buddy_gateway.app import create_http_app, create_websocket_app
from buddy_gateway.asr import (
    ASRAudioArtifact,
    ASRProviderError,
    ASRProviderNotImplemented,
    ASRStream,
    HttpFileASRProvider,
    QwenChatAudioASRProvider,
    StreamingASRProvider,
    asr_provider_catalog,
    build_asr_provider,
)
from buddy_gateway.audio_frames import xiaozhi_header_packet
from buddy_gateway.audio_store import AudioArtifactStore
from buddy_gateway.config import GatewaySettings
from buddy_gateway.state import GatewayState


def encoded_silence_frame() -> bytes:
    encoder = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO)
    return encoder.encode(b"\x00" * 1920, 960)


class FakeASRProvider:
    provider_name = "fake_asr"

    def __init__(self, text: str = "I like apples") -> None:
        self.text = text
        self.calls = []

    async def transcribe(self, artifact: ASRAudioArtifact):
        from buddy_gateway.asr import ASRResult

        self.calls.append(artifact)
        return ASRResult(text=self.text, provider=self.provider_name)


class FakeBuddyCoreClient:
    def __init__(self, assistant_text: str = "Apple means ping guo.") -> None:
        self.assistant_text = assistant_text
        self.calls = []

    async def complete_text(self, *, device_id, client_id, session_id, text, source, metadata=None):
        self.calls.append(
            {
                "device_id": device_id,
                "client_id": client_id,
                "session_id": session_id,
                "text": text,
                "source": source,
                "metadata": metadata or {},
            }
        )
        return self.assistant_text


@pytest.mark.asyncio
async def test_http_file_asr_provider_posts_wav_to_openai_compatible_transcription_endpoint():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"text": "I like apples"})

    provider = HttpFileASRProvider(
        url="https://asr.example.test/compatible-mode/v1",
        api_key="secret-key",
        model="qwen3-asr-flash-2025-09-08",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.transcribe(
        ASRAudioArtifact(
            session_id="session-a",
            turn_id="turn-a",
            device_id="fc:01",
            client_id="client-a",
            opus_frames=[b"opus"],
            wav_bytes=b"RIFF0000WAVE",
            wav_path=None,
            sample_rate=16000,
            channels=1,
            frame_duration_ms=60,
        )
    )

    assert result.text == "I like apples"
    assert result.provider == "http_file"
    assert len(requests) == 1
    assert str(requests[0].url) == "https://asr.example.test/compatible-mode/v1/audio/transcriptions"
    assert requests[0].headers["authorization"] == "Bearer secret-key"
    body = requests[0].content
    assert b'name="model"' in body
    assert b"qwen3-asr-flash-2025-09-08" in body
    assert b'name="file"; filename="turn-a.wav"' in body
    assert b"RIFF0000WAVE" in body


@pytest.mark.asyncio
async def test_qwen_chat_audio_asr_provider_posts_base64_audio_to_chat_completions():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "I like apples"}}]})

    provider = QwenChatAudioASRProvider(
        url="https://asr.example.test/compatible-mode/v1",
        api_key="secret-key",
        model="qwen3-asr-flash-2025-09-08",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.transcribe(
        ASRAudioArtifact(
            session_id="session-a",
            turn_id="turn-a",
            device_id="fc:01",
            client_id="client-a",
            opus_frames=[],
            wav_bytes=b"RIFF0000WAVE",
            wav_path=None,
            sample_rate=16000,
            channels=1,
            frame_duration_ms=60,
        )
    )

    assert result.text == "I like apples"
    assert result.provider == "qwen_chat_audio"
    assert str(requests[0].url) == "https://asr.example.test/compatible-mode/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer secret-key"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "qwen3-asr-flash-2025-09-08"
    assert payload["messages"][0]["role"] == "user"
    audio_data = payload["messages"][0]["content"][0]["input_audio"]["data"]
    assert audio_data == "data:audio/wav;base64," + base64.b64encode(b"RIFF0000WAVE").decode("ascii")
    assert payload["asr_options"] == {"enable_itn": False}


def test_asr_provider_factory_exposes_planned_not_implemented_providers():
    provider = build_asr_provider(
        GatewaySettings(
            asr_provider="local_model",
            asr_http_url="https://asr.example.test/compatible-mode/v1",
        )
    )

    assert isinstance(provider, ASRProviderNotImplemented)
    assert provider.provider_name == "local_model"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["local_model", "asr_server", "streaming_asr"])
async def test_each_planned_asr_provider_has_a_provider_specific_error(provider_name):
    provider = build_asr_provider(GatewaySettings(asr_provider=provider_name))
    artifact = ASRAudioArtifact(
        session_id="session-a",
        turn_id="turn-a",
        device_id=None,
        client_id=None,
        opus_frames=[],
        wav_bytes=b"RIFF0000WAVE",
        wav_path=None,
        sample_rate=16000,
        channels=1,
        frame_duration_ms=60,
        pcm_bytes=b"\x00\x00",
    )

    with pytest.raises(
        ASRProviderError,
        match=rf"ASR provider '{provider_name}' is planned but not implemented",
    ):
        await provider.transcribe(artifact)


def test_asr_catalog_preserves_batch_providers_and_planned_slots():
    catalog = asr_provider_catalog(GatewaySettings(asr_provider="qwen_chat_audio"))

    assert catalog["implemented"] == ["disabled", "http_file", "qwen_chat_audio"]
    assert catalog["planned"] == ["local_model", "asr_server", "streaming_asr"]


def test_asr_audio_artifact_carries_predecoded_pcm_bytes():
    artifact = ASRAudioArtifact(
        session_id="session-a",
        turn_id="turn-a",
        device_id=None,
        client_id=None,
        opus_frames=[b"opus"],
        wav_bytes=b"RIFF0000WAVE",
        wav_path=None,
        sample_rate=16000,
        channels=1,
        frame_duration_ms=60,
        pcm_bytes=b"cached-pcm",
    )

    assert artifact.pcm_bytes == b"cached-pcm"


def test_streaming_asr_protocols_expose_the_binding_methods():
    assert list(inspect.signature(ASRStream.push_pcm).parameters) == ["self", "pcm_frame"]
    assert list(inspect.signature(ASRStream.finish).parameters) == ["self"]
    assert list(inspect.signature(ASRStream.abort).parameters) == ["self"]
    assert list(inspect.signature(ASRStream.close).parameters) == ["self"]
    assert list(inspect.signature(StreamingASRProvider.open_stream).parameters) == ["self", "artifact"]


def test_gateway_settings_default_asr_provider_is_disabled_even_when_user_env_is_set(monkeypatch):
    monkeypatch.setenv("ASR_PROVIDER", "qwen_chat_audio")

    settings = GatewaySettings()

    assert settings.asr_provider == "disabled"


def test_gateway_listen_stop_transcribes_audio_and_calls_buddy_core(tmp_path: Path):
    settings = GatewaySettings(
        advertise_host="127.0.0.1",
        http_port=18003,
        websocket_port=18000,
        audio_artifact_dir=str(tmp_path),
        asr_provider="http_file",
    )
    state = GatewayState()
    audio_store = AudioArtifactStore(base_dir=tmp_path, session_limit=20)
    asr_provider = FakeASRProvider(text="I like apples")
    core_client = FakeBuddyCoreClient()
    websocket_client = TestClient(
        create_websocket_app(
            settings=settings,
            state=state,
            core_client=core_client,
            audio_store=audio_store,
            asr_provider=asr_provider,
        )
    )
    http_client = TestClient(
        create_http_app(
            settings=settings,
            state=state,
            core_client=core_client,
            audio_store=audio_store,
            asr_provider=asr_provider,
        )
    )

    with websocket_client.websocket_connect(
        "/xiaozhi/v1/",
        headers={"device-id": "fc:01", "client-id": "client-a"},
    ) as websocket:
        websocket.send_json({"type": "hello"})
        session_id = websocket.receive_json()["session_id"]
        websocket.send_json({"type": "listen", "state": "start", "mode": "manual"})
        websocket.send_bytes(encoded_silence_frame())
        websocket.send_json({"type": "listen", "state": "stop", "mode": "manual"})

    summary = http_client.get("/debug/sessions").json()["sessions"][0]
    assert summary["session_id"] == session_id
    assert summary["asr_turns"][0]["status"] == "ok"
    assert summary["asr_turns"][0]["transcript"] == "I like apples"
    assert summary["asr_turns"][0]["assistant_text"] == "Apple means ping guo."
    assert summary["asr_turns"][0]["trigger"] == "listen_stop"
    assert summary["asr_turns"][0]["sent_stt_to_device"] is False
    assert asr_provider.calls[0].device_id == "fc:01"
    assert asr_provider.calls[0].wav_bytes.startswith(b"RIFF")
    assert core_client.calls == [
        {
            "device_id": "fc:01",
            "client_id": "client-a",
            "session_id": session_id,
            "text": "I like apples",
            "source": "buddy_gateway_asr",
            "metadata": {
                "asr_provider": "fake_asr",
                "asr_turn_id": summary["asr_turns"][0]["turn_id"],
            },
        }
    ]


def test_gateway_listen_stop_transcribes_timestamped_frames_in_order(tmp_path: Path, monkeypatch):
    settings = GatewaySettings(
        advertise_host="127.0.0.1",
        http_port=18003,
        websocket_port=18000,
        audio_artifact_dir=str(tmp_path),
        asr_provider="http_file",
    )
    state = GatewayState()
    asr_provider = FakeASRProvider(text="ordered transcript")
    core_client = FakeBuddyCoreClient()
    decoded_inputs = []

    def fake_decode(opus_frames, *, sample_rate=16000, channels=1, frame_duration_ms=60):
        from buddy_gateway.opus_codec import DecodedWav

        decoded_inputs.append(list(opus_frames))
        return DecodedWav(
            wav_bytes=b"RIFF0000WAVE",
            decoded_frame_count=len(opus_frames),
            decode_error_count=0,
            duration_ms=len(opus_frames) * frame_duration_ms,
            sample_rate=sample_rate,
            channels=channels,
        )

    monkeypatch.setattr("buddy_gateway.app.decode_opus_frames_to_wav", fake_decode)
    client = TestClient(
        create_websocket_app(
            settings=settings,
            state=state,
            core_client=core_client,
            audio_store=AudioArtifactStore(base_dir=tmp_path, session_limit=20),
            asr_provider=asr_provider,
        )
    )

    with client.websocket_connect("/xiaozhi/v1/", headers={"device-id": "fc:01"}) as websocket:
        websocket.send_json({"type": "hello"})
        websocket.receive_json()
        websocket.send_json({"type": "listen", "state": "start"})
        websocket.send_bytes(xiaozhi_header_packet(b"late", timestamp=100, sequence=2))
        websocket.send_bytes(xiaozhi_header_packet(b"early", timestamp=50, sequence=1))
        websocket.send_json({"type": "listen", "state": "stop"})

    assert decoded_inputs == [[b"early", b"late"]]
    assert state.session_summaries()[0]["asr_turns"][0]["status"] == "ok"


def test_gateway_disconnect_transcribes_unfinished_listen_turn(tmp_path: Path):
    settings = GatewaySettings(
        advertise_host="127.0.0.1",
        http_port=18003,
        websocket_port=18000,
        audio_artifact_dir=str(tmp_path),
        asr_provider="http_file",
    )
    state = GatewayState()
    asr_provider = FakeASRProvider(text="disconnect transcript")
    core_client = FakeBuddyCoreClient()
    websocket_client = TestClient(
        create_websocket_app(
            settings=settings,
            state=state,
            core_client=core_client,
            audio_store=AudioArtifactStore(base_dir=tmp_path, session_limit=20),
            asr_provider=asr_provider,
        )
    )

    with websocket_client.websocket_connect("/xiaozhi/v1/", headers={"device-id": "fc:01"}) as websocket:
        websocket.send_json({"type": "hello"})
        websocket.receive_json()
        websocket.send_json({"type": "listen", "state": "start"})
        websocket.send_bytes(encoded_silence_frame())

    summary = state.session_summaries()[0]
    assert summary["asr_turns"][0]["status"] == "ok"
    assert summary["asr_turns"][0]["trigger"] == "disconnect"
    assert summary["asr_turns"][0]["transcript"] == "disconnect transcript"
    assert len(core_client.calls) == 1


def test_gateway_sends_stt_to_device_when_enabled(tmp_path: Path):
    settings = GatewaySettings(
        advertise_host="127.0.0.1",
        http_port=18003,
        websocket_port=18000,
        audio_artifact_dir=str(tmp_path),
        asr_provider="http_file",
        send_stt_to_device=True,
    )
    state = GatewayState()
    asr_provider = FakeASRProvider(text="hello buddy")
    core_client = FakeBuddyCoreClient()
    client = TestClient(
        create_websocket_app(
            settings=settings,
            state=state,
            core_client=core_client,
            audio_store=AudioArtifactStore(base_dir=tmp_path, session_limit=20),
            asr_provider=asr_provider,
        )
    )

    with client.websocket_connect("/xiaozhi/v1/", headers={"device-id": "fc:01"}) as websocket:
        websocket.send_json({"type": "hello"})
        session_id = websocket.receive_json()["session_id"]
        websocket.send_json({"type": "listen", "state": "start"})
        websocket.send_bytes(encoded_silence_frame())
        websocket.send_json({"type": "listen", "state": "stop"})
        stt = websocket.receive_json()

    assert stt == {"type": "stt", "text": "hello buddy", "session_id": session_id}


def test_gateway_manual_transcribe_endpoint_uses_audio_store_session(tmp_path: Path):
    settings = GatewaySettings(
        advertise_host="127.0.0.1",
        http_port=18003,
        websocket_port=18000,
        audio_artifact_dir=str(tmp_path),
        asr_provider="http_file",
    )
    state = GatewayState()
    audio_store = AudioArtifactStore(base_dir=tmp_path, session_limit=20)
    asr_provider = FakeASRProvider(text="manual transcript")
    core_client = FakeBuddyCoreClient()
    websocket_client = TestClient(
        create_websocket_app(
            settings=settings,
            state=state,
            core_client=core_client,
            audio_store=audio_store,
            asr_provider=asr_provider,
        )
    )
    http_client = TestClient(
        create_http_app(
            settings=settings,
            state=state,
            core_client=core_client,
            audio_store=audio_store,
            asr_provider=asr_provider,
        )
    )

    with websocket_client.websocket_connect("/xiaozhi/v1/", headers={"device-id": "fc:01"}) as websocket:
        websocket.send_json({"type": "hello"})
        session_id = websocket.receive_json()["session_id"]
        websocket.send_bytes(encoded_silence_frame())

    response = http_client.post(f"/debug/sessions/{session_id}/transcribe-audio")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["transcript"] == "manual transcript"
    assert payload["assistant_text"] == "Apple means ping guo."
    assert core_client.calls[0]["source"] == "buddy_gateway_asr"
    assert json.loads(json.dumps(payload)) == payload
