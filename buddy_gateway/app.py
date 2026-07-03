from __future__ import annotations

import json
import logging
from json import JSONDecodeError
from typing import Any

from fastapi import FastAPI, Request, WebSocket
from buddy_gateway.config import GatewaySettings
from buddy_gateway.state import GatewayState, epoch_seconds


logger = logging.getLogger(__name__)

DEFAULT_AUDIO_PARAMS = {
    "format": "opus",
    "sample_rate": 24000,
    "channels": 1,
    "frame_duration": 60,
}


def create_http_app(
    settings: GatewaySettings | None = None,
    state: GatewayState | None = None,
) -> FastAPI:
    settings = settings or GatewaySettings()
    state = state or GatewayState(session_history_limit=settings.session_history_limit)
    api = FastAPI(title="Buddy Device Gateway")

    @api.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "http_port": settings.http_port,
            "websocket_port": settings.websocket_port,
            "websocket_url": settings.websocket_url(),
            "recent_devices": state.recent_device_count(),
            "session_count": len(state.session_summaries()),
        }

    @api.get("/debug/sessions")
    async def debug_sessions() -> dict[str, Any]:
        sessions = state.session_summaries()
        return {
            "session_count": len(sessions),
            "sessions": sessions,
            "ota_requests": state.ota_summaries(),
        }

    @api.get("/xiaozhi/ota/")
    async def ota_get() -> dict[str, Any]:
        return _ota_payload(settings=settings, version="0.0.0")

    @api.post("/xiaozhi/ota/")
    async def ota_post(request: Request) -> dict[str, Any]:
        body = await _safe_json(request)
        headers = _headers_dict(request.headers)
        device_id = _header_value(headers, "device-id")
        client_id = _header_value(headers, "client-id")
        version = _version_from_body(body)
        board = body.get("board") if isinstance(body, dict) else None
        state.record_ota(
            device_id=device_id,
            client_id=client_id,
            board=board,
            version=version,
            headers=headers,
        )
        logger.info(
            "OTA request device_id=%s client_id=%s version=%s board=%s websocket=%s",
            device_id,
            client_id,
            version,
            board,
            settings.websocket_url(),
        )
        return _ota_payload(settings=settings, version=version)

    return api


def create_websocket_app(
    settings: GatewaySettings | None = None,
    state: GatewayState | None = None,
) -> FastAPI:
    settings = settings or GatewaySettings()
    state = state or GatewayState(session_history_limit=settings.session_history_limit)
    api = FastAPI(title="Buddy Device Gateway WebSocket")

    @api.websocket("/xiaozhi/v1/")
    async def xiaozhi_websocket(websocket: WebSocket) -> None:
        headers = _headers_dict(websocket.headers)
        device_id = _header_value(headers, "device-id")
        client_id = _header_value(headers, "client-id")
        remote_address = _remote_address(websocket)
        await websocket.accept()
        session = state.start_session(
            device_id=device_id,
            client_id=client_id,
            remote_address=remote_address,
            headers=headers,
        )
        logger.info(
            "WebSocket connected session_id=%s device_id=%s client_id=%s remote=%s",
            session.session_id,
            device_id,
            client_id,
            remote_address,
        )
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                text = message.get("text")
                payload = message.get("bytes")
                if text is not None:
                    await _handle_text_message(
                        websocket=websocket,
                        state=state,
                        session_id=session.session_id,
                        text=text,
                    )
                elif payload is not None:
                    state.record_audio_frame(session.session_id, len(payload))
                    logger.debug(
                        "Audio frame session_id=%s bytes=%s",
                        session.session_id,
                        len(payload),
                    )
        finally:
            summary = state.finish_session(session.session_id)
            logger.info("WebSocket disconnected summary=%s", summary)

    return api


async def _handle_text_message(
    *,
    websocket: WebSocket,
    state: GatewayState,
    session_id: str,
    text: str,
) -> None:
    try:
        payload = json.loads(text)
    except JSONDecodeError:
        state.record_text_message(session_id, "invalid_json", {"raw": text})
        logger.warning("Invalid JSON message session_id=%s raw=%s", session_id, text)
        return

    if not isinstance(payload, dict):
        state.record_text_message(session_id, "non_object_json", {"raw": payload})
        return

    message_type = payload.get("type")
    if not isinstance(message_type, str) or not message_type:
        message_type = "unknown"
    state.record_text_message(session_id, message_type, payload)
    logger.info("WebSocket message session_id=%s type=%s", session_id, message_type)

    if message_type == "hello":
        await websocket.send_json(_welcome_payload(session_id, payload))
    elif message_type == "ping":
        await websocket.send_json({"type": "pong", "session_id": session_id})


def _welcome_payload(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    audio_params = payload.get("audio_params")
    if not isinstance(audio_params, dict):
        audio_params = DEFAULT_AUDIO_PARAMS
    return {
        "type": "hello",
        "version": payload.get("version", 1),
        "transport": "websocket",
        "session_id": session_id,
        "audio_params": audio_params,
    }


def _ota_payload(settings: GatewaySettings, version: str) -> dict[str, Any]:
    return {
        "server_time": {
            "timestamp": epoch_seconds() * 1000,
            "timezone_offset": 480,
        },
        "firmware": {
            "version": version,
            "url": "",
        },
        "websocket": {
            "url": settings.websocket_url(),
            "token": "",
        },
        "message": "Buddy Device Gateway v0.1 is running.",
    }


async def _safe_json(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except (JSONDecodeError, UnicodeDecodeError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _version_from_body(body: dict[str, Any]) -> str:
    for key in ("version", "firmware_version"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    application = body.get("application")
    if isinstance(application, dict):
        value = application.get("version")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "0.0.0"


def _headers_dict(headers: Any) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in dict(headers).items()}


def _header_value(headers: dict[str, str], name: str) -> str | None:
    value = headers.get(name.lower())
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _remote_address(websocket: WebSocket) -> str | None:
    client = websocket.client
    if not client:
        return None
    return f"{client.host}:{client.port}"


app = create_http_app()
