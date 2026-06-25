from fastapi.testclient import TestClient

from buddy_brain.app import create_app
from buddy_brain.repository import BuddyRepository
from tests.conftest import FakeChatProvider


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
    assert "data:" in body
    assert "[DONE]" in body
    episodes = test_repository.recent_episodes("demo-mia", limit=5)
    assert episodes[0].assistant_text == "Sure! Dinosaurs are big."
