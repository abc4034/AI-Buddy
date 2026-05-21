#!/usr/bin/env python3
"""
OpenAI-compatible TTS API server for faster-qwen3-tts.
Modified to use built-in voices and hardcoded parameters.
"""
import asyncio
import io
import logging
import os
import queue
import struct
import sys
import threading
from typing import AsyncGenerator

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from faster_qwen3_tts import FasterQwen3TTS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level = logging.INFO)
logger = logging.getLogger(__name__)

# MODEL_PATH_OR_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
MODEL_PATH_OR_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
HOST = "0.0.0.0"  # 监听地址
PORT = 8000  # 监听端口
DEVICE = "cuda"  # 运行设备
DTYPE = torch.bfloat16  # 数据精度
DEFAULT_LANGUAGE = "Chinese"

app = FastAPI(title = "faster-qwen3-tts OpenAI-compatible API")

tts_model = None
SAMPLE_RATE = 24000  # 模型加载后会自动更新
_model_lock = threading.Lock()  # 防止 GPU 并发冲突


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SpeechRequest(BaseModel):
    model: str = "tts-1"
    input: str
    voice: str = "alloy"
    response_format: str = "wav"  # wav | pcm | mp3
    speed: float = 1.0


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def _to_pcm16(pcm: np.ndarray) -> bytes:
    """Convert float32 numpy array to raw 16-bit little-endian PCM bytes."""
    return np.clip(pcm * 32768, -32768, 32767).astype(np.int16).tobytes()


def _wav_header(sample_rate: int, data_len: int = 0xFFFFFFFF) -> bytes:
    """Build a WAV header. Use data_len=0xFFFFFFFF for streaming."""
    n_channels = 1
    bits = 16
    byte_rate = sample_rate * n_channels * bits // 8
    block_align = n_channels * bits // 8
    riff_size = 0xFFFFFFFF if data_len == 0xFFFFFFFF else 36 + data_len
    buf = io.BytesIO()
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", riff_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<IHHIIHH", 16, 1, n_channels, sample_rate,
                          byte_rate, block_align, bits))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_len))
    return buf.getvalue()


def _to_mp3_bytes(pcm: np.ndarray, sample_rate: int) -> bytes:
    """Convert float32 numpy array to MP3 bytes (requires pydub + ffmpeg)."""
    try:
        from pydub import AudioSegment
    except ImportError:
        raise HTTPException(
            status_code = 400,
            detail = "response_format='mp3' requires pydub: pip install pydub",
        )
    segment = AudioSegment(
        _to_pcm16(pcm),
        frame_rate = sample_rate,
        sample_width = 2,
        channels = 1,
    )
    buf = io.BytesIO()
    segment.export(buf, format = "mp3")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Streaming helper
# ---------------------------------------------------------------------------

async def _stream_chunks(voice_name: str, text: str) -> AsyncGenerator[bytes, None]:
    """
    后台线程运行流式生成，并 yielded PCM 字节流
    """
    q: queue.Queue = queue.Queue()
    _DONE = object()

    def producer():
        try:
            with _model_lock:
                for chunk, _sr, _timing in tts_model.generate_custom_voice_streaming(
                        text = text,
                        speaker = "Serena",  # 直接传入客户端请求的音色名
                        language = "Chinese",
                        chunk_size = 8,
                        instruct = "体现撒娇稚嫩的萝莉女声，音调偏高且起伏明显，营造出黏人、做作又刻意卖萌的听觉效果。"
                ):
                    q.put(chunk)
        except Exception as exc:
            q.put(exc)
        finally:
            q.put(_DONE)

    thread = threading.Thread(target = producer, daemon = True)
    thread.start()

    loop = asyncio.get_event_loop()
    while True:
        item = await loop.run_in_executor(None, q.get)
        if item is _DONE:
            break
        if isinstance(item, Exception):
            raise item
        yield _to_pcm16(item)


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": tts_model is not None}


@app.post("/v1/audio/speech")
async def create_speech(req: SpeechRequest):
    if tts_model is None:
        raise HTTPException(status_code = 503, detail = "Model not loaded")
    if not req.input.strip():
        raise HTTPException(status_code = 400, detail = "'input' text is empty")

    fmt = req.response_format.lower()
    voice_name = req.voice

    _CONTENT_TYPES = {
        "wav": "audio/wav",
        "pcm": "audio/pcm",
        "mp3": "audio/mpeg",
    }
    if fmt not in _CONTENT_TYPES:
        raise HTTPException(
            status_code = 400,
            detail = f"response_format {fmt!r} not supported. Use: wav, pcm, mp3",
        )
    content_type = _CONTENT_TYPES[fmt]

    if fmt == "mp3":
        loop = asyncio.get_event_loop()

        def _generate():
            with _model_lock:
                return tts_model.generate_custom_voice(
                    text = req.input,
                    speaker = "Serena",
                    language = DEFAULT_LANGUAGE,
                    instruct = "体现撒娇稚嫩的萝莉女声，音调偏高且起伏明显，营造出黏人、做作又刻意卖萌的听觉效果。"
                )

        audio_arrays, sr = await loop.run_in_executor(None, _generate)
        audio = audio_arrays[0] if audio_arrays else np.zeros(1, dtype = np.float32)
        return Response(content = _to_mp3_bytes(audio, sr), media_type = content_type)

    # --- WAV / PCM: 实时流式传输 ---
    async def audio_stream():
        if fmt == "wav":
            yield _wav_header(SAMPLE_RATE)  # 流式头部
        async for raw_chunk in _stream_chunks(voice_name, req.input):
            yield raw_chunk

    return StreamingResponse(audio_stream(), media_type = content_type)


def main():
    global tts_model, SAMPLE_RATE

    logger.info("正在加载模型 %s 设备: %s ...", MODEL_PATH_OR_ID, DEVICE)

    tts_model = FasterQwen3TTS.from_pretrained(
        MODEL_PATH_OR_ID,
        device = DEVICE,
        dtype = DTYPE,
    )
    SAMPLE_RATE = tts_model.sample_rate

    logger.info("模型加载完成! 采样率: %d Hz", SAMPLE_RATE)
    logger.info("OpenAI 兼容服务器正在监听: http://%s:%d", HOST, PORT)

    uvicorn.run(app, host = HOST, port = PORT)


if __name__ == "__main__":
    main()
