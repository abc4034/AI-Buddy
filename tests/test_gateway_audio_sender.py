from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from enum import Enum

import opuslib_next
import pytest

from buddy_gateway.audio_sender import DeviceAudioSender
from buddy_gateway.opus_codec import encode_pcm16_mono_chunks_to_opus_frames
from buddy_gateway.tts import TTSPcmChunk


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


class RecordingWebSocket:
    def __init__(self, clock: FakeClock, *, frame_send_seconds: float = 0.0) -> None:
        self.clock = clock
        self.frame_send_seconds = frame_send_seconds
        self.open = True
        self.events: list[tuple[str, object, float]] = []
        self.frame_sent = asyncio.Event()

    async def send_json(self, payload: dict[str, object]) -> None:
        self.events.append(("json", payload, self.clock.now))

    async def send_bytes(self, payload: bytes) -> None:
        self.events.append(("bytes", payload, self.clock.now))
        self.frame_sent.set()
        self.clock.now += self.frame_send_seconds


async def frames(*payloads: bytes) -> AsyncIterator[bytes]:
    for payload in payloads:
        yield payload


def make_sender(
    websocket: RecordingWebSocket,
    clock: FakeClock,
    *,
    current: dict[str, object] | None = None,
    drain_events: list[tuple[str, float]] | None = None,
) -> DeviceAudioSender:
    expected = current if current is not None else {"turn_id": "turn-a", "generation": 7}

    async def drain() -> None:
        if drain_events is not None:
            drain_events.append(("drain", clock.now))

    return DeviceAudioSender(
        websocket,
        session_id="session-a",
        is_generation_current=lambda turn_id, generation: (
            expected.get("turn_id") == turn_id and expected.get("generation") == generation
        ),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        drain=drain,
        is_open=lambda: websocket.open,
    )


@pytest.mark.asyncio
async def test_play_sends_v05_controls_raw_opus_and_one_stop_in_exact_order() -> None:
    clock = FakeClock()
    websocket = RecordingWebSocket(clock)
    drain_events: list[tuple[str, float]] = []
    sender = make_sender(websocket, clock, drain_events=drain_events)

    result = await sender.play("turn-a", 7, "Hello Buddy", frames(b"opus-a", b"opus-b"))

    assert [(kind, payload) for kind, payload, _ in websocket.events] == [
        ("json", {"type": "tts", "state": "start", "session_id": "session-a"}),
        (
            "json",
            {
                "type": "tts",
                "state": "sentence_start",
                "session_id": "session-a",
                "text": "Hello Buddy",
            },
        ),
        ("bytes", b"opus-a"),
        ("bytes", b"opus-b"),
        ("json", {"type": "tts", "state": "stop", "session_id": "session-a"}),
    ]
    assert drain_events == [("drain", 0.0)]
    assert clock.sleeps == [pytest.approx(0.420)]
    assert result.status == "ok"
    assert result.frame_count == 2
    assert result.error is None


@pytest.mark.asyncio
async def test_play_bursts_five_frames_then_uses_absolute_60ms_schedule() -> None:
    clock = FakeClock()
    websocket = RecordingWebSocket(clock, frame_send_seconds=0.010)
    sender = make_sender(websocket, clock)

    result = await sender.play("turn-a", 7, "paced", frames(*(bytes([index]) for index in range(7))))

    frame_times = [timestamp for kind, _, timestamp in websocket.events if kind == "bytes"]
    assert frame_times == pytest.approx([0.0, 0.01, 0.02, 0.03, 0.04, 0.06, 0.12])
    assert clock.sleeps == pytest.approx([0.01, 0.05, 0.42])
    assert result.frame_count == 7


@pytest.mark.asyncio
async def test_stale_generation_stops_without_more_audio_or_stale_stop() -> None:
    clock = FakeClock()
    current: dict[str, object] = {"turn_id": "turn-a", "generation": 7}

    class StalingWebSocket(RecordingWebSocket):
        async def send_bytes(self, payload: bytes) -> None:
            await super().send_bytes(payload)
            current["generation"] = 8

    websocket = StalingWebSocket(clock)
    sender = make_sender(websocket, clock, current=current)

    result = await sender.play("turn-a", 7, "stale", frames(b"first", b"stale"))

    assert [payload for kind, payload, _ in websocket.events if kind == "bytes"] == [b"first"]
    assert not any(payload.get("state") == "stop" for kind, payload, _ in websocket.events if kind == "json")
    assert clock.sleeps == []
    assert result.status == "aborted"
    assert result.frame_count == 1


