from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from buddy_brain.config import Settings, get_settings
from buddy_brain.llm import LLMProvider, OpenAICompatibleProvider
from buddy_brain.memory import MemoryService
from buddy_brain.models import ChatCompletionRequest
from buddy_brain.prompting import build_chat_messages, detect_language
from buddy_brain.repository import BuddyRepository


def create_app(
    settings: Settings | None = None,
    repository: BuddyRepository | None = None,
    provider: LLMProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    repository = repository or BuddyRepository(
        settings.database_path,
        demo_user_id=settings.demo_user_id,
        demo_device_id=settings.demo_device_id,
    )
    provider = provider or OpenAICompatibleProvider(settings)
    memory_service = MemoryService(settings=settings, repository=repository, provider=provider)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        repository.init_schema()
        repository.ensure_demo_user()
        yield

    api = FastAPI(title=settings.app_name, lifespan=lifespan)

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "model": settings.model_name,
            "database": str(settings.database_path),
        }

    @api.post("/v1/chat/completions")
    async def chat_completions(
        request: ChatCompletionRequest,
        background_tasks: BackgroundTasks,
    ) -> Any:
        user_text = _latest_user_text(request)
        profile = repository.ensure_demo_user()
        history = repository.recent_episodes(profile.user_id, settings.recent_episode_limit)
        detected_language = detect_language(user_text)
        messages = build_chat_messages(profile, history, user_text)
        model = request.model or settings.model_name
        session_id = request.metadata.get("session_id") or f"session-{uuid.uuid4().hex}"

        if request.stream:
            return StreamingResponse(
                _stream_response(
                    provider=provider,
                    memory_service=memory_service,
                    repository=repository,
                    user_id=profile.user_id,
                    session_id=session_id,
                    user_text=user_text,
                    detected_language=detected_language,
                    messages=messages,
                    model=model,
                    temperature=request.temperature,
                ),
                media_type="text/event-stream",
            )

        assistant_text = await provider.complete(
            messages=messages,
            model=model,
            temperature=request.temperature,
        )
        episode = repository.add_episode(
            user_id=profile.user_id,
            session_id=session_id,
            user_text=user_text,
            assistant_text=assistant_text,
            detected_language=detected_language,
        )
        background_tasks.add_task(
            memory_service.update_from_episode,
            profile.user_id,
            episode.episode_id,
            user_text,
            assistant_text,
        )
        return _chat_completion_payload(model=model, assistant_text=assistant_text)

    return api


def _latest_user_text(request: ChatCompletionRequest) -> str:
    for message in reversed(request.messages):
        content = message.content.strip()
        if message.role == "user" and content:
            return content
    raise HTTPException(
        status_code=400,
        detail="messages must include a non-empty user message",
    )


def _chat_completion_payload(model: str, assistant_text: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": assistant_text},
                "finish_reason": "stop",
            }
        ],
    }


async def _stream_response(
    provider: LLMProvider,
    memory_service: MemoryService,
    repository: BuddyRepository,
    user_id: str,
    session_id: str,
    user_text: str,
    detected_language: str,
    messages: list[dict[str, str]],
    model: str,
    temperature: float | None,
) -> AsyncIterator[str]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    chunks: list[str] = []

    async for delta in provider.stream(messages=messages, model=model, temperature=temperature):
        chunks.append(delta)
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": delta},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    assistant_text = "".join(chunks)
    episode = repository.add_episode(
        user_id=user_id,
        session_id=session_id,
        user_text=user_text,
        assistant_text=assistant_text,
        detected_language=detected_language,
    )
    await memory_service.update_from_episode(user_id, episode.episode_id, user_text, assistant_text)
    yield "data: [DONE]\n\n"


app = create_app()
