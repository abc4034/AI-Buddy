from collections.abc import AsyncIterator

import pytest

from buddy_brain.config import Settings
from buddy_brain.repository import BuddyRepository


class FakeChatProvider:
    async def complete(self, messages, model=None, temperature=None):
        if messages[0]["content"].startswith("Extract only stable"):
            return '{"interests_add":["dinosaurs"],"learning_goals_add":[],"notes_add":["likes dinosaurs"],"english_level":null}'
        return "Sure! Dinosaurs are big animals. 恐龙是很大的动物。"

    async def stream(self, messages, model=None, temperature=None) -> AsyncIterator[str]:
        for chunk in ["Sure! ", "Dinosaurs ", "are big."]:
            yield chunk


@pytest.fixture
def test_settings(tmp_path):
    return Settings(
        database_path=tmp_path / "buddy_memory.db",
        openai_api_key="test-key",
    )


@pytest.fixture
def test_repository(test_settings):
    repo = BuddyRepository(test_settings.database_path)
    repo.init_schema()
    repo.ensure_demo_user()
    return repo