@pytest.mark.asyncio
async def test_abort_cancels_blocked_iteration_and_repeated_abort_sends_one_stop() -> None:
    clock = FakeClock()
    websocket = RecordingWebSocket(clock)
    sender = make_sender(websocket, clock)
    blocked = asyncio.Event()

    async def blocked_frames() -> AsyncIterator[bytes]:
        yield b"first"
        await blocked.wait()
        yield b"never"

    play_task = asyncio.create_task(sender.play("turn-a", 7, "abort", blocked_frames()))
    await websocket.frame_sent.wait()
    await sender.abort("device abort")
    await sender.abort("duplicate abort")
    result = await play_task

    states = [payload["state"] for kind, payload, _ in websocket.events if kind == "json"]
    assert states == ["start", "sentence_start", "stop"]
    assert [payload for kind, payload, _ in websocket.events if kind == "bytes"] == [b"first"]
    assert clock.sleeps == []
    assert result.status == "aborted"
    assert result.frame_count == 1
    assert result.error == "device abort"


@pytest.mark.asyncio
async def test_disconnect_close_cancels_playback_without_stop_or_tail_sleep() -> None:
    clock = FakeClock()
    websocket = RecordingWebSocket(clock)
    sender = make_sender(websocket, clock)
    blocked = asyncio.Event()

    async def blocked_frames() -> AsyncIterator[bytes]:
        yield b"first"
        await blocked.wait()

    play_task = asyncio.create_task(sender.play("turn-a", 7, "disconnect", blocked_frames()))
    await websocket.frame_sent.wait()
    websocket.open = False
    await sender.close(send_stop=False)
    result = await play_task

    states = [payload["state"] for kind, payload, _ in websocket.events if kind == "json"]
    assert states == ["start", "sentence_start"]
    assert clock.sleeps == []
    assert result.status == "aborted"


@pytest.mark.asyncio
async def test_close_with_stop_is_idempotent_for_active_playback() -> None:
    clock = FakeClock()
    websocket = RecordingWebSocket(clock)
    sender = make_sender(websocket, clock)
    blocked = asyncio.Event()

    async def blocked_frames() -> AsyncIterator[bytes]:
        yield b"first"
        await blocked.wait()

    play_task = asyncio.create_task(sender.play("turn-a", 7, "close", blocked_frames()))
    await websocket.frame_sent.wait()
    await sender.close(send_stop=True)
    await sender.close(send_stop=True)
    result = await play_task

    states = [payload["state"] for kind, payload, _ in websocket.events if kind == "json"]
    assert states == ["start", "sentence_start", "stop"]
    assert result.status == "aborted"


@pytest.mark.asyncio
async def test_abort_during_start_attempts_the_single_stop() -> None:
    clock = FakeClock()

    class StartBlockingWebSocket(RecordingWebSocket):
        def __init__(self) -> None:
            super().__init__(clock)
            self.start_entered = asyncio.Event()

        async def send_json(self, payload: dict[str, object]) -> None:
            if payload["state"] == "start":
                self.start_entered.set()
                await asyncio.Event().wait()
            await super().send_json(payload)

    websocket = StartBlockingWebSocket()
    sender = make_sender(websocket, clock)
    play_task = asyncio.create_task(sender.play("turn-a", 7, "abort", frames(b"never")))
    await websocket.start_entered.wait()

    await sender.abort("device abort")
    result = await play_task

    assert [(kind, payload) for kind, payload, _ in websocket.events] == [
        ("json", {"type": "tts", "state": "stop", "session_id": "session-a"})
    ]
    assert result.status == "aborted"


@pytest.mark.asyncio
async def test_default_socket_state_rejects_disconnected_transport() -> None:
    class SocketState(Enum):
        DISCONNECTED = 3

    clock = FakeClock()
    websocket = RecordingWebSocket(clock)
    websocket.application_state = SocketState.DISCONNECTED
    sender = DeviceAudioSender(
        websocket,
        session_id="session-a",
        is_generation_current=lambda _turn_id, _generation: True,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    result = await sender.play("turn-a", 7, "offline", frames(b"never"))

    assert websocket.events == []
    assert result.status == "aborted"


@pytest.mark.asyncio
async def test_task3_pcm_stream_adapter_feeds_real_sender_as_raw_opus() -> None:
    pcm_frame = b"\x00\x00" * 960

    async def chunks() -> AsyncIterator[TTSPcmChunk]:
        yield TTSPcmChunk(pcm16_mono=pcm_frame[:1000], sample_rate=16000, is_final=False)
        yield TTSPcmChunk(pcm16_mono=pcm_frame[1000:] + pcm_frame, sample_rate=16000, is_final=True)

    clock = FakeClock()
    websocket = RecordingWebSocket(clock)
    sender = make_sender(websocket, clock)

    result = await sender.play(
        "turn-a",
        7,
        "streamed",
        encode_pcm16_mono_chunks_to_opus_frames(chunks()),
    )

    opus_frames = [payload for kind, payload, _ in websocket.events if kind == "bytes"]
    assert result.status == "ok"
    assert len(opus_frames) == 2
    decoder = opuslib_next.Decoder(16000, 1)
    try:
        assert all(len(decoder.decode(frame, 960)) == len(pcm_frame) for frame in opus_frames)
    finally:
        del decoder
