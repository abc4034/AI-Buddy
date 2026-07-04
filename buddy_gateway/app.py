from __future__ import annotations

import json
import logging
from json import JSONDecodeError
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, PlainTextResponse
from buddy_gateway.audio_artifact_writer import AudioArtifactWriter
from buddy_gateway.audio_frames import TimestampAudioBuffer, parse_audio_frame
from buddy_gateway.audio_store import AudioArtifactStore
from buddy_gateway.config import GatewaySettings
from buddy_gateway.core_client import BuddyCoreClient, BuddyCoreError
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
    core_client: Any | None = None,
    audio_store: AudioArtifactStore | None = None,
) -> FastAPI:
    settings = settings or GatewaySettings()
    state = state or GatewayState(session_history_limit=settings.session_history_limit)
    core_client = core_client or BuddyCoreClient(base_url=settings.buddy_core_base_url)
    audio_store = audio_store or AudioArtifactStore(
        base_dir=settings.audio_artifact_dir,
        session_limit=settings.audio_session_limit,
    )
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

    @api.get("/debug/audio/sessions")
    async def debug_audio_sessions() -> dict[str, Any]:
        sessions = audio_store.audio_session_summaries()
        return {
            "session_count": len(sessions),
            "sessions": sessions,
        }

    @api.post("/debug/sessions/{session_id}/decode-audio")
    async def decode_audio(session_id: str) -> dict[str, Any]:
        try:
            payload = audio_store.decode_session(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="audio session not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload["audio_url"] = _audio_url(settings, session_id)
        return payload

    @api.get("/debug/sessions/{session_id}/audio.wav")
    async def download_audio(session_id: str) -> FileResponse:
        wav_path = audio_store.wav_path_for_session(session_id)
        if wav_path is None:
            raise HTTPException(status_code=404, detail="audio wav not found")
        return FileResponse(wav_path, media_type="audio/wav", filename=f"{session_id}.wav")

    @api.post("/debug/sessions/{session_id}/inject-text")
    async def inject_debug_text(session_id: str, request: Request) -> dict[str, Any]:
        body = await _safe_json(request)
        text = body.get("text") if isinstance(body, dict) else None
        return await _run_debug_text(
            state=state,
            core_client=core_client,
            session_id=session_id,
            text=text,
        )

    @api.get("/xiaozhi/ota/")
    async def ota_get() -> PlainTextResponse:
        return PlainTextResponse(
            f"OTA interface is running. WebSocket URL: {settings.websocket_url()}",
            media_type="text/plain",
        )

    @api.post("/xiaozhi/ota/")
    async def ota_post(request: Request) -> dict[str, Any]:
        body = await _safe_json(request)
        headers = _headers_dict(request.headers)
        device_id = _header_value(headers, "device-id")
        client_id = _header_value(headers, "client-id")
        version = _version_from_request(headers=headers, body=body)
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
    core_client: Any | None = None,
    audio_store: AudioArtifactStore | None = None,
) -> FastAPI:
    settings = settings or GatewaySettings()
    state = state or GatewayState(session_history_limit=settings.session_history_limit)
    core_client = core_client or BuddyCoreClient(base_url=settings.buddy_core_base_url)
    audio_store = audio_store or AudioArtifactStore(
        base_dir=settings.audio_artifact_dir,
        session_limit=settings.audio_session_limit,
    )
    audio_writer = AudioArtifactWriter(audio_store)
    audio_buffers: dict[str, TimestampAudioBuffer] = {}
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
        audio_buffers[session.session_id] = TimestampAudioBuffer(max_size=20)
        audio_writer.start_session(session.session_id)
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
                        core_client=core_client,
                        session_id=session.session_id,
                        text=text,
                    )
                elif payload is not None:
                    parsed = parse_audio_frame(payload)
                    emitted_frames = audio_buffers[session.session_id].push(parsed)
                    state.record_audio_frame(
                        session.session_id,
                        raw_byte_count=len(payload),
                        payload_byte_count=len(parsed.payload),
                        parse_mode=parsed.mode,
                        timestamp=parsed.timestamp,
                    )
                    for emitted_frame in emitted_frames:
                        await audio_writer.enqueue_frame(
                            session_id=session.session_id,
                            device_id=device_id,
                            client_id=client_id,
                            frame=emitted_frame,
                        )
                    logger.debug(
                        "Audio frame session_id=%s mode=%s raw_bytes=%s payload_bytes=%s timestamp=%s",
                        session.session_id,
                        parsed.mode,
                        len(payload),
                        len(parsed.payload),
                        parsed.timestamp,
                    )
        finally:
            audio_buffer = audio_buffers.pop(session.session_id, None)
            if audio_buffer is not None:
                for buffered_frame in audio_buffer.flush():
                    await audio_writer.enqueue_frame(
                        session_id=session.session_id,
                        device_id=device_id,
                        client_id=client_id,
                        frame=buffered_frame,
                    )
            summary = state.finish_session(session.session_id)
            await audio_writer.finish_session(session.session_id)
            logger.info("WebSocket disconnected summary=%s", summary)

    return api


async def _handle_text_message(
    *,
    websocket: WebSocket,
    state: GatewayState,
    core_client: Any,
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
    elif message_type == "debug_text":
        result = await _run_debug_text_for_websocket(
            state=state,
            core_client=core_client,
            session_id=session_id,
            text=payload.get("text"),
        )
        await websocket.send_json(result)


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
        "message": "Buddy Device Gateway is running.",
    }


async def _run_debug_text_for_websocket(
    *,
    state: GatewayState,
    core_client: Any,
    session_id: str,
    text: Any,
) -> dict[str, Any]:
    try:
        result = await _run_debug_text(
            state=state,
            core_client=core_client,
            session_id=session_id,
            text=text,
        )
        return {"type": "debug_text_result", **result}
    except HTTPException as exc:
        error = exc.detail if isinstance(exc.detail, str) else "debug text failed"
        return {
            "type": "debug_text_result",
            "status": "error",
            "session_id": session_id,
            "error": error,
        }


async def _run_debug_text(
    *,
    state: GatewayState,
    core_client: Any,
    session_id: str,
    text: Any,
) -> dict[str, Any]:
    session = state.session_summary(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="text must be a non-empty string")

    user_text = text.strip()
    try:
        assistant_text = await core_client.complete_debug_text(
            device_id=session.get("device_id"),
            client_id=session.get("client_id"),
            session_id=session_id,
            text=user_text,
        )
    except (BuddyCoreError, RuntimeError) as exc:
        turn = state.record_debug_turn(
            session_id,
            user_text=user_text,
            status="error",
            error=str(exc),
        )
        error = turn["error"] if turn else str(exc)
        raise HTTPException(status_code=502, detail=error) from exc

    turn = state.record_debug_turn(
        session_id,
        user_text=user_text,
        status="ok",
        assistant_text=assistant_text,
    )
    return {
        "status": "ok",
        "session_id": session_id,
        "device_id": session.get("device_id"),
        "client_id": session.get("client_id"),
        "user_text": user_text,
        "assistant_text": assistant_text,
        "created_at": turn["created_at"] if turn else epoch_seconds(),
    }


async def _safe_json(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except (JSONDecodeError, UnicodeDecodeError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _version_from_request(*, headers: dict[str, str], body: dict[str, Any]) -> str:
    for key in ("device-version", "device_version", "firmware-version", "app-version", "application-version"):
        value = headers.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
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


def _audio_url(settings: GatewaySettings, session_id: str) -> str:
    return f"http://{settings.advertised_host()}:{settings.http_port}/debug/sessions/{session_id}/audio.wav"


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
