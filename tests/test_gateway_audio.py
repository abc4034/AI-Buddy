from pathlib import Path

import opuslib_next
from fastapi.testclient import TestClient

from buddy_gateway.app import create_http_app, create_websocket_app
from buddy_gateway.audio_artifact_writer import AudioArtifactWriter
from buddy_gateway.audio_frames import (
    ParsedAudioFrame,
    TimestampAudioBuffer,
    parse_audio_frame,
    xiaozhi_header_packet,
)
from buddy_gateway.audio_store import AudioArtifactStore
from buddy_gateway.config import GatewaySettings
from buddy_gateway.opus_codec import DecodedWav, decode_opus_frames_to_wav
from buddy_gateway.state import GatewayState


def encoded_silence_frame() -> bytes:
    encoder = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO)
    return encoder.encode(b"\x00" * 1920, 960)


def test_audio_frame_parser_treats_plain_bytes_as_raw_opus():
    parsed = parse_audio_frame(b"\x11\x22\x33")

    assert parsed.payload == b"\x11\x22\x33"
    assert parsed.timestamp is None
    assert parsed.sequence is None
    assert parsed.mode == "raw_opus"
    assert parsed.raw_size == 3


def test_audio_frame_parser_accepts_strict_xiaozhi_header():
    packet = xiaozhi_header_packet(b"opus", timestamp=1234, sequence=7)

    parsed = parse_audio_frame(packet)

    assert parsed.payload == b"opus"
    assert parsed.timestamp == 1234
    assert parsed.sequence == 7
    assert parsed.mode == "xiaozhi_header"
    assert parsed.raw_size == 20


def test_audio_frame_parser_falls_back_when_header_lengths_do_not_match():
    packet = bytearray(xiaozhi_header_packet(b"opus", timestamp=1234, sequence=7))
    packet[3] = 99

    parsed = parse_audio_frame(bytes(packet))

    assert parsed.payload == bytes(packet)
    assert parsed.timestamp is None
    assert parsed.mode == "raw_opus"


def test_timestamp_audio_buffer_limits_out_of_order_frames():
    buffer = TimestampAudioBuffer(max_size=20)

    emitted = buffer.push(ParsedAudioFrame(payload=b"latest", raw_size=6, timestamp=100, sequence=1, mode="xiaozhi_header"))
    assert [frame.payload for frame in emitted] == [b"latest"]
    for timestamp in range(1, 21):
        assert buffer.push(
            ParsedAudioFrame(
                payload=f"old-{timestamp}".encode("ascii"),
                raw_size=6,
                timestamp=timestamp,
                sequence=timestamp,
                mode="xiaozhi_header",
            )
        ) == []

    emitted = buffer.push(ParsedAudioFrame(payload=b"overflow", raw_size=8, timestamp=21, sequence=21, mode="xiaozhi_header"))

    assert buffer.buffered_count == 20
    assert [frame.payload for frame in emitted] == [b"overflow"]


def test_timestamp_audio_buffer_keeps_duplicate_timestamps_by_sequence():
    buffer = TimestampAudioBuffer(max_size=20)

    buffer.push(ParsedAudioFrame(payload=b"latest", raw_size=6, timestamp=100, sequence=3, mode="xiaozhi_header"))
    buffer.push(ParsedAudioFrame(payload=b"same-a", raw_size=6, timestamp=50, sequence=1, mode="xiaozhi_header"))
    buffer.push(ParsedAudioFrame(payload=b"same-b", raw_size=6, timestamp=50, sequence=2, mode="xiaozhi_header"))

    assert [frame.payload for frame in buffer.flush()] == [b"same-a", b"same-b"]


def test_opus_decoder_writes_valid_wav_bytes():
    result = decode_opus_frames_to_wav([encoded_silence_frame()])

    assert result.decoded_frame_count == 1
    assert result.decode_error_count == 0
    assert result.duration_ms == 60
    assert result.wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in result.wav_bytes[:16]


def test_audio_store_writes_metadata_and_retains_recent_sessions(tmp_path: Path):
    store = AudioArtifactStore(base_dir=tmp_path, session_limit=2)

    for session_id in ("session-a", "session-b", "session-c"):
        store.record_frame(
            session_id=session_id,
            device_id=f"device-{session_id[-1]}",
            client_id=None,
            frame=ParsedAudioFrame(payload=b"opus", raw_size=4, timestamp=None, sequence=None, mode="raw_opus"),
        )

    summaries = store.audio_session_summaries()

    assert [summary["session_id"] for summary in summaries] == ["session-b", "session-c"]
    assert not (tmp_path / "session-a").exists()
    assert (tmp_path / "session-c" / "metadata.json").exists()
    assert summaries[-1]["opus_frame_count"] == 1


