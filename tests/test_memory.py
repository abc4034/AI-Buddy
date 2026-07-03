import asyncio

import pytest

from buddy_brain.config import Settings
from buddy_brain.memory import MemoryService, parse_memory_patch
from buddy_brain.repository import BuddyRepository


class FakeMemoryLLM:
    async def complete(self, messages, model=None, temperature=None):
        return '{"interests_add":["space"],"learning_goals_add":[],"notes_add":["likes planets"],"english_level":null}'


class EmptyMemoryLLM:
    async def complete(self, messages, model=None, temperature=None):
        return '{"interests_add":[],"learning_goals_add":[],"notes_add":[],"english_level":null}'


def test_parse_memory_patch_accepts_json_inside_markdown_fence():
    patch = parse_memory_patch(
        '```json\n{"interests_add":["cats"],"notes_add":["likes cats"]}\n```'
    )

    assert patch.interests_add == ["cats"]
    assert patch.notes_add == ["likes cats"]


def test_parse_memory_patch_returns_empty_patch_for_non_json():
    patch = parse_memory_patch("no durable memory")

    assert patch.interests_add == []
    assert patch.notes_add == []


@pytest.mark.parametrize(
    "raw_text",
    [
        "[]",
        '"ok"',
        '{"interests_add":"space"}',
    ],
)
def test_parse_memory_patch_returns_empty_patch_for_malformed_valid_json(raw_text):
    patch = parse_memory_patch(raw_text)

    assert patch == type(patch)()


def test_memory_service_updates_repository_profile(tmp_path):
    repo = BuddyRepository(tmp_path / "memory.db")
    repo.init_schema()
    profile = repo.ensure_demo_user()
    episode = repo.add_episode(
        user_id=profile.user_id,
        session_id="session-1",
        user_text="I like planets.",
        assistant_text="Planets are in space.",
        detected_language="en",
    )
    service = MemoryService(
        settings=Settings(database_path=tmp_path / "memory.db"),
        repository=repo,
        provider=FakeMemoryLLM(),
    )

    updated = asyncio.run(
        service.update_from_episode(
            user_id=profile.user_id,
            episode_id=episode.episode_id,
            user_text=episode.user_text,
            assistant_text=episode.assistant_text,
        )
    )

    assert "space" in updated.interests
    assert "likes planets" in updated.notes


def test_memory_service_adds_reading_interest_from_xiaozhi_json_payload(tmp_path):
    repo = BuddyRepository(tmp_path / "memory.db")
    repo.init_schema()
    profile = repo.ensure_demo_user()
    episode = repo.add_episode(
        user_id=profile.user_id,
        session_id="session-1",
        user_text='{"content":"\\u6211\\u559c\\u6b22\\u8bfb\\u4e66\\u3002","language":"zh","emotion":"\\ud83d\\ude36"}',
        assistant_text='English sentence: "I like books."',
        detected_language="mixed",
    )
    service = MemoryService(
        settings=Settings(database_path=tmp_path / "memory.db"),
        repository=repo,
        provider=EmptyMemoryLLM(),
    )

    updated = asyncio.run(
        service.update_from_episode(
            user_id=profile.user_id,
            episode_id=episode.episode_id,
            user_text=episode.user_text,
            assistant_text=episode.assistant_text,
        )
    )

    assert "reading" in updated.interests
    assert "likes reading" in updated.notes
