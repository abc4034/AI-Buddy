import asyncio
from dataclasses import FrozenInstanceError

import pytest

from buddy_gateway.audio_frames import ParsedAudioFrame
from buddy_gateway.session_runtime import GatewaySessionRuntime
from buddy_gateway.state import GatewayState
from buddy_gateway.vad import VADDecision
from buddy_gateway.voice_pipeline import GatewayVoicePipeline, TurnAudio


class FakeVADSession:
    def __init__(
        self,
        decisions: list[VADDecision] | None = None,
        *,
        listen_mode: str = "auto",
    ) -> None:
        self.decisions = list(decisions or [])
        self.listen_mode = listen_mode
        self.analyzed: list[bytes] = []
        self.reset_count = 0
        self.close_count = 0
        self.error: Exception | None = None

    def analyze(self, pcm_frame: bytes) -> VADDecision:
        self.analyzed.append(pcm_frame)
        if self.error is not None:
            raise self.error
        if self.listen_mode == "manual":
            return decision(voice=True)
        if self.decisions:
            return self.decisions.pop(0)
        return decision()

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
        if opus_frame == b"bad":
            return b""
        return b"pcm:" + opus_frame

    def close(self) -> None:
        self.close_count += 1


class FakeProcessor:
    def __init__(self) -> None:
        self.audio_calls: list[tuple[str, TurnAudio]] = []
        self.text_calls: list[tuple[str, str]] = []
        self.transcript = "hello"
        self.transcribe_started: asyncio.Event | None = None
        self.release_transcribe: asyncio.Event | None = None
        self.text_started: asyncio.Event | None = None
        self.release_text: asyncio.Event | None = None
        self.suppress_cancellation = False
        self.error: Exception | None = None
        self.text_error: Exception | None = None

    async def transcribe(self, turn_id: str, audio: TurnAudio) -> str:
        self.audio_calls.append((turn_id, audio))
        if self.transcribe_started is not None:
            self.transcribe_started.set()
        if self.release_transcribe is not None:
            try:
                await self.release_transcribe.wait()
            except asyncio.CancelledError:
                if not self.suppress_cancellation:
                    raise
        if self.error is not None:
            raise self.error
        return self.transcript

    async def process_text(self, turn_id: str, text: str) -> None:
        self.text_calls.append((turn_id, text))
        if self.text_started is not None:
            self.text_started.set()
        if self.release_text is not None:
            try:
                await self.release_text.wait()
            except asyncio.CancelledError:
                if not self.suppress_cancellation:
                    raise
        if self.text_error is not None:
            raise self.text_error


def decision(*, voice: bool = False, stopped: bool = False) -> VADDecision:
    return VADDecision(
        speech_probability=1.0 if voice else 0.0,
        has_voice=voice,
        speech_stopped=stopped,
    )


def frame(index: int | str) -> ParsedAudioFrame:
    payload = f"opus-{index}".encode()
    return ParsedAudioFrame(
        payload=payload,
        raw_size=len(payload),
        timestamp=None,
        sequence=None,
        mode="raw_opus",
    )


def make_pipeline(
    *,
    mode: str = "auto",
    decisions: list[VADDecision] | None = None,
    vad_preroll_frames: int = 10,
    vad_min_turn_frames: int = 16,
) -> tuple[GatewayVoicePipeline, GatewaySessionRuntime, FakeVADSession, FakeDecoder, FakeProcessor, GatewayState]:
    vad = FakeVADSession(decisions, listen_mode=mode)
    decoder = FakeDecoder()
    state = GatewayState()
    session = state.start_session(
        device_id="device-a",
        client_id="client-a",
        remote_address=None,
        headers={},
    )
    runtime = GatewaySessionRuntime(
        session_id=session.session_id,
        listen_mode=mode,
        vad_session=vad,
        opus_decoder=decoder,
    )
    processor = FakeProcessor()
    ids = iter(f"turn-{index}" for index in range(1, 20))
    pipeline = GatewayVoicePipeline(
        runtime=runtime,
        state=state,
        processor=processor,
        turn_id_factory=lambda: next(ids),
        vad_preroll_frames=vad_preroll_frames,
        vad_min_turn_frames=vad_min_turn_frames,
    )
    return pipeline, runtime, vad, decoder, processor, state


