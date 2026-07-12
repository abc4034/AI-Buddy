from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal


PlaybackStatus = Literal["ok", "aborted", "error"]


@dataclass(frozen=True)
class DevicePlaybackResult:
    turn_id: str
    generation: int
    status: PlaybackStatus
    frame_count: int
    error: str | None = None


@dataclass
class _ActivePlayback:
    turn_id: str
    generation: int
    task: asyncio.Task[Any] | None
    frame_count: int = 0
    started: bool = False
    stop_sent: bool = False
    stop_task: asyncio.Task[bool] | None = None
    abort_reason: str | None = None


async def _noop_drain() -> None:
    return None


class DeviceAudioSender:
    BURST_FRAME_COUNT = 5
    FRAME_INTERVAL_SECONDS = 0.060
    PLAYBACK_TAIL_SECONDS = 0.420

    def __init__(
        self,
        websocket: Any,
        *,
        session_id: str,
        is_generation_current: Callable[[str, int], bool],
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        drain: Callable[[], Awaitable[None]] = _noop_drain,
        is_open: Callable[[], bool] | None = None,
    ) -> None:
        self._websocket = websocket
        self._session_id = session_id
        self._is_generation_current = is_generation_current
        self._monotonic = monotonic
        self._sleep = sleep
        self._drain = drain
        self._is_open_callback = is_open
        self._active: _ActivePlayback | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._stop_tasks: set[asyncio.Task[bool]] = set()
        self._closed = False
        self._close_complete = False
        self._stop_suppressed = False

    async def play(
        self,
        turn_id: str,
        generation: int,
        text: str,
        opus_frames: AsyncIterator[bytes],
    ) -> DevicePlaybackResult:
        async with self._lifecycle_lock:
            if self._closed:
                return DevicePlaybackResult(turn_id, generation, "aborted", 0, "sender closed")
            await self._end_active("superseded by a new playback", send_stop=True)
            if self._closed:
                return DevicePlaybackResult(turn_id, generation, "aborted", 0, "sender closed")
            playback = _ActivePlayback(turn_id, generation, asyncio.current_task())
            self._active = playback

        return await self._run_playback(playback, text, opus_frames)

    async def _run_playback(
        self,
        playback: _ActivePlayback,
        text: str,
        opus_frames: AsyncIterator[bytes],
    ) -> DevicePlaybackResult:
        try:
            playback.started = True
            if not await self._send_control(playback, "start"):
                return self._aborted_result(playback)
            if not await self._send_control(playback, "sentence_start", text=text):
                return self._aborted_result(playback)

            queued_origin: float | None = None
            iterator = opus_frames.__aiter__()
            while True:
                producer_wait_started = self._monotonic()
                try:
                    opus_frame = await anext(iterator)
                except StopAsyncIteration:
                    break
                frame_acquired_at = self._monotonic()
                if not self._is_current_and_open(playback):
                    return self._aborted_result(playback)

                frame_index = playback.frame_count
                if frame_index >= self.BURST_FRAME_COUNT:
                    queued_position = (
                        frame_index - self.BURST_FRAME_COUNT
                    ) * self.FRAME_INTERVAL_SECONDS
                    if queued_origin is None:
                        queued_origin = frame_acquired_at
                    elif (
                        frame_acquired_at - producer_wait_started
                        >= self.FRAME_INTERVAL_SECONDS
                    ):
                        queued_origin = frame_acquired_at - queued_position
                    target = queued_origin + queued_position
                    delay = target - self._monotonic()
                    if delay > 0:
                        await self._sleep(delay)

                if not self._is_current_and_open(playback):
                    return self._aborted_result(playback)
                if not await self._send_audio(playback, bytes(opus_frame)):
                    return self._aborted_result(playback)
                playback.frame_count += 1

            if not self._is_current_and_open(playback):
                return self._aborted_result(playback)
            await self._drain()
            if not self._is_current_and_open(playback):
                return self._aborted_result(playback)
            await self._sleep(self.PLAYBACK_TAIL_SECONDS)
            if not await self._send_stop(playback, require_current=True):
                return self._aborted_result(playback)
            return DevicePlaybackResult(
                playback.turn_id,
                playback.generation,
                "ok",
                playback.frame_count,
            )
        except asyncio.CancelledError:
            if playback.abort_reason is None and self._active is playback and not self._closed:
                raise
            return self._aborted_result(playback)
        except Exception as exc:
            if playback.started:
                try:
                    await self._send_stop(playback, require_current=True)
                except Exception:
                    pass
            return DevicePlaybackResult(
                playback.turn_id,
                playback.generation,
                "error",
                playback.frame_count,
                str(exc),
            )
        finally:
            if self._active is playback:
                self._active = None

    async def abort(self, reason: str) -> None:
        async with self._lifecycle_lock:
            await self._end_active(reason, send_stop=True)

    async def close(self, *, send_stop: bool) -> None:
        if not send_stop:
            self._closed = True
            self._stop_suppressed = True
            self._cancel_stop_tasks()

        async with self._lifecycle_lock:
            if self._close_complete:
                return
            self._closed = True
            await self._end_active(
                "sender closed",
                send_stop=send_stop and not self._stop_suppressed,
            )
            self._close_complete = True

    async def _end_active(self, reason: str, *, send_stop: bool) -> None:
        playback = self._invalidate_active(reason)
        if playback is None:
            return
        self._cancel_playback_task(playback)
        await self._await_playback_task(playback)
        if send_stop and playback.started and not self._stop_suppressed:
            try:
                await self._send_stop(playback, require_current=False)
            except Exception:
                pass

    def _invalidate_active(self, reason: str) -> _ActivePlayback | None:
        playback = self._active
        if playback is None:
            return None
        playback.abort_reason = reason
        self._active = None
        return playback

    @staticmethod
    def _cancel_playback_task(playback: _ActivePlayback) -> None:
        task = playback.task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

    @staticmethod
    async def _await_playback_task(playback: _ActivePlayback) -> None:
        task = playback.task
        if task is None or task is asyncio.current_task() or task.done():
            return
        try:
            await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise

    def _cancel_stop_tasks(self) -> None:
        for task in tuple(self._stop_tasks):
            if not task.done():
                task.cancel()

    async def _send_control(
        self,
        playback: _ActivePlayback,
        state: str,
        *,
        text: str | None = None,
    ) -> bool:
        payload: dict[str, object] = {
            "type": "tts",
            "state": state,
            "session_id": self._session_id,
        }
        if text is not None:
            payload["text"] = text
        async with self._write_lock:
            if not self._is_current_and_open(playback):
                return False
            await self._websocket.send_json(payload)
            return True

    async def _send_audio(self, playback: _ActivePlayback, payload: bytes) -> bool:
        async with self._write_lock:
            if not self._is_current_and_open(playback):
                return False
            await self._websocket.send_bytes(payload)
            return True

    async def _send_stop(self, playback: _ActivePlayback, *, require_current: bool) -> bool:
        while True:
            if playback.stop_sent:
                return True
            if self._stop_suppressed:
                return False

            stop_task = playback.stop_task
            if stop_task is None:
                stop_task = asyncio.create_task(
                    self._deliver_stop(playback, require_current=require_current)
                )
                playback.stop_task = stop_task
                self._stop_tasks.add(stop_task)
                stop_task.add_done_callback(self._stop_tasks.discard)

            try:
                delivered = await asyncio.shield(stop_task)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if stop_task.cancelled() and (current is None or not current.cancelling()):
                    return False
                raise

            if delivered or require_current or self._stop_suppressed:
                return delivered
            if playback.stop_task is stop_task:
                playback.stop_task = None

    async def _deliver_stop(
        self,
        playback: _ActivePlayback,
        *,
        require_current: bool,
    ) -> bool:
        async with self._write_lock:
            if playback.stop_sent or self._stop_suppressed or not self._transport_is_open():
                return playback.stop_sent
            if require_current and not self._is_current_and_open(playback):
                return False
            await self._websocket.send_json(
                {"type": "tts", "state": "stop", "session_id": self._session_id}
            )
            playback.stop_sent = True
            return True

    def _is_current_and_open(self, playback: _ActivePlayback) -> bool:
        return (
            not self._closed
            and self._active is playback
            and self._transport_is_open()
            and self._is_generation_current(playback.turn_id, playback.generation)
        )

    def _transport_is_open(self) -> bool:
        if self._is_open_callback is not None:
            return bool(self._is_open_callback())
        state = getattr(self._websocket, "application_state", None)
        if state is None:
            return True
        state_name = getattr(state, "name", None)
        if state_name is None:
            state_name = str(state).rsplit(".", 1)[-1]
        return str(state_name).upper() == "CONNECTED"

    @staticmethod
    def _aborted_result(playback: _ActivePlayback) -> DevicePlaybackResult:
        return DevicePlaybackResult(
            playback.turn_id,
            playback.generation,
            "aborted",
            playback.frame_count,
            playback.abort_reason,
        )
