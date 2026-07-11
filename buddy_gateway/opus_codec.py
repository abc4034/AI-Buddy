from __future__ import annotations

import audioop
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
    pcm_bytes: bytes = b""


def decode_opus_frame_to_pcm(
    decoder: opuslib_next.Decoder,
    opus_frame: bytes,
    *,
    frame_size: int = 960,
) -> bytes:
    return decoder.decode(opus_frame, frame_size)


def release_opus_decoder(decoder: opuslib_next.Decoder) -> None:
    close = getattr(decoder, "close", None)
    if callable(close):
        close()
        return

    decoder_state = getattr(decoder, "decoder_state", None)
    if decoder_state is not None:
        opuslib_next.api.decoder.destroy(decoder_state)
        del decoder.decoder_state


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
        pcm_bytes=pcm_bytes,
    )


def wav_bytes_to_pcm16_mono(wav_bytes: bytes, *, target_sample_rate: int = 16000) -> bytes:
    with wave.open(BytesIO(wav_bytes), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        source_sample_rate = wav_file.getframerate()
        pcm = wav_file.readframes(wav_file.getnframes())

    if sample_width != 2:
        pcm = audioop.lin2lin(pcm, sample_width, 2)
        sample_width = 2
    if channels > 1:
        pcm = audioop.tomono(pcm, sample_width, 1.0 / channels, 1.0 / channels)
    if source_sample_rate != target_sample_rate:
        pcm, _ = audioop.ratecv(
            pcm,
            sample_width,
            1,
            source_sample_rate,
            target_sample_rate,
            None,
        )
    return pcm


def encode_pcm16_mono_to_opus_frames(
    pcm: bytes,
    *,
    sample_rate: int = 16000,
    frame_duration_ms: int = 60,
) -> list[bytes]:
    frame_size = int(sample_rate * frame_duration_ms / 1000)
    frame_byte_count = frame_size * 2
    encoder = opuslib_next.Encoder(sample_rate, 1, opuslib_next.APPLICATION_AUDIO)
    frames: list[bytes] = []
    try:
        for offset in range(0, len(pcm), frame_byte_count):
            chunk = pcm[offset : offset + frame_byte_count]
            if not chunk:
                continue
            if len(chunk) < frame_byte_count:
                chunk += b"\x00" * (frame_byte_count - len(chunk))
            frames.append(encoder.encode(chunk, frame_size))
    finally:
        del encoder
    return frames
