from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import ValidationError
from buddy_brain.config import Settings
from buddy_brain.llm import LLMProvider
from buddy_brain.models import MemoryPatch, Profile
from buddy_brain.repository import BuddyRepository


def parse_memory_patch(raw_text: str) -> MemoryPatch:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(
            line for line in lines[1:] if line.strip() != "```"
        ).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return MemoryPatch()
    if not isinstance(payload, Mapping):
        return MemoryPatch()
    try:
        return MemoryPatch(**payload)
    except ValidationError:
        return MemoryPatch()


class MemoryService:
    def __init__(
        self,
        settings: Settings,
        repository: BuddyRepository,
        provider: LLMProvider,
    ):
        self.settings = settings
        self.repository = repository
        self.provider = provider

    async def update_from_episode(
        self,
        user_id: str,
        episode_id: str,
        user_text: str,
        assistant_text: str,
    ) -> Profile:
        profile = self.repository.get_profile(user_id)
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract only stable, child-safe learning memory from the conversation. "
                    "Return compact JSON with keys interests_add, learning_goals_add, notes_add, english_level. "
                    "Use empty arrays and null when there is no durable update."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Existing profile:\n{profile.model_dump_json()}\n\n"
                    f"Child said: {user_text}\n"
                    f"Buddy answered: {assistant_text}"
                ),
            },
        ]
        raw = await self.provider.complete(
            messages=messages,
            model=self.settings.effective_memory_model,
            temperature=0,
        )
        patch = parse_memory_patch(raw)
        return self.repository.apply_memory_patch(user_id, episode_id, patch)
