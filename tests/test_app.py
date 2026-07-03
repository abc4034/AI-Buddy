import json

from fastapi.testclient import TestClient

from buddy_brain.app import create_app
from buddy_brain.models import MemoryPatch
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


def test_memory_dashboard_renders_profile_episodes_and_events(test_settings, test_repository):
    profile = test_repository.ensure_demo_user()
    episode = test_repository.add_episode(
        user_id=profile.user_id,
        session_id="session-1",
        user_text="I like cats",
        assistant_text="Cats are cute!",
        detected_language="en",
    )
    test_repository.apply_memory_patch(
        user_id=profile.user_id,
        episode_id=episode.episode_id,
        patch=MemoryPatch(interests_add=["cats"], notes_add=["likes cats"]),
    )
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FakeChatProvider(),
    )
    client = TestClient(app)

    response = client.get("/memory")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Memory Dashboard" in response.text
    assert "Mia" in response.text
    assert "I like cats" in response.text
    assert "likes cats" in response.text


def test_memory_dashboard_reset_clears_demo_memory(test_settings, test_repository):
    profile = test_repository.ensure_demo_user()
    episode = test_repository.add_episode(
        user_id=profile.user_id,
        session_id="session-1",
        user_text="I like cats",
        assistant_text="Cats are cute!",
        detected_language="en",
    )
    test_repository.apply_memory_patch(
        user_id=profile.user_id,
        episode_id=episode.episode_id,
        patch=MemoryPatch(interests_add=["cats"]),
    )
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FakeChatProvider(),
    )
    client = TestClient(app)

    response = client.post("/memory/reset", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/memory"
    assert test_repository.recent_episodes(profile.user_id, limit=5) == []
    assert "cats" not in test_repository.get_profile(profile.user_id).interests


def test_memory_dashboard_reset_clears_selected_device_only(test_settings, test_repository):
    profile_a = test_repository.ensure_profile_for_device("esp32-child-a")
    profile_b = test_repository.ensure_profile_for_device("esp32-child-b")
    episode_a = test_repository.add_episode(
        user_id=profile_a.user_id,
        session_id="session-a",
        user_text="I like cats",
        assistant_text="Cats are cute!",
        detected_language="en",
    )
    episode_b = test_repository.add_episode(
        user_id=profile_b.user_id,
        session_id="session-b",
        user_text="I like trains",
        assistant_text="Trains are fast!",
        detected_language="en",
    )
    test_repository.apply_memory_patch(
        user_id=profile_a.user_id,
        episode_id=episode_a.episode_id,
        patch=MemoryPatch(interests_add=["cats"]),
    )
    test_repository.apply_memory_patch(
        user_id=profile_b.user_id,
        episode_id=episode_b.episode_id,
        patch=MemoryPatch(interests_add=["trains"]),
    )
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FakeChatProvider(),
    )
    client = TestClient(app)

    response = client.post("/memory/reset?device_id=esp32-child-a", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/memory?device_id=esp32-child-a"
    assert test_repository.recent_episodes(profile_a.user_id, limit=5) == []
    assert "cats" not in test_repository.get_profile(profile_a.user_id).interests
    assert test_repository.recent_episodes(profile_b.user_id, limit=5)[0].user_text == "I like trains"
    assert "trains" in test_repository.get_profile(profile_b.user_id).interests


def test_memory_dashboard_can_show_selected_device(test_settings, test_repository):
    profile_a = test_repository.ensure_profile_for_device("esp32-child-a")
    profile_b = test_repository.ensure_profile_for_device("esp32-child-b")
    test_repository.add_episode(
        user_id=profile_a.user_id,
        session_id="session-a",
        user_text="I like cats",
        assistant_text="Cats are cute!",
        detected_language="en",
    )
    test_repository.add_episode(
        user_id=profile_b.user_id,
        session_id="session-b",
        user_text="I like trains",
        assistant_text="Trains are fast!",
        detected_language="en",
    )
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FakeChatProvider(),
    )
    client = TestClient(app)

    response = client.get("/memory?device_id=esp32-child-b")

    assert response.status_code == 200
    assert "esp32-child-a" in response.text
    assert "esp32-child-b" in response.text
    assert "I like trains" in response.text
    assert "I like cats" not in response.text


