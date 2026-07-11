import asyncio
from collections import deque

import opuslib_next
import pytest

from buddy_gateway.session_runtime import GatewaySessionRuntime


class FakeVADSession:
    def __init__(self) -> None:
        self.reset_count = 0
        self.close_count = 0

    def analyze(self, pcm_frame: bytes):
        raise AssertionError("not used")

    def reset(self) -> None:
        self.reset_count += 1

    def close(self) -> None:
        self.close_count += 1


class FakeDecoder:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, int]] = []
        self.close_count = 0

    def decode(self, opus_frame: bytes, frame_size: int) -> bytes:
        self.calls.append((opus_frame, frame_size))
        if opus_frame == b"malformed":
            raise opuslib_next.OpusError("invalid packet")
        return b"pcm:" + opus_frame

    def close(self) -> None:
        self.close_count += 1


def make_runtime() -> tuple[GatewaySessionRuntime, FakeVADSession, FakeDecoder]:
    vad = FakeVADSession()
    decoder = FakeDecoder()
    runtime = GatewaySessionRuntime(
        session_id="session-a",
        listen_mode="auto",
        vad_session=vad,
        opus_decoder=decoder,
    )
    return runtime, vad, decoder


def test_runtime_reuses_one_decoder_with_960_sample_frames():
    runtime, _, decoder = make_runtime()

    assert runtime.decode_opus(b"one") == b"pcm:one"
    assert runtime.decode_opus(b"two") == b"pcm:two"
    assert decoder.calls == [(b"one", 960), (b"two", 960)]


def test_runtime_skips_malformed_opus_and_increments_diagnostic():
    runtime, _, _ = make_runtime()

    assert runtime.decode_opus(b"malformed") == b""
    assert runtime.opus_decode_error_count == 1
    assert runtime.closed is False


def test_runtime_generation_is_the_monotonic_stale_work_authority():
    runtime, _, _ = make_runtime()

    first = runtime.invalidate_turn("listen start")
    second = runtime.invalidate_turn("device abort")

    assert (first, second) == (1, 2)
    assert runtime.turn_generation == 2
    assert runtime.last_invalidation_reason == "device abort"


def test_runtime_reset_input_clears_turn_buffers_and_vad_state():
    runtime, vad, _ = make_runtime()
    runtime.preroll_pcm.extend([b"before"])
    runtime.turn_pcm_frames.append(b"pcm")
    runtime.turn_opus_frames.append(b"opus")
    runtime.active_asr_turn_id = "turn-a"

    runtime.reset_input()

    assert runtime.preroll_pcm == deque()
    assert runtime.turn_pcm_frames == []
    assert runtime.turn_opus_frames == []
    assert runtime.active_asr_turn_id is None
    assert vad.reset_count == 1


@pytest.mark.asyncio
async def test_runtime_close_cancels_turn_and_releases_resources_exactly_once():
    runtime, vad, decoder = make_runtime()
    started = asyncio.Event()

    async def pending_turn() -> None:
        started.set()
        await asyncio.Event().wait()

    runtime.turn_task = asyncio.create_task(pending_turn())
    await started.wait()

    await asyncio.gather(runtime.close(), runtime.close())
    await runtime.close()

    assert runtime.turn_task.cancelled()
    assert vad.close_count == 1
    assert decoder.close_count == 1
    assert runtime.closing is False
    assert runtime.closed is True
