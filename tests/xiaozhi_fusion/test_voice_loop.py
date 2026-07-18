from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from urllib.parse import quote
from urllib.request import urlopen

import opuslib_next
import pytest
import websockets


RUN_LIVE = os.environ.get("RUN_XIAOZHI_VOICE_LOOP") == "1"


def encode_silence_frame() -> bytes:
    encoder = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO)
    return encoder.encode(b"\0" * (960 * 2), 960)


async def run_voice_loop(device_id: str) -> list[object]:
    uri = "ws://127.0.0.1:8000/xiaozhi/v1/"
    headers = {"device-id": device_id, "client-id": f"voice-loop-{device_id}"}
    received: list[object] = []
    async with websockets.connect(uri, additional_headers=headers, open_timeout=10) as socket:
        await socket.send(json.dumps({"type": "hello", "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1}}))
        await asyncio.wait_for(socket.recv(), timeout=15)
        await asyncio.sleep(2)
        await socket.send(json.dumps({"type": "listen", "state": "start", "mode": "manual"}))
        frame = encode_silence_frame()
        for _ in range(6):
            await socket.send(frame)
        await socket.send(json.dumps({"type": "listen", "state": "stop", "mode": "manual"}))

        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            message = await asyncio.wait_for(socket.recv(), timeout=5)
            received.append(message)
            if isinstance(message, str):
                payload = json.loads(message)
                if payload.get("type") == "tts" and payload.get("state") == "stop":
                    break
    return received


def message_events(messages: list[object]) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    for message in messages:
        if isinstance(message, bytes):
            events.append(("binary", "opus"))
            continue
        payload = json.loads(message)
        events.append((str(payload.get("type")), str(payload.get("state", ""))))
    return events


@pytest.mark.live_provider
@pytest.mark.skipif(not RUN_LIVE, reason="set RUN_XIAOZHI_VOICE_LOOP=1 after starting the fused runtime")
def test_software_voice_loop_returns_native_tts_and_persists_one_buddy_episode():
    device_id = f"software-voice-loop-{uuid.uuid4().hex}"
    messages = asyncio.run(run_voice_loop(device_id))
    events = message_events(messages)

    first_tts_start = next(index for index, event in enumerate(events) if event == ("tts", "start"))
    sentence_start = next(index for index, event in enumerate(events) if event == ("tts", "sentence_start"))
    first_binary = next(index for index, event in enumerate(events) if event == ("binary", "opus"))
    tts_stop = next(index for index, event in enumerate(events) if event == ("tts", "stop"))
    assert first_tts_start < sentence_start < first_binary < tts_stop
    assert sum(event == ("binary", "opus") for event in events) > 0

    with urlopen(f"http://127.0.0.1:8010/memory?device_id={quote(device_id, safe='')}", timeout=10) as response:
        dashboard = response.read().decode("utf-8")
    assert device_id in dashboard
    assert dashboard.count("<tr>") == 2