def test_audio_store_retention_keeps_newest_session_when_created_in_same_second(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("buddy_gateway.audio_store.epoch_seconds", lambda: 1000)
    ticks = iter([10, 20, 30])
    monkeypatch.setattr("buddy_gateway.audio_store.time_ns", lambda: next(ticks))
    store = AudioArtifactStore(base_dir=tmp_path, session_limit=2)

    for session_id in ("session-a", "session-b", "session-c"):
        store.record_frame(
            session_id=session_id,
            device_id=f"device-{session_id[-1]}",
            client_id=None,
            frame=ParsedAudioFrame(payload=b"opus", raw_size=4, timestamp=None, sequence=None, mode="raw_opus"),
        )

    summaries = store.audio_session_summaries()

    assert [summary["session_id"] for summary in summaries] == ["session-b", "session-c"]
    assert not (tmp_path / "session-a").exists()
    assert (tmp_path / "session-c").exists()


def test_audio_store_decodes_timestamped_frames_in_timestamp_order(tmp_path: Path, monkeypatch):
    store = AudioArtifactStore(base_dir=tmp_path, session_limit=20)
    store.record_frame(
        session_id="session-a",
        device_id="device-a",
        client_id=None,
        frame=ParsedAudioFrame(payload=b"late", raw_size=20, timestamp=100, sequence=2, mode="xiaozhi_header"),
    )
    store.record_frame(
        session_id="session-a",
        device_id="device-a",
        client_id=None,
        frame=ParsedAudioFrame(payload=b"early", raw_size=21, timestamp=50, sequence=1, mode="xiaozhi_header"),
    )
    decoded_inputs = []

    def fake_decode(opus_frames, *, sample_rate=16000, channels=1, frame_duration_ms=60):
        decoded_inputs.append(list(opus_frames))
        return DecodedWav(
            wav_bytes=b"RIFF0000WAVE",
            decoded_frame_count=len(opus_frames),
            decode_error_count=0,
            duration_ms=len(opus_frames) * frame_duration_ms,
            sample_rate=sample_rate,
            channels=channels,
        )

    monkeypatch.setattr("buddy_gateway.audio_store.decode_opus_frames_to_wav", fake_decode)

    store.decode_session("session-a")

    assert decoded_inputs == [[b"early", b"late"]]


async def test_audio_artifact_writer_writes_frames_in_queue_order(tmp_path: Path):
    store = AudioArtifactStore(base_dir=tmp_path, session_limit=20)
    writer = AudioArtifactWriter(store)
    writer.start_session("session-a")

    await writer.enqueue_frame(
        session_id="session-a",
        device_id="device-a",
        client_id=None,
        frame=ParsedAudioFrame(payload=b"one", raw_size=3, timestamp=None, sequence=None, mode="raw_opus"),
    )
    await writer.enqueue_frame(
        session_id="session-a",
        device_id="device-a",
        client_id=None,
        frame=ParsedAudioFrame(payload=b"two", raw_size=3, timestamp=None, sequence=None, mode="raw_opus"),
    )
    await writer.finish_session("session-a")

    summaries = store.audio_session_summaries()
    assert summaries[0]["opus_frame_count"] == 2
    assert (tmp_path / "session-a" / "frame-00001.opus").read_bytes() == b"one"
    assert (tmp_path / "session-a" / "frame-00002.opus").read_bytes() == b"two"


def test_gateway_buffers_out_of_order_header_audio_until_disconnect(tmp_path: Path):
    settings = GatewaySettings(
        advertise_host="127.0.0.1",
        http_port=18003,
        websocket_port=18000,
        audio_artifact_dir=str(tmp_path),
        audio_session_limit=20,
    )
    state = GatewayState()
    audio_store = AudioArtifactStore(base_dir=tmp_path, session_limit=20)
    websocket_client = TestClient(create_websocket_app(settings=settings, state=state, audio_store=audio_store))
    http_client = TestClient(create_http_app(settings=settings, state=state, audio_store=audio_store))

    with websocket_client.websocket_connect(
        "/xiaozhi/v1/",
        headers={"device-id": "fc:01", "client-id": "client-a"},
    ) as websocket:
        websocket.send_json({"type": "hello"})
        session_id = websocket.receive_json()["session_id"]
        websocket.send_bytes(xiaozhi_header_packet(b"late", timestamp=100, sequence=2))
        websocket.send_bytes(xiaozhi_header_packet(b"early", timestamp=50, sequence=1))
        live_audio_payload = http_client.get("/debug/audio/sessions").json()
        assert live_audio_payload["sessions"][0]["session_id"] == session_id
        assert live_audio_payload["sessions"][0]["opus_frame_count"] == 1

    final_audio_payload = http_client.get("/debug/audio/sessions").json()
    assert final_audio_payload["sessions"][0]["opus_frame_count"] == 2


def test_gateway_records_and_decodes_audio_session(tmp_path: Path):
    settings = GatewaySettings(
        advertise_host="127.0.0.1",
        http_port=18003,
        websocket_port=18000,
        audio_artifact_dir=str(tmp_path),
        audio_session_limit=20,
    )
    state = GatewayState()
    audio_store = AudioArtifactStore(base_dir=tmp_path, session_limit=20)
    websocket_client = TestClient(create_websocket_app(settings=settings, state=state, audio_store=audio_store))
    http_client = TestClient(create_http_app(settings=settings, state=state, audio_store=audio_store))
    opus_frame = encoded_silence_frame()

    with websocket_client.websocket_connect(
        "/xiaozhi/v1/",
        headers={"device-id": "fc:01", "client-id": "client-a"},
    ) as websocket:
        websocket.send_json({"type": "hello"})
        session_id = websocket.receive_json()["session_id"]
        websocket.send_bytes(opus_frame)

    audio_payload = http_client.get("/debug/audio/sessions").json()
    assert audio_payload["session_count"] == 1
    assert audio_payload["sessions"][0]["session_id"] == session_id
    assert audio_payload["sessions"][0]["opus_frame_count"] == 1
    assert state.session_summaries()[0]["audio_parse_modes"] == {"raw_opus": 1}

    decode_response = http_client.post(f"/debug/sessions/{session_id}/decode-audio")
    assert decode_response.status_code == 200
    decode_payload = decode_response.json()
    assert decode_payload["decoded_frame_count"] == 1
    assert decode_payload["decode_error_count"] == 0
    assert decode_payload["wav_path"].endswith("audio.wav")

    wav_response = http_client.get(f"/debug/sessions/{session_id}/audio.wav")
    assert wav_response.status_code == 200
    assert wav_response.content.startswith(b"RIFF")
