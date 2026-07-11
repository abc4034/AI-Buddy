from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import opuslib_next

from buddy_gateway.opus_codec import decode_opus_frame_to_pcm, release_opus_decoder
from buddy_gateway.vad import VADSession


@dataclass
class GatewaySessionRuntime:
    session_id: str
    listen_mode: str
    vad_session: VADSession
    opus_decoder: opuslib_next.Decoder
    preroll_pcm: deque[bytes] = field(default_factory=deque)
    turn_pcm_frames: list[bytes] = field(default_factory=list)
    turn_opus_frames: list[bytes] = field(default_factory=list)
    active_asr_turn_id: str | None = None
    turn_generation: int = 0
    turn_task: asyncio.Task[Any] | None = None
    closing: bool = False
    closed: bool = False
    opus_decode_error_count: int = 0
    last_invalidation_reason: str | None = None
    _close_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def decode_opus(self, opus_frame: bytes) -> bytes:
        try:
            return decode_opus_frame_to_pcm(self.opus_decoder, opus_frame, frame_size=960)
        except opuslib_next.OpusError:
            self.opus_decode_error_count += 1
            return b""

    def invalidate_turn(self, reason: str) -> int:
        self.turn_generation += 1
        self.last_invalidation_reason = reason
        return self.turn_generation

    def reset_input(self) -> None:
        self.vad_session.reset()
        self.preroll_pcm.clear()
        self.turn_pcm_frames.clear()
        self.turn_opus_frames.clear()
        self.active_asr_turn_id = None

    async def close(self) -> None:
        async with self._close_lock:
            if self.closed:
                return
            self.closing = True
            try:
                if self.turn_task is not None:
                    if not self.turn_task.done():
                        self.turn_task.cancel()
                    try:
                        await self.turn_task
                    except asyncio.CancelledError:
                        pass
                self.vad_session.close()
                release_opus_decoder(self.opus_decoder)
                self.closed = True
            finally:
                self.closing = False