def test_memory_dashboard_url_encodes_device_links_and_reset_redirect(test_settings, test_repository):
    device_id = "fc:01:2c:cf:17:54"
    test_repository.ensure_profile_for_device(device_id)
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FakeChatProvider(),
    )
    client = TestClient(app)

    response = client.get("/memory")
    reset_response = client.post(f"/memory/reset?device_id={device_id}", follow_redirects=False)

    assert response.status_code == 200
    assert "device_id=fc%3A01%3A2c%3Acf%3A17%3A54" in response.text
    assert reset_response.headers["location"] == "/memory?device_id=fc%3A01%3A2c%3Acf%3A17%3A54"


def test_memory_dashboard_shows_device_identity_details(test_settings, test_repository):
    profile = test_repository.ensure_profile_for_device("esp32-child-a", client_id="client-a")
    episode = test_repository.add_episode(
        user_id=profile.user_id,
        session_id="session-a",
        user_text="I like cats",
        assistant_text="Cats are cute!",
        detected_language="en",
    )
    test_repository.apply_memory_patch(
        user_id=profile.user_id,
        episode_id=episode.episode_id,
        patch=MemoryPatch(interests_add=["cats"]),
    )
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FakeChatProvider(),
    )
    client = TestClient(app)

    response = client.get("/memory?device_id=esp32-child-a")

    assert response.status_code == 200
    assert "client-a" in response.text
    assert "device-esp32-child-a" in response.text
    assert "Last Memory Update" in response.text
    assert '<div class="label">Last Memory Update</div>None yet' not in response.text


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


def test_chat_completion_sanitizes_tts_reply_before_return_and_memory(test_settings, test_repository):
    class MarkdownProvider(FakeChatProvider):
        async def complete(self, messages, model=None, temperature=None):
            if messages[0]["content"].startswith("Extract only stable"):
                return '{"interests_add":[],"learning_goals_add":[],"notes_add":[],"english_level":null}'
            return 'Wow! 🦖 Say: **Dinosaurs are cool.**\n- Try `I can draw.`'

    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=MarkdownProvider(),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "I like dinosaurs"}]},
    )

    assert response.status_code == 200
    assistant_text = response.json()["choices"][0]["message"]["content"]
    assert assistant_text == "Wow! Say: Dinosaurs are cool. Try I can draw."
    episodes = test_repository.recent_episodes("demo-mia", limit=5)
    assert episodes[0].assistant_text == assistant_text


def test_chat_completion_uses_metadata_device_id_for_child_identity(test_settings, test_repository):
    app = create_app(
        settings=test_settings,
        repository=test_repository,
        provider=FakeChatProvider(),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "I like reading"}],
            "metadata": {
                "device_id": "esp32-child-a",
                "client_id": "client-a",
                "session_id": "session-child-a",
            },
        },
    )

    assert response.status_code == 200
    repo = BuddyRepository(test_settings.database_path)
    device = repo.get_device("esp32-child-a")
    episodes = repo.recent_episodes(device["user_id"], limit=5)
    assert device["user_id"] == "device-esp32-child-a"
    assert device["client_id"] == "client-a"
    assert episodes[0].session_id == "session-child-a"
    assert episodes[0].user_text == "I like reading"


def test_chat_completion_uses_configured_device_profile_and_persona(test_settings, tmp_path):
    config_path = tmp_path / "devices.yaml"
    config_path.write_text(
        "\n".join(
            [
                "devices:",
                "  esp32-luna:",
                "    child_name: Luna",
                "    age_group: kindergarten",
                "    english_level: starter",
                "    persona: coach",
            ]
        ),
        encoding="utf-8",
    )
    settings = test_settings.model_copy(update={"device_config_path": config_path})

    class CapturingProvider(FakeChatProvider):
        def __init__(self):
            self.calls = []

        async def complete(self, messages, model=None, temperature=None):
            self.calls.append(messages)
            return await super().complete(messages, model=model, temperature=temperature)

    provider = CapturingProvider()
    app = create_app(settings=settings, provider=provider)
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "metadata": {"device_id": "esp32-luna"},
            },
    )

    assert response.status_code == 200
    system_prompt = provider.calls[0][0]["content"]
    assert "Child name: Luna" in system_prompt
    assert "Age group: kindergarten" in system_prompt
    assert "English level: starter" in system_prompt
    assert "focused, coach-like personality" in system_prompt


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