async def wait_for_turn(runtime: GatewaySessionRuntime) -> None:
    assert runtime.turn_task is not None
    await runtime.turn_task


@pytest.mark.asyncio
async def test_auto_keeps_ten_frame_preroll_and_hands_off_one_immutable_turn():
    decisions = [decision()] * 12 + [decision(voice=True)] + [decision()] * 4 + [decision(stopped=True)]
    pipeline, runtime, _, decoder, processor, _ = make_pipeline(decisions=decisions)

    await pipeline.handle_listen({"state": "start", "mode": "auto"})
    for index in range(18):
        await pipeline.handle_audio(frame(index))
    await wait_for_turn(runtime)

    assert len(processor.audio_calls) == 1
    turn_id, audio = processor.audio_calls[0]
    assert turn_id == "turn-1"
    assert audio.pcm_bytes == b"".join(b"pcm:" + frame(index).payload for index in range(2, 18))
    assert audio.opus_frames == tuple(frame(index).payload for index in range(12, 18))
    assert (audio.sample_rate, audio.channels, audio.frame_duration_ms, audio.frame_count) == (16000, 1, 60, 16)
    assert decoder.calls == [(frame(index).payload, 960) for index in range(18)]
    assert processor.text_calls == [("turn-1", "hello")]
    with pytest.raises(FrozenInstanceError):
        audio.frame_count = 99


@pytest.mark.asyncio
async def test_auto_discards_turn_shorter_than_sixteen_frames():
    pipeline, runtime, _, _, processor, state = make_pipeline(
        decisions=[decision(voice=True), decision(), decision(stopped=True)]
    )

    await pipeline.handle_listen({"state": "start", "mode": "auto"})
    for index in range(3):
        await pipeline.handle_audio(frame(index))

    assert runtime.turn_task is None
    assert processor.audio_calls == []
    assert runtime.turn_pcm_frames == []
    assert [event["event"] for event in state.session_summary(runtime.session_id)["vad_events"]] == [
        "speech_start",
        "speech_stop",
        "discarded_short_turn",
    ]


@pytest.mark.asyncio
async def test_manual_bypasses_vad_and_finalizes_only_on_listen_stop():
    pipeline, runtime, vad, _, processor, _ = make_pipeline(mode="manual")

    await pipeline.handle_audio(frame("before-start"))
    await pipeline.handle_listen({"state": "start", "mode": "manual"})
    for index in range(3):
        await pipeline.handle_audio(frame(index))
    assert runtime.turn_task is None

    await pipeline.handle_listen({"state": "stop"})
    await wait_for_turn(runtime)

    audio = processor.audio_calls[0][1]
    assert audio.pcm_bytes == b"pcm:opus-0pcm:opus-1pcm:opus-2"
    assert audio.opus_frames == (b"opus-0", b"opus-1", b"opus-2")
    assert audio.frame_count == 3
    assert vad.analyzed == []


@pytest.mark.asyncio
async def test_auto_listen_stop_finalizes_buffered_speech_exactly_once_before_vad_silence():
    pipeline, runtime, _, _, processor, _ = make_pipeline(
        decisions=[decision(voice=True), decision()]
    )

    await pipeline.handle_listen({"state": "start", "mode": "auto"})
    await pipeline.handle_audio(frame(0))
    await pipeline.handle_audio(frame(1))
    await pipeline.handle_listen({"state": "stop"})
    await wait_for_turn(runtime)
    await pipeline.handle_listen({"state": "stop"})

    assert len(processor.audio_calls) == 1
    assert processor.audio_calls[0][1].frame_count == 2


