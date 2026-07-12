from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from buddy_gateway.audio_frames import ParsedAudioFrame
from buddy_gateway.config import require_positive_frame_count
from buddy_gateway.session_runtime import GatewaySessionRuntime
from buddy_gateway.state import GatewayState, new_asr_turn_id


SAMPLE_RATE = 16000
CHANNELS = 1
FRAME_DURATION_MS = 60
PREROLL_FRAME_LIMIT = 10
MIN_AUTO_TURN_FRAMES = 16


@dataclass(frozen=True)
class TurnAudio:
    pcm_bytes: bytes
    opus_frames: tuple[bytes, ...]
    sample_rate: int
    channels: int
    frame_duration_ms: int
    frame_count: int


class VoiceTurnProcessor(Protocol):
    async def transcribe(self, turn_id: str, audio: TurnAudio) -> str:
        ...

    async def process_text(self, turn_id: str, text: str) -> None:
        ...


class GatewayVoicePipeline:
    def __init__(
        self,
        *,
        runtime: GatewaySessionRuntime,
        state: GatewayState,
        processor: VoiceTurnProcessor,
        turn_id_factory: Callable[[], str] = new_asr_turn_id,
        vad_preroll_frames: int = PREROLL_FRAME_LIMIT,
        vad_min_turn_frames: int = MIN_AUTO_TURN_FRAMES,
    ) -> None:
        self._runtime = runtime
        self._state = state
        self._processor = processor
        self._turn_id_factory = turn_id_factory
        self._vad_preroll_frames = require_positive_frame_count(
            "vad_preroll_frames", vad_preroll_frames
        )
        self._vad_min_turn_frames = require_positive_frame_count(
            "vad_min_turn_frames", vad_min_turn_frames
        )
        self._listening = False

    async def handle_listen(self, payload: dict[str, Any]) -> None:
        listen_state = payload.get("state")
        if listen_state == "start":
            await self._invalidate_active("listen start")
            mode = payload.get("mode")
            if mode in {"auto", "manual"}:
                self._runtime.listen_mode = mode
                setattr(self._runtime.vad_session, "listen_mode", mode)
            self._runtime.reset_input()
            self._listening = True
            return

        if listen_state == "stop":
            self._listening = False
            await self._finalize_audio_turn(trigger="listen_stop")
            return

        if listen_state == "detect":
            generation = await self._invalidate_active("listen detect")
            self._runtime.reset_input()
            self._listening = False
            text = payload.get("text")
            if isinstance(text, str) and text:
                turn_id = self._turn_id_factory()
                self._runtime.active_asr_turn_id = turn_id
                self._runtime.turn_task = asyncio.create_task(
                    self._run_detect_turn(turn_id, generation, text)
                )

    async def handle_audio(self, frame: ParsedAudioFrame) -> None:
        if not self._listening or self._runtime.closing or self._runtime.closed:
            return

        pcm_frame = self._runtime.decode_opus(bytes(frame.payload))
        if not pcm_frame:
            self._record_event("decode_error")
            return

        pcm_frame = bytes(pcm_frame)
        opus_frame = bytes(frame.payload)
        if self._runtime.listen_mode == "manual":
            self._runtime.turn_pcm_frames.append(pcm_frame)
            self._runtime.turn_opus_frames.append(opus_frame)
            return

        try:
            vad = self._runtime.vad_session.analyze(pcm_frame)
        except Exception as exc:
            self._record_event("pipeline_error", error=str(exc))
            self._runtime.reset_input()
            return

        if not self._runtime.turn_pcm_frames:
            if not vad.has_voice:
                while len(self._runtime.preroll_pcm) >= self._vad_preroll_frames:
                    self._runtime.preroll_pcm.popleft()
                self._runtime.preroll_pcm.append(pcm_frame)
                return
            self._runtime.turn_pcm_frames.extend(self._runtime.preroll_pcm)
            self._runtime.preroll_pcm.clear()
            self._record_event("speech_start")

        self._runtime.turn_pcm_frames.append(pcm_frame)
        self._runtime.turn_opus_frames.append(opus_frame)
        if not vad.speech_stopped:
            return

        self._record_event("speech_stop")
        if len(self._runtime.turn_pcm_frames) < self._vad_min_turn_frames:
            self._record_event("discarded_short_turn")
            self._runtime.reset_input()
            return
        await self._finalize_audio_turn(trigger="vad_speech_stop")

    async def handle_abort(self) -> None:
        await self._invalidate_active("device abort")
        self._runtime.reset_input()
        self._listening = False

    async def close(self) -> None:
        if self._runtime.closed:
            return
        await self.handle_abort()
        await self._runtime.close()

    async def _finalize_audio_turn(self, *, trigger: str) -> None:
        if not self._runtime.turn_pcm_frames:
            return

        audio = TurnAudio(
            pcm_bytes=b"".join(self._runtime.turn_pcm_frames),
            opus_frames=tuple(bytes(frame) for frame in self._runtime.turn_opus_frames),
            sample_rate=SAMPLE_RATE,
            channels=CHANNELS,
            frame_duration_ms=FRAME_DURATION_MS,
            frame_count=len(self._runtime.turn_pcm_frames),
        )
        generation = await self._invalidate_active("turn finalized")
        turn_id = self._turn_id_factory()
        self._runtime.reset_input()
        self._runtime.active_asr_turn_id = turn_id
        self._state.start_asr_turn(
            self._runtime.session_id,
            trigger=trigger,
            turn_id=turn_id,
        )
        self._runtime.turn_task = asyncio.create_task(
            self._run_audio_turn(turn_id, generation, audio)
        )

    async def _run_audio_turn(self, turn_id: str, generation: int, audio: TurnAudio) -> None:
        if not self._is_current(turn_id, generation):
            self._mark_aborted(turn_id)
            return
        try:
            transcript = await self._processor.transcribe(turn_id, audio)
            if not self._is_current(turn_id, generation):
                self._mark_aborted(turn_id)
                return
            transcript = transcript.strip()
            if not transcript:
                self._state.update_asr_turn(
                    self._runtime.session_id,
                    turn_id,
                    status="no_text",
                    transcript="",
                    audio_frame_count=audio.frame_count,
                )
                return
            await self._processor.process_text(turn_id, transcript)
            if not self._is_current(turn_id, generation):
                self._mark_aborted(turn_id)
                return
            self._state.update_asr_turn(
                self._runtime.session_id,
                turn_id,
                status="ok",
                transcript=transcript,
                audio_frame_count=audio.frame_count,
            )
        except asyncio.CancelledError:
            self._mark_aborted(turn_id)
            raise
        except Exception as exc:
            if not self._is_current(turn_id, generation):
                self._mark_aborted(turn_id)
                return
            self._record_event("pipeline_error", error=str(exc))
            self._state.update_asr_turn(
                self._runtime.session_id,
                turn_id,
                status="error",
                error=str(exc),
                audio_frame_count=audio.frame_count,
            )

    async def _run_detect_turn(self, turn_id: str, generation: int, text: str) -> None:
        if not self._is_current(turn_id, generation):
            return
        try:
            await self._processor.process_text(turn_id, text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._is_current(turn_id, generation):
                self._record_event("pipeline_error", error=str(exc))

    async def _invalidate_active(self, reason: str) -> int:
        generation = self._runtime.invalidate_turn(reason)
        task = self._runtime.turn_task
        if task is None or task.done() or task is asyncio.current_task():
            return generation
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        if self._runtime.turn_task is task:
            self._runtime.turn_task = None
        return generation

    def _is_current(self, turn_id: str, generation: int) -> bool:
        return (
            not self._runtime.closing
            and not self._runtime.closed
            and self._runtime.turn_generation == generation
            and self._runtime.active_asr_turn_id == turn_id
        )

    def _mark_aborted(self, turn_id: str) -> None:
        self._state.update_asr_turn(
            self._runtime.session_id,
            turn_id,
            status="aborted",
            error=self._runtime.last_invalidation_reason,
        )

    def _record_event(self, event: str, *, error: str | None = None) -> None:
        self._state.record_vad_event(
            self._runtime.session_id,
            event,
            error=error,
        )
