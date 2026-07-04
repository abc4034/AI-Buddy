from __future__ import annotations

import asyncio
from dataclasses import dataclass

from buddy_gateway.audio_frames import ParsedAudioFrame
from buddy_gateway.audio_store import AudioArtifactStore


@dataclass(frozen=True)
class AudioFrameWrite:
    session_id: str
    device_id: str | None
    client_id: str | None
    frame: ParsedAudioFrame


class AudioArtifactWriter:
    def __init__(self, store: AudioArtifactStore) -> None:
        self.store = store
        self._queues: dict[str, asyncio.Queue[AudioFrameWrite | None]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def start_session(self, session_id: str) -> None:
        if session_id in self._queues:
            return
        queue: asyncio.Queue[AudioFrameWrite | None] = asyncio.Queue()
        self._queues[session_id] = queue
        self._tasks[session_id] = asyncio.create_task(self._run(queue))

    async def enqueue_frame(
        self,
        *,
        session_id: str,
        device_id: str | None,
        client_id: str | None,
        frame: ParsedAudioFrame,
    ) -> None:
        if session_id not in self._queues:
            self.start_session(session_id)
        await self._queues[session_id].put(
            AudioFrameWrite(
                session_id=session_id,
                device_id=device_id,
                client_id=client_id,
                frame=frame,
            )
        )

    async def finish_session(self, session_id: str) -> None:
        queue = self._queues.pop(session_id, None)
        task = self._tasks.pop(session_id, None)
        if queue is None or task is None:
            return
        await queue.put(None)
        await task

    async def _run(self, queue: asyncio.Queue[AudioFrameWrite | None]) -> None:
        while True:
            item = await queue.get()
            try:
                if item is None:
                    return
                await asyncio.to_thread(
                    self.store.record_frame,
                    session_id=item.session_id,
                    device_id=item.device_id,
                    client_id=item.client_id,
                    frame=item.frame,
                )
            finally:
                queue.task_done()
