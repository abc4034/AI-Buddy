from __future__ import annotations

import wave
from dataclasses import dataclass
from io import BytesIO

import opuslib_next


@dataclass(frozen=True)
class DecodedWav:
    wav_bytes: bytes
    decoded_frame_count: int
    decode_error_count: int
    duration_ms: int
    sample_rate: int
    channels: int


def decode_opus_frames_to_wav(
    opus_frames: list[bytes],
    *,
    sample_rate: int = 16000,
    channels: int = 1,
    frame_duration_ms: int = 60,
) -> DecodedWav:
    decoder = opuslib_next.Decoder(sample_rate, channels)
    frame_size = int(sample_rate * frame_duration_ms / 1000)
    pcm_frames: list[bytes] = []
    error_count = 0

    try:
        for opus_frame in opus_frames:
            try:
                pcm_frames.append(decoder.decode(opus_frame, frame_size))
            except opuslib_next.OpusError:
                error_count += 1
    finally:
        del decoder

    if not pcm_frames:
        raise ValueError("no valid opus frames decoded")

    pcm_bytes = b"".join(pcm_frames)
    wav_buffer = BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)

    return DecodedWav(
        wav_bytes=wav_buffer.getvalue(),
        decoded_frame_count=len(pcm_frames),
        decode_error_count=error_count,
        duration_ms=len(pcm_frames) * frame_duration_ms,
        sample_rate=sample_rate,
        channels=channels,
    )
