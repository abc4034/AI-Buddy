from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest


RUNTIME_DIR = Path(__file__).resolve().parents[2] / "xiaozhi_server"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from core.buddy.session_context import (
    SessionContext,
    context_from_headers,
    get_context,
    register_context,
    remove_context,
)


def test_session_context_is_immutable_and_client_id_falls_back_to_device_id():
    context = context_from_headers("session-a", {"device-id": "fc:01"})

    assert context == SessionContext("session-a", "fc:01", "fc:01")
    with pytest.raises(AttributeError):
        context.device_id = "changed"  # type: ignore[misc]


def test_context_registry_registers_and_removes_one_session():
    context = SessionContext("session-a", "fc:01", "client-a")

    register_context(context)
    try:
        assert get_context("session-a") == context
    finally:
        assert remove_context("session-a") == context
    assert get_context("session-a") is None


def test_context_registry_keeps_interleaved_sessions_isolated():
    contexts = [SessionContext(f"session-{index}", f"fc:{index:02}", f"client-{index}") for index in range(20)]
    barrier = threading.Barrier(len(contexts))
    failures: list[Exception] = []

    def register_and_read(context: SessionContext) -> None:
        try:
            register_context(context)
            barrier.wait()
            assert get_context(context.session_id) == context
        except Exception as error:  # pragma: no cover - surfaced below
            failures.append(error)

    threads = [threading.Thread(target=register_and_read, args=(context,)) for context in contexts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert failures == []
    finally:
        for context in contexts:
            remove_context(context.session_id)
