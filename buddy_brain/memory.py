from __future__ import annotations

import json
import re
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


def deterministic_memory_patch(user_text: str, assistant_text: str) -> MemoryPatch:
    content = _message_content(user_text)
    lowered = content.casefold()
    interests: list[str] = []
    notes: list[str] = []

    if _mentions_reading_preference(content, lowered):
        interests.append("reading")
        notes.append("likes reading")
    if _mentions_dinosaur_preference(content, lowered):
        interests.append("dinosaurs")
        notes.append("likes dinosaurs")

    return MemoryPatch(interests_add=interests, notes_add=notes)


def merge_memory_patches(primary: MemoryPatch, supplement: MemoryPatch) -> MemoryPatch:
    return MemoryPatch(
        interests_add=_merge_unique(primary.interests_add, supplement.interests_add),
        learning_goals_add=_merge_unique(
            primary.learning_goals_add,
            supplement.learning_goals_add,
        ),
        notes_add=_merge_unique(primary.notes_add, supplement.notes_add),
        english_level=primary.english_level or supplement.english_level,
    )


def _message_content(user_text: str) -> str:
    try:
        payload = json.loads(user_text)
    except json.JSONDecodeError:
        return user_text
    if isinstance(payload, Mapping):
        content = payload.get("content")
        if isinstance(content, str):
            return content
    return user_text


def _mentions_reading_preference(content: str, lowered: str) -> bool:
    reading_markers = (
        "\u559c\u6b22\u8bfb\u4e66",
        "\u559c\u6b22\u770b\u4e66",
        "\u7231\u8bfb\u4e66",
        "\u7231\u770b\u4e66",
    )
    if any(marker in content for marker in reading_markers):
        return True
    return bool(
        re.search(
            r"\b(i|we)\s+(really\s+)?(like|love|enjoy)\s+(reading|books?)\b",
            lowered,
        )
    )


def _mentions_dinosaur_preference(content: str, lowered: str) -> bool:
    like_markers = (
        "\u559c\u6b22",
        "\u7231",
    )
    dinosaur_markers = (
        "\u6050\u9f99",
        "dinosaur",
        "dinosaurs",
        "t-rex",
    )
    if any(marker in content for marker in like_markers) and any(
        marker in lowered or marker in content for marker in dinosaur_markers
    ):
        return True
    return bool(
        re.search(
            r"\b(i|we)\s+(really\s+)?(like|love|enjoy)\s+(dinosaurs?|t-?rex)\b",
            lowered,
        )
    )


def _merge_unique(existing: list[str], incoming: list[str]) -> list[str]:
    values = list(existing)
    seen = {value.casefold() for value in values}
    for value in incoming:
        clean = value.strip()
        if clean and clean.casefold() not in seen:
            values.append(clean)
            seen.add(clean.casefold())
    return values


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
        patch = merge_memory_patches(
            parse_memory_patch(raw),
            deterministic_memory_patch(user_text, assistant_text),
        )
        return self.repository.apply_memory_patch(user_id, episode_id, patch)
