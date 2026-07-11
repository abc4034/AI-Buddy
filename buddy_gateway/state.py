from __future__ import annotations

import time
import uuid
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


def epoch_seconds() -> int:
    return int(time.time())


def _new_session_id() -> str:
    return f"gateway-{uuid.uuid4().hex}"


def new_asr_turn_id() -> str:
    return f"asr-{uuid.uuid4().hex}"


def new_tts_turn_id() -> str:
    return f"tts-{uuid.uuid4().hex}"


@dataclass
class OtaRecord:
    device_id: str | None
    client_id: str | None
    board: Any
    version: str
    headers: dict[str, str]
    created_at: int = field(default_factory=epoch_seconds)

    def summary(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "client_id": self.client_id,
            "board": self.board,
            "version": self.version,
            "created_at": self.created_at,
        }


@dataclass
class SessionRecord:
    device_id: str | None
    client_id: str | None
    remote_address: str | None
    headers: dict[str, str]
    session_id: str = field(default_factory=_new_session_id)
    connected_at: int = field(default_factory=epoch_seconds)
    disconnected_at: int | None = None
    message_counts: Counter[str] = field(default_factory=Counter)
    message_log: list[dict[str, Any]] = field(default_factory=list)
    audio_frame_count: int = 0
    audio_byte_count: int = 0
    audio_payload_byte_count: int = 0
    audio_parse_modes: Counter[str] = field(default_factory=Counter)
    last_audio_at: int | None = None
    last_audio_timestamp: int | None = None
    last_message_at: int | None = None
    last_listen_state: str | None = None
    debug_turns: list[dict[str, Any]] = field(default_factory=list)
    asr_turns: list[dict[str, Any]] = field(default_factory=list)
    tts_turns: list[dict[str, Any]] = field(default_factory=list)
    vad_events: list[dict[str, Any]] = field(default_factory=list)

    def record_message(self, message_type: str, payload: dict[str, Any] | None = None) -> None:
        now = epoch_seconds()
        self.message_counts[message_type] += 1
        self.last_message_at = now
        if payload and message_type == "listen":
            state = payload.get("state")
            if isinstance(state, str):
                self.last_listen_state = state
        self.message_log.append(
            {
                "type": message_type,
                "created_at": now,
                "payload": payload or {},
            }
        )
        self.message_log = self.message_log[-20:]

    def record_audio(
        self,
        *,
        raw_byte_count: int,
        payload_byte_count: int,
        parse_mode: str,
        timestamp: int | None,
    ) -> None:
        self.audio_frame_count += 1
        self.audio_byte_count += raw_byte_count
        self.audio_payload_byte_count += payload_byte_count
        self.audio_parse_modes[parse_mode] += 1
        self.last_audio_at = epoch_seconds()
        self.last_audio_timestamp = timestamp

    def record_debug_turn(
        self,
        *,
        user_text: str,
        status: str,
        assistant_text: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        turn = {
            "created_at": epoch_seconds(),
            "status": status,
            "user_text": user_text,
            "assistant_text": assistant_text,
            "error": error,
        }
        self.debug_turns.append(turn)
        self.debug_turns = self.debug_turns[-20:]
        return turn

    def record_vad_event(self, event: str, *, error: str | None = None) -> dict[str, Any]:
        item = {
            "event": event,
            "created_at": epoch_seconds(),
            "error": error,
        }
        self.vad_events.append(item)
        self.vad_events = self.vad_events[-20:]
        return dict(item)

    def start_asr_turn(self, *, trigger: str, turn_id: str | None = None) -> dict[str, Any]:
        turn = {
            "turn_id": turn_id or new_asr_turn_id(),
            "trigger": trigger,
            "status": "recording",
            "started_at": epoch_seconds(),
            "completed_at": None,
            "transcript": None,
            "assistant_text": None,
            "asr_provider": None,
            "error": None,
            "sent_stt_to_device": False,
            "audio_frame_count": 0,
        }
        self.asr_turns.append(turn)
        self.asr_turns = self.asr_turns[-20:]
        return turn

    def update_asr_turn(self, turn_id: str, **updates: Any) -> dict[str, Any] | None:
        for turn in self.asr_turns:
            if turn.get("turn_id") == turn_id:
                turn.update(updates)
                if updates.get("status") not in {None, "recording"}:
                    turn["completed_at"] = epoch_seconds()
                return dict(turn)
        return None

    def start_tts_turn(self, *, asr_turn_id: str | None, text: str, turn_id: str | None = None) -> dict[str, Any]:
        turn = {
            "turn_id": turn_id or new_tts_turn_id(),
            "asr_turn_id": asr_turn_id,
            "status": "synthesizing",
            "started_at": epoch_seconds(),
            "completed_at": None,
            "text": text,
            "provider": None,
            "audio_format": None,
            "audio_frame_count": 0,
            "error": None,
        }
        self.tts_turns.append(turn)
        self.tts_turns = self.tts_turns[-20:]
        return turn

    def update_tts_turn(self, turn_id: str, **updates: Any) -> dict[str, Any] | None:
        for turn in self.tts_turns:
            if turn.get("turn_id") == turn_id:
                turn.update(updates)
                if updates.get("status") not in {None, "synthesizing", "sending"}:
                    turn["completed_at"] = epoch_seconds()
                return dict(turn)
        return None

    def disconnect(self) -> None:
        self.disconnected_at = epoch_seconds()

    def summary(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "device_id": self.device_id,
            "client_id": self.client_id,
            "remote_address": self.remote_address,
            "connected_at": self.connected_at,
            "disconnected_at": self.disconnected_at,
            "message_counts": dict(self.message_counts),
            "message_log": list(self.message_log),
            "audio_frame_count": self.audio_frame_count,
            "audio_byte_count": self.audio_byte_count,
            "audio_payload_byte_count": self.audio_payload_byte_count,
            "audio_parse_modes": dict(self.audio_parse_modes),
            "last_audio_at": self.last_audio_at,
            "last_audio_timestamp": self.last_audio_timestamp,
            "last_message_at": self.last_message_at,
            "last_listen_state": self.last_listen_state,
            "debug_turns": list(self.debug_turns),
            "asr_turns": list(self.asr_turns),
            "tts_turns": list(self.tts_turns),
            "vad_events": list(self.vad_events),
        }


class GatewayState:
    def __init__(self, session_history_limit: int = 50) -> None:
        self.session_history_limit = session_history_limit
        self._lock = Lock()
        self._sessions: OrderedDict[str, SessionRecord] = OrderedDict()
        self._ota_records: list[OtaRecord] = []

    def record_ota(
        self,
        *,
        device_id: str | None,
        client_id: str | None,
        board: Any,
        version: str,
        headers: dict[str, str],
    ) -> None:
        with self._lock:
            self._ota_records.append(
                OtaRecord(
                    device_id=device_id,
                    client_id=client_id,
                    board=board,
                    version=version,
                    headers=headers,
                )
            )
            self._ota_records = self._ota_records[-self.session_history_limit :]

    def start_session(
        self,
        *,
        device_id: str | None,
        client_id: str | None,
        remote_address: str | None,
        headers: dict[str, str],
    ) -> SessionRecord:
        with self._lock:
            session = SessionRecord(
                device_id=device_id,
                client_id=client_id,
                remote_address=remote_address,
                headers=headers,
            )
            self._sessions[session.session_id] = session
            self._trim_sessions()
            return session

    def record_text_message(
        self,
        session_id: str,
        message_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.record_message(message_type, payload)

    def record_audio_frame(
        self,
        session_id: str,
        *,
        raw_byte_count: int,
        payload_byte_count: int,
        parse_mode: str,
        timestamp: int | None,
    ) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.record_audio(
                    raw_byte_count=raw_byte_count,
                    payload_byte_count=payload_byte_count,
                    parse_mode=parse_mode,
                    timestamp=timestamp,
                )

    def record_debug_turn(
        self,
        session_id: str,
        *,
        user_text: str,
        status: str,
        assistant_text: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            return session.record_debug_turn(
                user_text=user_text,
                status=status,
                assistant_text=assistant_text,
                error=error,
            )

    def record_vad_event(
        self,
        session_id: str,
        event: str,
        *,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            return session.record_vad_event(event, error=error)

    def start_asr_turn(
        self,
        session_id: str,
        *,
        trigger: str,
        turn_id: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            return session.start_asr_turn(trigger=trigger, turn_id=turn_id)

    def update_asr_turn(self, session_id: str, turn_id: str, **updates: Any) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            return session.update_asr_turn(turn_id, **updates)

    def start_tts_turn(self, session_id: str, *, asr_turn_id: str | None, text: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            return session.start_tts_turn(asr_turn_id=asr_turn_id, text=text)

    def update_tts_turn(self, session_id: str, turn_id: str, **updates: Any) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            return session.update_tts_turn(turn_id, **updates)

    def finish_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            session.disconnect()
            return session.summary()

    def session_summary(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            return session.summary()

    def session_summaries(self) -> list[dict[str, Any]]:
        with self._lock:
            return [session.summary() for session in self._sessions.values()]

    def ota_summaries(self) -> list[dict[str, Any]]:
        with self._lock:
            return [record.summary() for record in self._ota_records]

    def recent_device_count(self) -> int:
        with self._lock:
            devices = {
                record.device_id
                for record in self._ota_records
                if record.device_id
            }
            devices.update(
                session.device_id
                for session in self._sessions.values()
                if session.device_id
            )
            return len(devices)

    def _trim_sessions(self) -> None:
        while len(self._sessions) > self.session_history_limit:
            self._sessions.popitem(last=False)