@pytest.mark.asyncio
async def test_non_default_preroll_limit_changes_auto_turn_segmentation():
    pipeline, runtime, _, _, processor, _ = make_pipeline(
        decisions=[decision()] * 4 + [decision(voice=True), decision(stopped=True)],
        vad_preroll_frames=2,
        vad_min_turn_frames=4,
    )

    await pipeline.handle_listen({"state": "start", "mode": "auto"})
    for index in range(6):
        await pipeline.handle_audio(frame(index))
    await wait_for_turn(runtime)

    audio = processor.audio_calls[0][1]
    assert audio.pcm_bytes == b"".join(b"pcm:" + frame(index).payload for index in range(2, 6))
    assert audio.frame_count == 4


@pytest.mark.asyncio
async def test_non_default_minimum_accepts_shorter_auto_turn():
    pipeline, runtime, _, _, processor, _ = make_pipeline(
        decisions=[decision(voice=True), decision(stopped=True)],
        vad_min_turn_frames=2,
    )

    await pipeline.handle_listen({"state": "start", "mode": "auto"})
    await pipeline.handle_audio(frame(0))
    await pipeline.handle_audio(frame(1))
    await wait_for_turn(runtime)

    assert len(processor.audio_calls) == 1
    assert processor.audio_calls[0][1].frame_count == 2


@pytest.mark.parametrize("field", ["vad_preroll_frames", "vad_min_turn_frames"])
def test_pipeline_rejects_non_positive_segmentation_values(field: str):
    kwargs = {field: 0}

    with pytest.raises(ValueError, match=field):
        make_pipeline(**kwargs)


@pytest.mark.asyncio
async def test_listen_start_switches_manual_vad_session_to_auto_inference():
    decisions = [decision(voice=True)] + [decision()] * 14 + [decision(stopped=True)]
    pipeline, runtime, vad, _, processor, _ = make_pipeline(mode="manual", decisions=decisions)

    await pipeline.handle_listen({"state": "start", "mode": "auto"})
    for index in range(16):
        await pipeline.handle_audio(frame(index))
    await wait_for_turn(runtime)

    assert runtime.listen_mode == "auto"
    assert vad.listen_mode == "auto"
    assert len(vad.analyzed) == 16
    assert len(processor.audio_calls) == 1


@pytest.mark.asyncio
async def test_audio_is_ignored_until_listen_start():
    pipeline, runtime, vad, decoder, processor, _ = make_pipeline(mode="manual")

    await pipeline.handle_audio(frame(1))
    await pipeline.handle_listen({"state": "stop"})

    assert runtime.turn_task is None
    assert decoder.calls == []
    assert vad.analyzed == []
    assert processor.audio_calls == []


@pytest.mark.asyncio
async def test_detect_with_text_resets_input_and_skips_asr():
    pipeline, runtime, vad, _, processor, _ = make_pipeline()
    runtime.turn_pcm_frames.append(b"old")

    await pipeline.handle_listen({"state": "detect", "text": "typed words"})
    await wait_for_turn(runtime)

    assert processor.audio_calls == []
    assert processor.text_calls == [("turn-1", "typed words")]
    assert runtime.turn_pcm_frames == []
    assert vad.reset_count == 1


@pytest.mark.asyncio
async def test_detect_without_text_only_resets_input():
    pipeline, runtime, vad, _, processor, _ = make_pipeline()
    runtime.turn_pcm_frames.append(b"old")

    await pipeline.handle_listen({"state": "detect", "text": ""})

    assert processor.audio_calls == []
    assert processor.text_calls == []
    assert runtime.turn_task is None
    assert runtime.turn_pcm_frames == []
    assert vad.reset_count == 1


@pytest.mark.asyncio
async def test_abort_generation_blocks_next_paid_stage_even_if_transcribe_suppresses_cancellation():
    pipeline, runtime, _, _, processor, state = make_pipeline(mode="manual")
    processor.transcribe_started = asyncio.Event()
    processor.release_transcribe = asyncio.Event()
    processor.suppress_cancellation = True

    await pipeline.handle_listen({"state": "start", "mode": "manual"})
    await pipeline.handle_audio(frame(1))
    await pipeline.handle_listen({"state": "stop"})
    await processor.transcribe_started.wait()
    generation_before_abort = runtime.turn_generation

    await pipeline.handle_abort()

    assert runtime.turn_generation == generation_before_abort + 1
    assert processor.text_calls == []
    assert state.session_summary(runtime.session_id)["asr_turns"][0]["status"] == "aborted"


