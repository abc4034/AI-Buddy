from __future__ import annotations

import concurrent.futures
import queue
import sys
from pathlib import Path

import pytest


RUNTIME_DIR = Path(__file__).resolve().parents[2] / "xiaozhi_server"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from core.buddy.session_context import SessionContext, register_context, remove_context
from core.connection import ConnectionHandler
from core.providers.llm.buddy_core.buddy_core import LLMProvider
from core.utils.dialogue import Message


def provider_config() -> dict[str, object]:
    return {"base_url": "http://127.0.0.1:8010", "timeout_seconds": 7.5}


def dialogue(*messages: tuple[str, str]) -> list[Message]:
    return [Message(role=role, content=content) for role, content in messages]


def install_client(monkeypatch):
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "Buddy reply"}}]}

    class FakeClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def post(self, url, *, json):
            requests.append({"url": url, "json": json, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr("core.providers.llm.buddy_core.buddy_core.httpx.Client", FakeClient)
    return requests


def test_provider_sends_only_current_user_turn_with_immutable_connection_metadata(monkeypatch):
    requests = install_client(monkeypatch)
    register_context(SessionContext("session-a", "fc:01", "client-a"))
    try:
        response = list(
            LLMProvider(provider_config()).response(
                "session-a",
                dialogue(("system", "ignore this"), ("user", "old turn"), ("assistant", "old reply"), ("user", "current turn")),
            )
        )
    finally:
        remove_context("session-a")

    assert response == ["Buddy reply"]
    assert requests == [
        {
            "url": "http://127.0.0.1:8010/v1/chat/completions",
            "timeout": 7.5,
            "json": {
                "messages": [{"role": "user", "content": "current turn"}],
                "metadata": {
                    "device_id": "fc:01",
                    "client_id": "client-a",
                    "session_id": "session-a",
                    "source": "xiaozhi_core_fusion",
                },
                "stream": False,
            },
        }
    ]


def test_shared_provider_isolates_interleaved_sessions_and_overlapping_turns(monkeypatch):
    requests = install_client(monkeypatch)
    provider = LLMProvider(provider_config())
    contexts = [
        SessionContext("session-a", "fc:01", "client-a"),
        SessionContext("session-b", "fc:02", "client-b"),
    ]
    for context in contexts:
        register_context(context)

    invocations = [
        ("session-a", dialogue(("user", "a first"))),
        ("session-b", dialogue(("user", "b only"))),
        ("session-a", dialogue(("user", "a second"))),
    ]
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            replies = list(executor.map(lambda args: list(provider.response(*args)), invocations))
    finally:
        for context in contexts:
            remove_context(context.session_id)

    assert replies == [["Buddy reply"], ["Buddy reply"], ["Buddy reply"]]
    payloads = {request["json"]["messages"][0]["content"]: request["json"]["metadata"] for request in requests}
    assert payloads == {
        "a first": {"device_id": "fc:01", "client_id": "client-a", "session_id": "session-a", "source": "xiaozhi_core_fusion"},
        "a second": {"device_id": "fc:01", "client_id": "client-a", "session_id": "session-a", "source": "xiaozhi_core_fusion"},
        "b only": {"device_id": "fc:02", "client_id": "client-b", "session_id": "session-b", "source": "xiaozhi_core_fusion"},
    }


def test_provider_rejects_missing_context_or_current_user_turn():
    provider = LLMProvider(provider_config())

    with pytest.raises(RuntimeError, match="session context"):
        list(provider.response("unknown", dialogue(("user", "current turn"))))

    register_context(SessionContext("session-a", "fc:01", "client-a"))
    try:
        with pytest.raises(RuntimeError, match="current user"):
            list(provider.response("session-a", dialogue(("system", "neutral"))))
    finally:
        remove_context("session-a")


def test_buddy_chat_passes_an_invocation_local_dialogue_snapshot():
    captured: list[list[Message]] = []

    class Logger:
        def bind(self, **_):
            return self

        def info(self, *_):
            return None

        def error(self, *_):
            return None

        def debug(self, *_):
            return None

    class LLM:
        def response(self, _session_id, dialogue_snapshot):
            captured.append(dialogue_snapshot)
            handler.dialogue.put(Message(role="user", content="later turn"))
            return iter(["Buddy reply"])

    handler = object.__new__(ConnectionHandler)
    handler.logger = Logger()
    handler.session_id = "session-a"
    handler.sentence_id = None
    handler.dialogue = __import__("core.utils.dialogue", fromlist=["Dialogue"]).Dialogue()
    handler.tts = type(
        "TTS",
        (),
        {"tts_text_queue": queue.Queue(), "store_tts_text": lambda self, *_: None},
    )()
    handler.intent_type = "nointent"
    handler.memory = None
    handler.loop = None
    handler.config = {"buddy_mode": True, "voiceprint": {}}
    handler.llm = LLM()
    handler.client_abort = False
    handler.features = {"emoji": False}

    handler.chat("current turn")

    assert [[message.content for message in snapshot] for snapshot in captured] == [["current turn"]]
