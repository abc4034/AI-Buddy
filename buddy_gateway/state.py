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
    last_audio_at: int | None = None
    last_message_at: int | None = None
    last_listen_state: str | None = None
    debug_turns: list[dict[str, Any]] = field(default_factory=list)

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

    def record_audio(self, byte_count: int) -> None:
        self.audio_frame_count += 1
        self.audio_byte_count += byte_count
        self.last_audio_at = epoch_seconds()

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
            "last_audio_at": self.last_audio_at,
            "last_message_at": self.last_message_at,
            "last_listen_state": self.last_listen_state,
            "debug_turns": list(self.debug_turns),
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

    def record_audio_frame(self, session_id: str, byte_count: int) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.record_audio(byte_count)

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
