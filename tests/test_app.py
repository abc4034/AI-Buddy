import json

from fastapi.testclient import TestClient

from buddy_brain.app import create_app
from buddy_brain.repository import BuddyRepository
from tests.conftest import (
    FailingCompleteProvider,
    FailingMemoryService,
    FailingStreamProvider,
    FakeChatProvider,
)


def _sse_payloads(body):
    payloads = []
    for block in body.split("\n\n"):
        if not block.startswith("data: "):
            continue
        raw = block.removeprefix("data: ")
        if raw != "[DONE]":
            payloads.append(json.loads(raw))
    return payloads


def test_health_endpoint(test_settings, test_repository):
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FakeChatProvider(),
    )
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["model"] == "deepseek-v4-flash"


def test_chat_completion_writes_episode_and_memory(test_settings, test_repository):
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FakeChatProvider(),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "我喜欢恐龙，dinosaur 怎么说？"}],
            "stream": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"]["content"].startswith("Sure!")

    repo = BuddyRepository(test_settings.database_path)
    profile = repo.get_profile("demo-mia")
    episodes = repo.recent_episodes("demo-mia", limit=5)
    assert episodes[0].user_text == "我喜欢恐龙，dinosaur 怎么说？"
    assert "dinosaurs" in profile.interests


def test_chat_completion_stream_returns_sse_and_writes_episode(test_settings, test_repository):
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FakeChatProvider(),
    )
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Tell me about dinosaurs"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert body.rstrip().endswith("data: [DONE]")
    payloads = _sse_payloads(body)
    assert payloads[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert [payload["choices"][0]["delta"].get("content") for payload in payloads[1:4]] == [
        "Sure! ",
        "Dinosaurs ",
        "are big.",
    ]
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"
    episodes = test_repository.recent_episodes("demo-mia", limit=5)
    assert episodes[0].assistant_text == "Sure! Dinosaurs are big."


def test_chat_completion_non_stream_provider_failure_returns_502(test_settings, test_repository):
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FailingCompleteProvider(),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Tell me about dinosaurs"}],
            "stream": False,
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "model provider request failed"


def test_chat_completion_stream_provider_failure_yields_error_and_done(test_settings, test_repository):
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FailingStreamProvider(),
    )
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Tell me about dinosaurs"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert body.rstrip().endswith("data: [DONE]")
    payloads = _sse_payloads(body)
    assert payloads[-1] == {
        "object": "error",
        "error": {"message": "model provider request failed"},
    }


def test_chat_completion_stream_memory_failure_still_finishes(
    monkeypatch,
    test_settings,
    test_repository,
):
    monkeypatch.setattr("buddy_brain.app.MemoryService", FailingMemoryService)
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FakeChatProvider(),
    )
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Tell me about dinosaurs"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert body.rstrip().endswith("data: [DONE]")
    payloads = _sse_payloads(body)
    assert payloads[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"
