from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import RLock
from typing import Any


_ALLOWED_EVENT_TYPES = {
    "connection_open",
    "connection_close",
    "listen",
    "asr_complete",
    "asr_error",
    "buddy_complete",
    "buddy_error",
    "tts_start",
    "tts_stop",
    "tts_error",
    "abort",
}
_SENSITIVE_KEY_PARTS = (
    "audio",
    "pcm",
    "opus",
    "prompt",
    "key",
    "token",
    "authorization",
    "headers",
    "config",
)


class DiagnosticsRegistry:
    """A bounded, best-effort view of lifecycle events for local debugging."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._active: dict[str, dict[str, Any]] = {}
        self._completed: deque[dict[str, Any]] = deque(maxlen=20)

    def record_event(self, session_id: str, event_type: str, payload: dict) -> None:
        if event_type not in _ALLOWED_EVENT_TYPES or not isinstance(session_id, str) or not session_id:
            return
        safe_payload = _safe_payload(payload)
        if safe_payload is None:
            return
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "payload": safe_payload,
        }
        with self._lock:
            if event_type == "connection_open":
                self._active.pop(session_id, None)
            session = self._active.setdefault(
                session_id,
                {"session_id": session_id, "state": "active", "events": deque(maxlen=20)},
            )
            session["events"].append(event)
            if event_type == "connection_close":
                completed = self._active.pop(session_id)
                completed["state"] = "closed"
                self._completed.append(_copy_summary(completed))

    def session_summaries(self) -> list[dict]:
        with self._lock:
            return [_copy_summary(session) for session in self._active.values()] + list(self._completed)


def _safe_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or _is_sensitive_key(key):
            continue
        if value is None or isinstance(value, (str, int, float, bool)):
            result[key] = value
    return result


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _copy_summary(session: dict[str, Any]) -> dict:
    return {
        "session_id": session["session_id"],
        "state": session["state"],
        "events": [dict(event) for event in session["events"]],
    }


_registry = DiagnosticsRegistry()


def record_event(session_id: str, event_type: str, payload: dict) -> None:
    """Record diagnostics without allowing debug failures into the speech path."""
    try:
        _registry.record_event(session_id, event_type, payload)
    except Exception:
        return


def session_summaries() -> list[dict]:
    try:
        return _registry.session_summaries()
    except Exception:
        return []
