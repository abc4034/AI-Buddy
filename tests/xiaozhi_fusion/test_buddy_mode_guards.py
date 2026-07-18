from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parents[2] / "xiaozhi_server"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from core.connection import ConnectionHandler
from core.handle import helloHandle


def test_buddy_mode_skips_unified_tool_handler_but_non_buddy_mode_keeps_it(monkeypatch):
    created = []

    class ToolHandler:
        def __init__(self, connection):
            created.append(connection)

    monkeypatch.setattr("core.connection.UnifiedToolHandler", ToolHandler)

    def handler(buddy_mode):
        instance = object.__new__(ConnectionHandler)
        instance.intent = object()
        instance.config = {
            "buddy_mode": buddy_mode,
            "selected_module": {"Intent": "FunctionIntent"},
            "Intent": {"FunctionIntent": {"type": "function_call"}},
        }
        instance.loop = None
        instance.logger = type("Logger", (), {"bind": lambda self, **_: self, "info": lambda self, *_: None})()
        return instance

    buddy = handler(True)
    buddy._initialize_intent()
    assert not hasattr(buddy, "func_handler")
    assert created == []

    upstream = handler(False)
    upstream._initialize_intent()
    assert upstream.func_handler.__class__ is ToolHandler
    assert created == [upstream]


def test_buddy_mode_skips_device_advertised_mcp_but_non_buddy_mode_starts_it(monkeypatch):
    created = []
    initialized = []

    class MCPClient:
        def __init__(self):
            created.append(True)

    async def initialize(connection):
        initialized.append(connection)

    monkeypatch.setattr(helloHandle, "MCPClient", MCPClient)
    monkeypatch.setattr(helloHandle, "send_mcp_initialize_message", initialize)

    class Connection:
        def __init__(self, buddy_mode):
            self.config = {"buddy_mode": buddy_mode}
            self.logger = type("Logger", (), {"bind": lambda self, **_: self, "debug": lambda self, *_: None})()
            self.welcome_msg = {"audio_params": {}}
            self.websocket = type("Websocket", (), {"send": self.send})()

        async def send(self, _):
            return None

    asyncio.run(helloHandle.handleHelloMessage(Connection(True), {"features": {"mcp": True}}))
    assert created == []

    upstream = Connection(False)
    asyncio.run(helloHandle.handleHelloMessage(upstream, {"features": {"mcp": True}}))
    assert created == [True]
    assert upstream.mcp_client.__class__ is MCPClient


def test_buddy_mode_does_not_send_connection_titles_to_the_manager(monkeypatch):
    requested_titles = []

    async def generate_title(session_id):
        requested_titles.append(session_id)

    real_thread = threading.Thread

    class JoinableThread:
        def __init__(self, target, daemon):
            self.thread = real_thread(target=target, daemon=daemon)

        def start(self):
            self.thread.start()
            self.thread.join()

    async def close(_ws):
        return None

    monkeypatch.setattr("core.connection.generate_and_save_chat_title", generate_title)
    monkeypatch.setattr("core.connection.threading.Thread", JoinableThread)
    handler = object.__new__(ConnectionHandler)
    handler.config = {"buddy_mode": True}
    handler.session_id = "session-a"
    handler.memory = None
    handler.logger = type("Logger", (), {"bind": lambda self, **_: self, "error": lambda self, *_: None})()
    handler.close = close

    asyncio.run(handler._save_and_close(None))

    assert requested_titles == []
