from __future__ import annotations

import sys
import threading
import asyncio
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
from core.connection import ConnectionHandler


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


def connection_handler(session_id: str) -> ConnectionHandler:
    handler = object.__new__(ConnectionHandler)
    handler.session_id = session_id
    handler.config = {"buddy_mode": True}
    handler.websocket = None
    handler.timeout_task = None
    handler.stop_event = threading.Event()
    handler.vad = None
    handler.tts = None
    handler.asr = None
    handler.executor = None
    handler.memory = None
    handler.logger = type(
        "Logger",
        (),
        {
            "bind": lambda self, **_: self,
            "info": lambda self, *_: None,
            "error": lambda self, *_: None,
        },
    )()
    return handler


def test_failed_connection_setup_removes_registered_context():
    handler = connection_handler("session-failed")

    class Request:
        headers = {"device-id": "fc:01", "client-id": "client-a"}

        @property
        def path(self):
            raise RuntimeError("setup failed after identity registration")

    class WebSocket:
        request = Request()
        remote_address = ("127.0.0.1", 12345)
        closed = True

        async def close(self):
            return None

    asyncio.run(handler.handle_connection(WebSocket()))

    assert get_context("session-failed") is None


def test_repeated_close_removes_context_idempotently():
    handler = connection_handler("session-close")
    register_context(SessionContext("session-close", "fc:01", "client-a"))

    asyncio.run(handler.close())
    asyncio.run(handler.close())

    assert get_context("session-close") is None