@pytest.mark.asyncio
async def test_stale_transcribe_error_records_aborted_without_pipeline_error():
    pipeline, runtime, _, _, processor, state = make_pipeline(mode="manual")
    processor.transcribe_started = asyncio.Event()
    processor.release_transcribe = asyncio.Event()
    processor.suppress_cancellation = True
    processor.error = RuntimeError("stale asr failure")

    await pipeline.handle_listen({"state": "start", "mode": "manual"})
    await pipeline.handle_audio(frame(1))
    await pipeline.handle_listen({"state": "stop"})
    await processor.transcribe_started.wait()
    await pipeline.handle_abort()

    summary = state.session_summary(runtime.session_id)
    assert summary["asr_turns"][0]["status"] == "aborted"
    assert summary["vad_events"] == []


@pytest.mark.asyncio
async def test_stale_detect_error_does_not_record_pipeline_diagnostic():
    pipeline, runtime, _, _, processor, state = make_pipeline()
    processor.text_started = asyncio.Event()
    processor.release_text = asyncio.Event()
    processor.suppress_cancellation = True
    processor.text_error = RuntimeError("stale detect failure")

    await pipeline.handle_listen({"state": "detect", "text": "typed words"})
    await processor.text_started.wait()
    await pipeline.handle_abort()

    summary = state.session_summary(runtime.session_id)
    assert summary["asr_turns"] == []
    assert summary["vad_events"] == []


@pytest.mark.asyncio
async def test_decode_and_pipeline_errors_are_diagnostic_and_do_not_close_session():
    pipeline, runtime, vad, _, processor, state = make_pipeline(decisions=[decision(voice=True)])

    await pipeline.handle_listen({"state": "start", "mode": "auto"})
    bad = ParsedAudioFrame(payload=b"bad", raw_size=3, timestamp=None, sequence=None, mode="raw_opus")
    await pipeline.handle_audio(bad)
    vad.error = RuntimeError("vad failed")
    await pipeline.handle_audio(frame(1))
    processor.error = RuntimeError("asr failed")
    runtime.listen_mode = "manual"
    await pipeline.handle_audio(frame(2))
    await pipeline.handle_listen({"state": "stop"})
    await wait_for_turn(runtime)

    events = state.session_summary(runtime.session_id)["vad_events"]
    assert [(event["event"], event["error"]) for event in events] == [
        ("decode_error", None),
        ("pipeline_error", "vad failed"),
        ("pipeline_error", "asr failed"),
    ]
    assert runtime.closed is False


def test_vad_diagnostics_keep_only_latest_twenty_events_without_probabilities():
    state = GatewayState()
    session = state.start_session(device_id=None, client_id=None, remote_address=None, headers={})

    for index in range(25):
        state.record_vad_event(session.session_id, "decode_error", error=str(index))

    events = state.session_summary(session.session_id)["vad_events"]
    assert len(events) == 20
    assert [event["error"] for event in events] == [str(index) for index in range(5, 25)]
    assert all("probability" not in event for event in events)


@pytest.mark.asyncio
async def test_close_aborts_work_and_releases_runtime_once():
    pipeline, runtime, vad, decoder, processor, _ = make_pipeline(mode="manual")
    processor.transcribe_started = asyncio.Event()
    processor.release_transcribe = asyncio.Event()

    await pipeline.handle_listen({"state": "start", "mode": "manual"})
    await pipeline.handle_audio(frame(1))
    await pipeline.handle_listen({"state": "stop"})
    await processor.transcribe_started.wait()

    await pipeline.close()
    await pipeline.close()

    assert runtime.closed is True
    assert vad.close_count == 1
    assert decoder.close_count == 1
    assert processor.text_calls == []
