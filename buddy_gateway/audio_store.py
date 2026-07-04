from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from pathlib import Path
from threading import RLock
from time import time_ns
from typing import Any

from buddy_gateway.audio_frames import ParsedAudioFrame
from buddy_gateway.opus_codec import decode_opus_frames_to_wav
from buddy_gateway.state import epoch_seconds


class AudioArtifactStore:
    def __init__(self, *, base_dir: str | Path = "data/gateway_audio", session_limit: int = 20) -> None:
        self.base_dir = Path(base_dir)
        self.session_limit = session_limit
        self._lock = RLock()

    def record_frame(
        self,
        *,
        session_id: str,
        device_id: str | None,
        client_id: str | None,
        frame: ParsedAudioFrame,
    ) -> dict[str, Any]:
        with self._lock:
            session_dir = self._session_dir(session_id)
            session_dir.mkdir(parents=True, exist_ok=True)
            now = epoch_seconds()
            now_ns = time_ns()
            metadata = self._load_metadata(session_id)
            is_new_session = metadata is None
            if metadata is None:
                metadata = self._new_metadata(session_id, device_id, client_id, now=now, now_ns=now_ns)
            frame_index = len(metadata["frames"]) + 1
            frame_name = f"frame-{frame_index:05d}.opus"
            frame_path = session_dir / frame_name
            frame_path.write_bytes(frame.payload)

            metadata["device_id"] = device_id
            metadata["client_id"] = client_id
            metadata["updated_at"] = now
            metadata["updated_at_ns"] = now_ns
            metadata["frames"].append(
                {
                    "index": frame_index,
                    "path": frame_name,
                    "payload_bytes": len(frame.payload),
                    "raw_size": frame.raw_size,
                    "timestamp": frame.timestamp,
                    "sequence": frame.sequence,
                    "mode": frame.mode,
                    "created_at": now,
                }
            )
            self._write_metadata(session_id, metadata)
            if is_new_session:
                self._trim_sessions()
            return self._summary_from_metadata(metadata)

    def audio_session_summaries(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.base_dir.exists():
                return []
            summaries = []
            for metadata_path in self.base_dir.glob("*/metadata.json"):
                try:
                    summaries.append(self._summary_from_metadata(json.loads(metadata_path.read_text(encoding="utf-8"))))
                except (OSError, json.JSONDecodeError, TypeError):
                    continue
            return sorted(summaries, key=lambda item: (item.get("updated_at") or 0, item.get("session_id") or ""))

    def decode_session(
        self,
        session_id: str,
        *,
        sample_rate: int = 16000,
        channels: int = 1,
        frame_duration_ms: int = 60,
    ) -> dict[str, Any]:
        with self._lock:
            metadata = self._load_metadata(session_id)
            if metadata is None:
                raise FileNotFoundError(f"audio session not found: {session_id}")
            frames = metadata.get("frames", [])
            if not frames:
                raise ValueError("session has no opus frames")

            ordered_frames = _ordered_frames_for_decode(frames)
            opus_frames = [(self._session_dir(session_id) / frame["path"]).read_bytes() for frame in ordered_frames]
            decoded = decode_opus_frames_to_wav(
                opus_frames,
                sample_rate=sample_rate,
                channels=channels,
                frame_duration_ms=frame_duration_ms,
            )
            wav_path = self._session_dir(session_id) / "audio.wav"
            wav_path.write_bytes(decoded.wav_bytes)

            metadata["wav_path"] = str(wav_path)
            metadata["decoded_at"] = epoch_seconds()
            metadata["decoded_frame_count"] = decoded.decoded_frame_count
            metadata["decode_error_count"] = decoded.decode_error_count
            metadata["duration_ms"] = decoded.duration_ms
            metadata["decode_sample_rate"] = decoded.sample_rate
            metadata["decode_channels"] = decoded.channels
            self._write_metadata(session_id, metadata)

            summary = self._summary_from_metadata(metadata)
            return {"status": "ok", **summary}

    def wav_path_for_session(self, session_id: str) -> Path | None:
        with self._lock:
            metadata = self._load_metadata(session_id)
            if not metadata:
                return None
            wav_path = metadata.get("wav_path")
            if not isinstance(wav_path, str):
                return None
            path = Path(wav_path)
            if not path.exists():
                return None
            return path

    def _new_metadata(
        self,
        session_id: str,
        device_id: str | None,
        client_id: str | None,
        *,
        now: int,
        now_ns: int,
    ) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "device_id": device_id,
            "client_id": client_id,
            "created_at": now,
            "updated_at": now,
            "created_at_ns": now_ns,
            "updated_at_ns": now_ns,
            "frames": [],
        }

    def _load_metadata(self, session_id: str) -> dict[str, Any] | None:
        metadata_path = self._session_dir(session_id) / "metadata.json"
        if not metadata_path.exists():
            return None
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    def _write_metadata(self, session_id: str, metadata: dict[str, Any]) -> None:
        metadata_path = self._session_dir(session_id) / "metadata.json"
        temp_path = metadata_path.with_name(f"{metadata_path.name}.tmp")
        temp_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(metadata_path)

    def _summary_from_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        frames = metadata.get("frames", [])
        parse_modes = Counter(
            frame["mode"]
            for frame in frames
            if isinstance(frame, dict) and isinstance(frame.get("mode"), str)
        )
        opus_byte_count = sum(int(frame.get("payload_bytes") or 0) for frame in frames if isinstance(frame, dict))
        summary = {
            "session_id": metadata.get("session_id"),
            "device_id": metadata.get("device_id"),
            "client_id": metadata.get("client_id"),
            "created_at": metadata.get("created_at"),
            "updated_at": metadata.get("updated_at"),
            "created_at_ns": metadata.get("created_at_ns"),
            "updated_at_ns": metadata.get("updated_at_ns"),
            "opus_frame_count": len(frames),
            "opus_byte_count": opus_byte_count,
            "audio_parse_modes": dict(parse_modes),
            "last_audio_at": frames[-1].get("created_at") if frames else None,
            "wav_path": metadata.get("wav_path"),
            "decoded_at": metadata.get("decoded_at"),
            "decoded_frame_count": metadata.get("decoded_frame_count"),
            "decode_error_count": metadata.get("decode_error_count"),
            "duration_ms": metadata.get("duration_ms"),
        }
        return summary

    def _trim_sessions(self) -> None:
        if self.session_limit <= 0 or not self.base_dir.exists():
            return
        metadata_paths = list(self.base_dir.glob("*/metadata.json"))
        rows = []
        for metadata_path in metadata_paths:
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                updated_at = _metadata_sort_key(metadata)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                updated_at = (0, 0, 0)
            rows.append((updated_at, metadata_path.parent))
        rows.sort(key=lambda item: (item[0], str(item[1])))
        for _, session_dir in rows[:-self.session_limit]:
            shutil.rmtree(session_dir, ignore_errors=True)

    def _session_dir(self, session_id: str) -> Path:
        return self.base_dir / _safe_session_dir_name(session_id)


def _safe_session_dir_name(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id).strip("._")
    return safe or "session"


def _metadata_sort_key(metadata: dict[str, Any]) -> tuple[int, int, int]:
    updated_at_ns = metadata.get("updated_at_ns")
    created_at_ns = metadata.get("created_at_ns")
    updated_at = metadata.get("updated_at")
    if isinstance(updated_at_ns, int):
        primary = updated_at_ns
    elif isinstance(updated_at, int):
        primary = updated_at * 1_000_000_000
    else:
        primary = 0
    secondary = created_at_ns if isinstance(created_at_ns, int) else primary
    frame_count = len(metadata.get("frames", [])) if isinstance(metadata.get("frames"), list) else 0
    return (primary, secondary, frame_count)


def _ordered_frames_for_decode(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not all(isinstance(frame, dict) for frame in frames):
        return frames
    if not frames or not all(isinstance(frame.get("timestamp"), int) for frame in frames):
        return frames
    return sorted(
        frames,
        key=lambda frame: (
            frame["timestamp"],
            frame.get("sequence") if isinstance(frame.get("sequence"), int) else frame.get("index", 0),
            frame.get("index", 0),
        ),
    )
