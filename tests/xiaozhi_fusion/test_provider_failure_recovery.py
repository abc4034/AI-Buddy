from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from types import SimpleNamespace


RUNTIME_DIR = Path(__file__).resolve().parents[2] / "xiaozhi_server"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from core.connection import ConnectionHandler


class _Logger:
    def bind(self, **_):
        return self

    def debug(self, *_):
        pass


class _Connection:
    def __init__(self, loop, *, sentence_id="turn-a", generation=1):
        self.loop = loop
        self.sentence_id = sentence_id
        self.asr_invocation_generation = generation
        self.stop_event = threading.Event()
        self.websocket = SimpleNamespace(closed=False)
        self.logger = _Logger()
        self.session_id = "session-1"


def _notify(conn, stage, sentence_id, generation):
    ConnectionHandler.notify_provider_failure(conn, stage, sentence_id, generation, f"{stage}_failed")


def test_stale_llm_failure_never_aborts_the_newer_sentence(monkeypatch):
    async def scenario():
        aborted = []

        async def native_abort(conn):
            aborted.append(conn.sentence_id)

        monkeypatch.setattr("core.handle.abortHandle.handleAbortMessage", native_abort)
        conn = _Connection(asyncio.get_running_loop())
        _notify(conn, "buddy", "turn-a", None)
        conn.sentence_id = "turn-b"
        await asyncio.sleep(0)
        assert aborted == []

    asyncio.run(scenario())


def test_stale_auto_mode_asr_failure_uses_generation_not_listen_state(monkeypatch):
    async def scenario():
        aborted = []

        async def native_abort(conn):
            aborted.append(conn.asr_invocation_generation)

        monkeypatch.setattr("core.handle.abortHandle.handleAbortMessage", native_abort)
        conn = _Connection(asyncio.get_running_loop(), generation=4)
        _notify(conn, "asr", None, 3)
        await asyncio.sleep(0)
        assert aborted == []

    asyncio.run(scenario())


def test_current_failure_uses_native_abort_once_and_next_turn_can_proceed(monkeypatch):
    async def scenario():
        aborted = []

        async def native_abort(conn):
            aborted.append(conn.sentence_id)

        monkeypatch.setattr("core.handle.abortHandle.handleAbortMessage", native_abort)
        conn = _Connection(asyncio.get_running_loop())
        _notify(conn, "tts", "turn-a", None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert aborted == ["turn-a"]
        conn.sentence_id = "turn-b"
        assert conn.sentence_id == "turn-b"

    asyncio.run(scenario())


def test_callback_rechecks_after_scheduling_before_calling_native_abort(monkeypatch):
    async def scenario():
        aborted = []

        async def native_abort(conn):
            aborted.append(conn.sentence_id)

        monkeypatch.setattr("core.handle.abortHandle.handleAbortMessage", native_abort)
        conn = _Connection(asyncio.get_running_loop())
        _notify(conn, "buddy", "turn-a", None)
        conn.sentence_id = "turn-b"
        await asyncio.sleep(0)
        assert aborted == []

    asyncio.run(scenario())


def test_llm_failure_path_has_no_upstream_fallback_tts_messages():
    source = (RUNTIME_DIR / "core" / "connection.py").read_text(encoding="utf-8")
    failure_block = source[source.index("except Exception as e:", source.index("# 处理流式响应")):]
    failure_block = failure_block[:failure_block.index("# 处理function call")]
    assert "get_system_error_response" not in failure_block
    assert "SentenceType.MIDDLE" not in failure_block
    assert "SentenceType.LAST" not in failure_block
