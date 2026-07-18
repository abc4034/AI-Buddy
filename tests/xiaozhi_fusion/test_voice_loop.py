from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

import opuslib_next
import pytest
import websockets


RUN_LIVE = os.environ.get("RUN_XIAOZHI_VOICE_LOOP") == "1"


def load_input_frames() -> list[bytes]:
    directory = Path(os.environ["XIAOZHI_VOICE_LOOP_OPUS_DIR"])
    frames = [path.read_bytes() for path in sorted(directory.glob("frame-*.opus"))]
    frames = [frame for frame in frames if frame]
    if not frames:
        raise AssertionError("voice-loop input directory has no nonempty Opus frames")
    return frames


async def run_voice_loop(device_id: str) -> list[object]:
    uri = os.environ.get("XIAOZHI_VOICE_LOOP_WS_URL", "ws://127.0.0.1:8000/xiaozhi/v1/")
    headers = {"device-id": device_id, "client-id": f"voice-loop-{device_id}"}
    received: list[object] = []
    async with websockets.connect(uri, additional_headers=headers, open_timeout=10) as socket:
        await socket.send(json.dumps({"type": "hello", "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}}))
        await asyncio.wait_for(socket.recv(), timeout=15)
        await asyncio.sleep(2)
        await socket.send(json.dumps({"type": "listen", "state": "start", "mode": "manual"}))
        for frame in load_input_frames():
            await socket.send(frame)
            await asyncio.sleep(0.06)
        await socket.send(json.dumps({"type": "listen", "state": "stop", "mode": "manual"}))

        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                message = await asyncio.wait_for(socket.recv(), timeout=5)
            except asyncio.TimeoutError:
                continue
            received.append(message)
            if isinstance(message, str):
                payload = json.loads(message)
                if payload.get("type") == "tts" and payload.get("state") == "stop":
                    break
    return received


def validate_voice_loop_messages(messages: list[object]) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    decoder = opuslib_next.Decoder(16000, 1)
    for message in messages:
        if isinstance(message, bytes):
            assert message, "voice loop returned an empty binary frame"
            assert decoder.decode(message, 960), "voice loop returned an invalid Opus frame"
            events.append(("binary", "opus"))
            continue
        payload = json.loads(message)
        events.append((str(payload.get("type")), str(payload.get("state", ""))))
    first_tts_start = next(index for index, event in enumerate(events) if event == ("tts", "start"))
    sentence_start = next(index for index, event in enumerate(events) if event == ("tts", "sentence_start"))
    first_binary = next(index for index, event in enumerate(events) if event == ("binary", "opus"))
    tts_stop = next(index for index, event in enumerate(events) if event == ("tts", "stop"))
    assert first_tts_start < sentence_start < first_binary < tts_stop
    stt_indexes = [index for index, event in enumerate(events) if event[0] == "stt"]
    assert not stt_indexes or max(stt_indexes) < first_tts_start
    return events


def test_voice_loop_validator_requires_nonempty_decodable_opus_and_stt_order():
    encoder = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO)
    frame = encoder.encode(b"\0" * (960 * 2), 960)
    messages = [
        json.dumps({"type": "stt", "text": "hello"}),
        json.dumps({"type": "tts", "state": "start"}),
        json.dumps({"type": "tts", "state": "sentence_start"}),
        frame,
        json.dumps({"type": "tts", "state": "stop"}),
    ]

    assert validate_voice_loop_messages(messages).count(("binary", "opus")) == 1

    with pytest.raises(AssertionError, match="empty binary"):
        validate_voice_loop_messages([*messages[:3], b"", messages[-1]])

    with pytest.raises(AssertionError):
        validate_voice_loop_messages([*messages[1:3], frame, messages[0], messages[-1]])


@pytest.mark.live_provider
@pytest.mark.skipif(not RUN_LIVE, reason="set RUN_XIAOZHI_VOICE_LOOP=1 after starting the fused runtime")
def test_software_voice_loop_returns_native_tts_and_persists_one_buddy_episode():
    device_id = os.environ.get("XIAOZHI_VOICE_LOOP_DEVICE_ID") or f"software-voice-loop-{uuid.uuid4().hex}"
    messages = asyncio.run(run_voice_loop(device_id))
    validate_voice_loop_messages(messages)

    buddy_base_url = os.environ.get("XIAOZHI_VOICE_LOOP_BUDDY_URL", "http://127.0.0.1:8010")
    with urlopen(f"{buddy_base_url.rstrip('/')}/memory?device_id={quote(device_id, safe='')}", timeout=10) as response:
        dashboard = response.read().decode("utf-8")
    assert device_id in dashboard
    episode_table = dashboard.split("<h2>Recent Episodes</h2>", 1)[1].split("</table>", 1)[0]
    assert episode_table.count("<tr>") == 2
