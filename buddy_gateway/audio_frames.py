from __future__ import annotations

from dataclasses import dataclass


XIAOZHI_HEADER_SIZE = 16
XIAOZHI_AUDIO_PACKET_TYPE = 1


@dataclass(frozen=True)
class ParsedAudioFrame:
    payload: bytes
    raw_size: int
    timestamp: int | None
    sequence: int | None
    mode: str


def parse_audio_frame(packet: bytes) -> ParsedAudioFrame:
    if _looks_like_xiaozhi_header_packet(packet):
        return ParsedAudioFrame(
            payload=packet[XIAOZHI_HEADER_SIZE:],
            raw_size=len(packet),
            timestamp=int.from_bytes(packet[8:12], "big"),
            sequence=int.from_bytes(packet[4:8], "big"),
            mode="xiaozhi_header",
        )

    return ParsedAudioFrame(
        payload=packet,
        raw_size=len(packet),
        timestamp=None,
        sequence=None,
        mode="raw_opus",
    )


def xiaozhi_header_packet(payload: bytes, *, timestamp: int, sequence: int = 0) -> bytes:
    header = bytearray(XIAOZHI_HEADER_SIZE)
    header[0] = XIAOZHI_AUDIO_PACKET_TYPE
    header[2:4] = len(payload).to_bytes(2, "big")
    header[4:8] = sequence.to_bytes(4, "big")
    header[8:12] = timestamp.to_bytes(4, "big")
    header[12:16] = len(payload).to_bytes(4, "big")
    return bytes(header) + payload


def _looks_like_xiaozhi_header_packet(packet: bytes) -> bool:
    if len(packet) < XIAOZHI_HEADER_SIZE:
        return False
    if packet[0] != XIAOZHI_AUDIO_PACKET_TYPE:
        return False
    short_length = int.from_bytes(packet[2:4], "big")
    long_length = int.from_bytes(packet[12:16], "big")
    payload_length = len(packet) - XIAOZHI_HEADER_SIZE
    return short_length == long_length == payload_length


class TimestampAudioBuffer:
    def __init__(self, max_size: int = 20) -> None:
        self.max_size = max_size
        self._buffer: dict[tuple[int, int, int], ParsedAudioFrame] = {}
        self._last_processed_timestamp = 0
        self._arrival_index = 0

    @property
    def buffered_count(self) -> int:
        return len(self._buffer)

    def push(self, frame: ParsedAudioFrame) -> list[ParsedAudioFrame]:
        if frame.timestamp is None:
            return [frame]

        if frame.timestamp >= self._last_processed_timestamp:
            emitted = [frame]
            self._last_processed_timestamp = frame.timestamp
            emitted.extend(self._flush_newer_buffered_frames())
            return emitted

        if len(self._buffer) < self.max_size:
            self._buffer[self._buffer_key(frame)] = frame
            return []

        return [frame]

    def flush(self) -> list[ParsedAudioFrame]:
        emitted = [self._buffer[key] for key in sorted(self._buffer)]
        self._buffer.clear()
        return emitted

    def _flush_newer_buffered_frames(self) -> list[ParsedAudioFrame]:
        emitted: list[ParsedAudioFrame] = []
        processed_any = True
        while processed_any:
            processed_any = False
            for key in sorted(self._buffer):
                timestamp = key[0]
                if timestamp > self._last_processed_timestamp:
                    buffered_frame = self._buffer.pop(key)
                    emitted.append(buffered_frame)
                    self._last_processed_timestamp = timestamp
                    processed_any = True
                    break
        return emitted

    def _buffer_key(self, frame: ParsedAudioFrame) -> tuple[int, int, int]:
        self._arrival_index += 1
        sequence = frame.sequence if isinstance(frame.sequence, int) else self._arrival_index
        return (frame.timestamp or 0, sequence, self._arrival_index)
