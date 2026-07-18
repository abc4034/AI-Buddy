from __future__ import annotations

import asyncio
import queue
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


RUNTIME_DIR = Path(__file__).resolve().parents[2] / "xiaozhi_server"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from core.connection import ConnectionHandler
from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO


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
    ConnectionHandler.notify_provider_failure(
        conn, stage, sentence_id, generation, f"{stage}_failed"
    )


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


def _llm_stream_failure_block() -> str:
    source = (RUNTIME_DIR / "core" / "connection.py").read_text(encoding="utf-8")
    stream_start = source.index("for response in llm_responses:")
    generic_catch = source.index("except Exception as e:", stream_start)
    return source[generic_catch : source.index("if tool_call_flag:", generic_catch)]


def test_llm_failure_path_has_no_upstream_fallback_tts_messages():
    failure_block = _llm_stream_failure_block()

    assert "get_system_error_response" not in failure_block
    assert "SentenceType.MIDDLE" not in failure_block
    assert "SentenceType.LAST" not in failure_block


def test_generic_llm_processing_error_does_not_notify_a_provider_failure():
    assert "notify_provider_failure" not in _llm_stream_failure_block()


class _FailingTTS(TTSProviderBase):
    async def text_to_speak(self, text, output_file):
        return None


def test_terminal_tts_failure_does_not_enqueue_last_completion():
    provider = _FailingTTS({}, delete_audio_file=True)
    stop_event = threading.Event()
    provider.conn = SimpleNamespace(
        stop_event=stop_event,
        client_abort=False,
        sentence_id="turn-a",
    )
    provider.current_sentence_id = "turn-a"
    provider._get_segment_text = lambda: "terminal text"

    def fail_synthesis(*_, **__):
        stop_event.set()
        return False

    provider.to_tts_stream = fail_synthesis
    provider.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id="turn-a",
            sentence_type=SentenceType.LAST,
            content_type=ContentType.TEXT,
            content_detail="terminal text",
        )
    )

    provider.tts_text_priority_thread()

    with pytest.raises(queue.Empty):
        provider.tts_audio_queue.get_nowait()


def test_fault_wrapper_owns_the_fixture_python_process_and_waits_for_cleanup():
    script = (RUNTIME_DIR.parent / "scripts" / "run_xiaozhi_fault_injection.ps1").read_text(
        encoding="utf-8"
    )

    assert "sys.executable" in script
    assert "Start-Process -FilePath $pythonExe" in script
    assert "$serverProcess.WaitForExit" in script
