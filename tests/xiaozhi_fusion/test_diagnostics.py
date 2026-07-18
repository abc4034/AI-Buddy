from __future__ import annotations

import sys
from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parents[2] / "xiaozhi_server"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from core.buddy import diagnostics


def test_registry_bounds_sessions_events_and_redacts_sensitive_payloads():
    registry = diagnostics.DiagnosticsRegistry()

    registry.record_event(
        "active",
        "connection_open",
        {
            "audio_frame": b"must-not-be-stored",
            "prompt": "must-not-be-stored",
            "count": 1,
        },
    )
    for index in range(25):
        registry.record_event("active", "listen", {"index": index})

    for index in range(21):
        registry.record_event(f"complete-{index}", "connection_open", {})
        registry.record_event(f"complete-{index}", "connection_close", {})

    summaries = registry.session_summaries()
    active = next(summary for summary in summaries if summary["session_id"] == "active")
    assert len(active["events"]) == 20
    assert active["events"][0]["payload"] == {"index": 5}
    assert all("audio_frame" not in event["payload"] for event in active["events"])
    assert all("prompt" not in event["payload"] for event in active["events"])
    assert len([summary for summary in summaries if summary["state"] == "closed"]) == 20


def test_registry_rejects_unknown_events_and_debug_failures_are_best_effort(monkeypatch):
    registry = diagnostics.DiagnosticsRegistry()
    registry.record_event("session", "not-allowed", {"count": 1})
    assert registry.session_summaries() == []

    monkeypatch.setattr(diagnostics, "_registry", registry)
    monkeypatch.setattr(registry, "record_event", lambda *_: (_ for _ in ()).throw(RuntimeError("debug down")))
    diagnostics.record_event("session", "listen", {"count": 1})


def test_registry_rejects_non_finite_float_payloads():
    registry = diagnostics.DiagnosticsRegistry()

    registry.record_event("session", "listen", {"latency": float("nan"), "count": 1})

    payload = registry.session_summaries()[0]["events"][0]["payload"]
    assert payload == {"count": 1}
