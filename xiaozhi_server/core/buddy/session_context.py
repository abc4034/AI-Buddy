from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Mapping


@dataclass(frozen=True)
class SessionContext:
    session_id: str
    device_id: str
    client_id: str
    source: str = "xiaozhi_core_fusion"


_contexts: dict[str, SessionContext] = {}
_lock = RLock()


def context_from_headers(session_id: str, headers: Mapping[str, str]) -> SessionContext:
    device_id = str(headers.get("device-id") or "").strip()
    if not device_id:
        raise ValueError("Buddy session context requires a device-id header.")
    client_id = str(headers.get("client-id") or device_id).strip() or device_id
    return SessionContext(session_id=session_id, device_id=device_id, client_id=client_id)


def register_context(context: SessionContext) -> None:
    with _lock:
        _contexts[context.session_id] = context


def get_context(session_id: str) -> SessionContext | None:
    with _lock:
        return _contexts.get(session_id)


def remove_context(session_id: str) -> SessionContext | None:
    with _lock:
        return _contexts.pop(session_id, None)
