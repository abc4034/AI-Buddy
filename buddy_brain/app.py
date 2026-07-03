from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from html import escape
from typing import Any
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from buddy_brain.config import Settings, get_settings, load_device_profiles
from buddy_brain.llm import LLMProvider, OpenAICompatibleProvider
from buddy_brain.memory import MemoryService
from buddy_brain.models import ChatCompletionRequest
from buddy_brain.prompting import build_chat_messages, detect_language, sanitize_tts_text
from buddy_brain.repository import BuddyRepository


logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    repository: BuddyRepository | None = None,
    provider: LLMProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    device_profiles = load_device_profiles(settings.device_config_path)
    repository = repository or BuddyRepository(
        settings.database_path,
        demo_user_id=settings.demo_user_id,
        demo_device_id=settings.demo_device_id,
        device_profiles=device_profiles,
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

    @api.get("/memory", response_class=HTMLResponse)
    async def memory_dashboard(device_id: str | None = None) -> HTMLResponse:
        repository.ensure_demo_user()
        if device_id:
            profile = repository.ensure_profile_for_device(device_id)
            selected_device_id = device_id
        else:
            devices = repository.list_devices()
            selected_device_id = devices[0]["device_id"] if devices else settings.demo_device_id
            profile = repository.ensure_profile_for_device(selected_device_id)
        episodes = repository.recent_episodes(profile.user_id, limit=50)
        events = repository.memory_events(profile.user_id)[:50]
        devices = repository.list_devices()
        selected_device = _selected_device(devices, selected_device_id)
        return HTMLResponse(
            _memory_dashboard_html(
                profile=profile,
                episodes=episodes,
                events=events,
                devices=devices,
                selected_device_id=selected_device_id,
                selected_device=selected_device,
            )
        )

    @api.post("/memory/reset")
    async def reset_memory_dashboard(device_id: str | None = None) -> RedirectResponse:
        if device_id:
            repository.reset_device_memory(device_id)
            return RedirectResponse(f"/memory?device_id={quote(device_id, safe='')}", status_code=303)
        repository.reset_demo_user()
        return RedirectResponse("/memory", status_code=303)

    @api.post("/v1/chat/completions")
    async def chat_completions(
        request: ChatCompletionRequest,
        background_tasks: BackgroundTasks,
    ) -> Any:
        user_text = _latest_user_text(request)
        device_id = _request_device_id(request, settings)
        client_id = _request_client_id(request)
        profile = repository.ensure_profile_for_device(device_id, client_id=client_id)
        history = repository.recent_episodes(profile.user_id, settings.recent_episode_limit)
        detected_language = detect_language(user_text)
        messages = build_chat_messages(
            profile,
            history,
            user_text,
            persona=repository.device_persona(device_id) or settings.persona,
        )
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

        try:
            assistant_text = await provider.complete(
                messages=messages,
                model=model,
                temperature=request.temperature,
            )
            assistant_text = sanitize_tts_text(assistant_text)
        except Exception as exc:
            logger.exception("Model provider request failed")
            raise HTTPException(
                status_code=502,
                detail="model provider request failed",
            ) from exc
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


def _request_device_id(request: ChatCompletionRequest, settings: Settings) -> str:
    device_id = request.metadata.get("device_id") or request.metadata.get("device-id")
    if isinstance(device_id, str) and device_id.strip():
        return device_id.strip()
    if request.user and request.user.strip():
        return request.user.strip()
    return settings.demo_device_id


def _request_client_id(request: ChatCompletionRequest) -> str | None:
    client_id = request.metadata.get("client_id") or request.metadata.get("client-id")
    if isinstance(client_id, str) and client_id.strip():
        return client_id.strip()
    return None


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


def _chat_completion_chunk_payload(
    completion_id: str,
    model: str,
    delta: dict[str, str],
    finish_reason: str | None,
) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }


def _sse_data(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _memory_dashboard_html(
    profile: Any,
    episodes: list[Any],
    events: list[dict[str, Any]],
    devices: list[dict[str, Any]],
    selected_device_id: str,
    selected_device: dict[str, Any] | None,
) -> str:
    interests = _chips(profile.interests)
    goals = _chips(profile.learning_goals)
    notes = _list_items(profile.notes)
    episode_rows = "\n".join(_episode_row(episode) for episode in episodes)
    event_rows = "\n".join(_event_row(event) for event in events)
    device_links = _device_links(devices, selected_device_id)
    reset_action = f"/memory/reset?device_id={quote(selected_device_id, safe='')}"
    client_id = selected_device.get("client_id") if selected_device else ""
    user_id = selected_device.get("user_id") if selected_device else profile.user_id
    last_memory_update = _format_time(events[0]["created_at"]) if events else "None yet"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Memory Dashboard</title>
  <style>
    body {{ margin: 0; font-family: system-ui, -apple-system, Segoe UI, sans-serif; background: #f6f7f9; color: #1f2937; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
    header {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 20px; }}
    h1 {{ font-size: 28px; margin: 0; }}
    h2 {{ font-size: 18px; margin: 0 0 12px; }}
    section {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 18px; margin-bottom: 16px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-top: 1px solid #e5e7eb; padding: 10px; text-align: left; vertical-align: top; }}
    th {{ color: #4b5563; font-weight: 650; }}
    pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .item {{ background: #f9fafb; border: 1px solid #eef0f3; border-radius: 8px; padding: 12px; }}
    .label {{ color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .chip {{ background: #e8f2ff; border: 1px solid #c9def8; border-radius: 999px; padding: 4px 10px; }}
    .devices {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
    .device {{ color: #1f2937; text-decoration: none; border: 1px solid #d1d5db; border-radius: 999px; padding: 5px 10px; background: #fff; }}
    .device.active {{ border-color: #2563eb; background: #dbeafe; color: #1d4ed8; }}
    .empty {{ color: #6b7280; }}
    button {{ background: #b91c1c; color: #fff; border: 0; border-radius: 6px; padding: 8px 12px; cursor: pointer; }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Memory Dashboard</h1>
        <div class="empty">Local demo database: data/buddy_memory.db</div>
        <div class="devices">{device_links}</div>
      </div>
      <form method="post" action="{reset_action}" onsubmit="return confirm('Reset memory for this device?');">
        <button type="submit">Reset Device Memory</button>
      </form>
    </header>

    <section>
      <h2>Profile</h2>
      <div class="grid">
        <div class="item"><div class="label">Name</div>{escape(profile.name)}</div>
        <div class="item"><div class="label">Device</div>{escape(selected_device_id)}</div>
        <div class="item"><div class="label">Client ID</div>{escape(str(client_id or 'unknown'))}</div>
        <div class="item"><div class="label">User ID</div>{escape(str(user_id))}</div>
        <div class="item"><div class="label">Age Group</div>{escape(profile.age_group)}</div>
        <div class="item"><div class="label">English Level</div>{escape(profile.english_level)}</div>
        <div class="item"><div class="label">Language Preference</div>{escape(profile.language_preference)}</div>
        <div class="item"><div class="label">Last Memory Update</div>{escape(last_memory_update)}</div>
      </div>
      <h2>Interests</h2>
      {interests}
      <h2>Learning Goals</h2>
      {goals}
      <h2>Stable Notes</h2>
      {notes}
    </section>

    <section>
      <h2>Recent Episodes</h2>
      <table>
        <thead><tr><th>Time</th><th>User</th><th>Assistant</th><th>Lang</th></tr></thead>
        <tbody>{episode_rows or '<tr><td colspan="4" class="empty">No episodes yet.</td></tr>'}</tbody>
      </table>
    </section>

    <section>
      <h2>Memory Events</h2>
      <table>
        <thead><tr><th>Time</th><th>Type</th><th>Payload</th></tr></thead>
        <tbody>{event_rows or '<tr><td colspan="3" class="empty">No memory events yet.</td></tr>'}</tbody>
      </table>
    </section>
  </main>
</body>
</html>"""


def _chips(values: list[str]) -> str:
    if not values:
        return '<p class="empty">None yet.</p>'
    items = "".join(f'<span class="chip">{escape(value)}</span>' for value in values)
    return f'<div class="chips">{items}</div>'


def _list_items(values: list[str]) -> str:
    if not values:
        return '<p class="empty">None yet.</p>'
    return "<ul>" + "".join(f"<li>{escape(value)}</li>" for value in values) + "</ul>"


def _episode_row(episode: Any) -> str:
    user_text = _display_user_text(episode.user_text)
    return (
        "<tr>"
        f"<td>{escape(_format_time(episode.created_at))}</td>"
        f"<td><pre>{escape(user_text)}</pre></td>"
        f"<td><pre>{escape(episode.assistant_text)}</pre></td>"
        f"<td>{escape(episode.detected_language)}</td>"
        "</tr>"
    )


def _event_row(event: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{escape(_format_time(event['created_at']))}</td>"
        f"<td>{escape(event['event_type'])}</td>"
        f"<td><pre>{escape(_format_json(event['payload_json']))}</pre></td>"
        "</tr>"
    )


def _display_user_text(user_text: str) -> str:
    try:
        payload = json.loads(user_text)
    except json.JSONDecodeError:
        return user_text
    if isinstance(payload, dict) and isinstance(payload.get("content"), str):
        return payload["content"]
    return user_text


def _format_json(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _device_links(devices: list[dict[str, Any]], selected_device_id: str) -> str:
    if not devices:
        return '<span class="empty">No devices yet.</span>'
    links = []
    for device in devices:
        device_id = str(device["device_id"])
        active = " active" if device_id == selected_device_id else ""
        label = escape(device_id)
        href_device_id = quote(device_id, safe="")
        links.append(
            f'<a class="device{active}" href="/memory?device_id={href_device_id}">{label}</a>'
        )
    return "".join(links)


def _selected_device(devices: list[dict[str, Any]], selected_device_id: str) -> dict[str, Any] | None:
    for device in devices:
        if str(device["device_id"]) == selected_device_id:
            return device
    return None


def _format_time(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


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

    yield _sse_data(
        _chat_completion_chunk_payload(
            completion_id=completion_id,
            model=model,
            delta={"role": "assistant"},
            finish_reason=None,
        )
    )

    try:
        async for delta in provider.stream(
            messages=messages,
            model=model,
            temperature=temperature,
        ):
            chunks.append(delta)
            yield _sse_data(
                _chat_completion_chunk_payload(
                    completion_id=completion_id,
                    model=model,
                    delta={"content": delta},
                    finish_reason=None,
                )
            )
    except Exception:
        logger.exception("Model provider streaming request failed")
        yield _sse_data(
            {
                "object": "error",
                "error": {"message": "model provider request failed"},
            }
        )
        yield "data: [DONE]\n\n"
        return

    assistant_text = "".join(chunks)
    episode = repository.add_episode(
        user_id=user_id,
        session_id=session_id,
        user_text=user_text,
        assistant_text=assistant_text,
        detected_language=detected_language,
    )
    try:
        await memory_service.update_from_episode(
            user_id,
            episode.episode_id,
            user_text,
            assistant_text,
        )
    except Exception:
        logger.exception("Memory extraction failed for streamed episode")
    yield _sse_data(
        _chat_completion_chunk_payload(
            completion_id=completion_id,
            model=model,
            delta={},
            finish_reason="stop",
        )
    )
    yield "data: [DONE]\n\n"


app = create_app()
