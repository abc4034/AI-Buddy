from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class OpenAIMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[OpenAIMessage]
    stream: bool = False
    user: str | None = None
    temperature: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Profile(BaseModel):
    user_id: str
    name: str
    age_group: str
    english_level: str
    interests: list[str]
    language_preference: str
    learning_goals: list[str]
    notes: list[str] = Field(default_factory=list)


class Episode(BaseModel):
    episode_id: str
    session_id: str
    user_id: str
    user_text: str
    assistant_text: str
    detected_language: str
    created_at: int


class MemoryPatch(BaseModel):
    interests_add: list[str] = Field(default_factory=list)
    learning_goals_add: list[str] = Field(default_factory=list)
    notes_add: list[str] = Field(default_factory=list)
    english_level: str | None = None
