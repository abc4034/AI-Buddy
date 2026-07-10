from __future__ import annotations

import asyncio
import json
import logging
import audioop
from json import JSONDecodeError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, PlainTextResponse
from buddy_brain.prompting import sanitize_tts_text
from buddy_gateway.asr import ASRAudioArtifact, ASRProviderError, asr_provider_catalog, build_asr_provider
from buddy_gateway.audio_artifact_writer import AudioArtifactWriter
from buddy_gateway.audio_frames import ParsedAudioFrame, TimestampAudioBuffer, parse_audio_frame
from buddy_gateway.audio_store import AudioArtifactStore
from buddy_gateway.config import GatewaySettings
from buddy_gateway.core_client import BuddyCoreClient, BuddyCoreError
from buddy_gateway.opus_codec import decode_opus_frames_to_wav, encode_pcm16_mono_to_opus_frames, wav_bytes_to_pcm16_mono
from buddy_gateway.state import GatewayState, epoch_seconds
from buddy_gateway.tts import TTSProviderError, TTSResult, build_tts_provider, tts_provider_catalog


logger = logging.getLogger(__name__)

DEFAULT_AUDIO_PARAMS = {
    "format": "opus",
    "sample_rate": 16000,
    "channels": 1,
    "frame_duration": 60,
}


@dataclass
class ActiveASRTurn:
    turn_id: str
    frames: list[ParsedAudioFrame] = field(default_factory=list)
    processed: bool = False


def create_http_app(
    settings: GatewaySettings | None = None,
    state: GatewayState | None = None,
    core_client: Any | None = None,
    audio_store: AudioArtifactStore | None = None,
    asr_provider: Any | None = None,
    tts_provider: Any | None = None,
) -> FastAPI:
    settings = settings or GatewaySettings()
    state = state or GatewayState(session_history_limit=settings.session_history_limit)
    core_client = core_client or BuddyCoreClient(base_url=settings.buddy_core_base_url)
    audio_store = audio_store or AudioArtifactStore(
        base_dir=settings.audio_artifact_dir,
        session_limit=settings.audio_session_limit,
    )
    asr_provider = asr_provider or build_asr_provider(settings)
    tts_provider = tts_provider or build_tts_provider(settings)
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

    @api.get("/debug/asr/providers")
    async def debug_asr_providers() -> dict[str, Any]:
        return asr_provider_catalog(settings)

    @api.get("/debug/tts/providers")
    async def debug_tts_providers() -> dict[str, Any]:
        return tts_provider_catalog(settings)

    @api.post("/debug/sessions/{session_id}/transcribe-audio")
    async def transcribe_audio(session_id: str) -> dict[str, Any]:
        session = state.session_summary(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="session not found")
        try:
            decode_payload = audio_store.decode_session(session_id)
            wav_path = decode_payload.get("wav_path")
            if not isinstance(wav_path, str):
                raise ValueError("decoded wav path missing")
            turn = state.start_asr_turn(session_id, trigger="manual_debug")
            if not turn:
                raise HTTPException(status_code=404, detail="session not found")
            artifact = ASRAudioArtifact(
                session_id=session_id,
                turn_id=turn["turn_id"],
                device_id=session.get("device_id"),
                client_id=session.get("client_id"),
                opus_frames=[],
                wav_bytes=Path(wav_path).read_bytes(),
                wav_path=wav_path,
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
            )
            return await _run_asr_artifact(
                state=state,
                core_client=core_client,
                asr_provider=asr_provider,
                tts_provider=tts_provider,
                settings=settings,
                session=session,
                artifact=artifact,
                websocket=None,
                tts_tasks=None,
                send_stt_to_device=False,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="audio session not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
    asr_provider: Any | None = None,
    tts_provider: Any | None = None,
) -> FastAPI:
    settings = settings or GatewaySettings()
    state = state or GatewayState(session_history_limit=settings.session_history_limit)
    core_client = core_client or BuddyCoreClient(base_url=settings.buddy_core_base_url)
    audio_store = audio_store or AudioArtifactStore(
        base_dir=settings.audio_artifact_dir,
        session_limit=settings.audio_session_limit,
    )
    asr_provider = asr_provider or build_asr_provider(settings)
    tts_provider = tts_provider or build_tts_provider(settings)
    audio_writer = AudioArtifactWriter(audio_store)
    audio_buffers: dict[str, TimestampAudioBuffer] = {}
    active_asr_turns: dict[str, ActiveASRTurn] = {}
    tts_tasks: dict[str, asyncio.Task[Any]] = {}
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
                    message_payload = await _handle_text_message(
                        websocket=websocket,
                        state=state,
                        core_client=core_client,
                        tts_tasks=tts_tasks,
                        session_id=session.session_id,
                        text=text,
                    )
                    if _is_listen_start(message_payload):
                        turn = state.start_asr_turn(session.session_id, trigger="listen_start")
                        if turn:
                            active_asr_turns[session.session_id] = ActiveASRTurn(turn_id=turn["turn_id"])
                    elif _is_listen_stop(message_payload):
                        await _flush_audio_buffer_to_writer(
                            session_id=session.session_id,
                            device_id=device_id,
                            client_id=client_id,
                            audio_buffer=audio_buffers.get(session.session_id),
                            audio_writer=audio_writer,
                            active_asr_turn=active_asr_turns.get(session.session_id),
                        )
                        turn = active_asr_turns.pop(session.session_id, None)
                        await _process_active_asr_turn(
                            state=state,
                            core_client=core_client,
                            asr_provider=asr_provider,
                            tts_provider=tts_provider,
                            settings=settings,
                            session_summary=state.session_summary(session.session_id),
                            active_turn=turn,
                            trigger="listen_stop",
                            websocket=websocket,
                            tts_tasks=tts_tasks,
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
                    await _write_audio_frames(
                        session_id=session.session_id,
                        device_id=device_id,
                        client_id=client_id,
                        frames=emitted_frames,
                        audio_writer=audio_writer,
                        active_asr_turn=active_asr_turns.get(session.session_id),
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
                await _flush_audio_buffer_to_writer(
                    session_id=session.session_id,
                    device_id=device_id,
                    client_id=client_id,
                    audio_buffer=audio_buffer,
                    audio_writer=audio_writer,
                    active_asr_turn=active_asr_turns.get(session.session_id),
                )
            turn = active_asr_turns.pop(session.session_id, None)
            await _process_active_asr_turn(
                state=state,
                core_client=core_client,
                asr_provider=asr_provider,
                tts_provider=tts_provider,
                settings=settings,
                session_summary=state.session_summary(session.session_id),
                active_turn=turn,
                trigger="disconnect",
                websocket=None,
                tts_tasks=tts_tasks,
            )
            task = tts_tasks.pop(session.session_id, None)
            if task and not task.done():
                task.cancel()
            summary = state.finish_session(session.session_id)
            await audio_writer.finish_session(session.session_id)
            logger.info("WebSocket disconnected summary=%s", summary)

    return api


async def _handle_text_message(
    *,
    websocket: WebSocket,
    state: GatewayState,
    core_client: Any,
    tts_tasks: dict[str, asyncio.Task[Any]],
    session_id: str,
    text: str,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except JSONDecodeError:
        state.record_text_message(session_id, "invalid_json", {"raw": text})
        logger.warning("Invalid JSON message session_id=%s raw=%s", session_id, text)
        return None

    if not isinstance(payload, dict):
        state.record_text_message(session_id, "non_object_json", {"raw": payload})
        return None

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
    elif message_type == "abort":
        await _abort_tts_playback(websocket=websocket, session_id=session_id, tts_tasks=tts_tasks)
    return payload


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


async def _write_audio_frames(
    *,
    session_id: str,
    device_id: str | None,
    client_id: str | None,
    frames: list[Any],
    audio_writer: AudioArtifactWriter,
    active_asr_turn: ActiveASRTurn | None,
) -> None:
    for frame in frames:
        if active_asr_turn is not None:
            active_asr_turn.frames.append(frame)
        await audio_writer.enqueue_frame(
            session_id=session_id,
            device_id=device_id,
            client_id=client_id,
            frame=frame,
        )


async def _flush_audio_buffer_to_writer(
    *,
    session_id: str,
    device_id: str | None,
    client_id: str | None,
    audio_buffer: TimestampAudioBuffer | None,
    audio_writer: AudioArtifactWriter,
    active_asr_turn: ActiveASRTurn | None,
) -> None:
    if audio_buffer is None:
        return
    await _write_audio_frames(
        session_id=session_id,
        device_id=device_id,
        client_id=client_id,
        frames=audio_buffer.flush(),
        audio_writer=audio_writer,
        active_asr_turn=active_asr_turn,
    )


async def _process_active_asr_turn(
    *,
    state: GatewayState,
    core_client: Any,
    asr_provider: Any,
    tts_provider: Any,
    settings: GatewaySettings,
    session_summary: dict[str, Any] | None,
    active_turn: ActiveASRTurn | None,
    trigger: str,
    websocket: WebSocket | None,
    tts_tasks: dict[str, asyncio.Task[Any]] | None,
) -> dict[str, Any] | None:
    if not active_turn or active_turn.processed or session_summary is None:
        return None
    active_turn.processed = True
    state.update_asr_turn(
        session_summary["session_id"],
        active_turn.turn_id,
        trigger=trigger,
        status="processing",
        audio_frame_count=len(active_turn.frames),
    )
    if not active_turn.frames:
        return state.update_asr_turn(
            session_summary["session_id"],
            active_turn.turn_id,
            status="error",
            error="audio turn has no opus frames",
        )
    if getattr(asr_provider, "provider_name", "disabled") == "disabled":
        return state.update_asr_turn(
            session_summary["session_id"],
            active_turn.turn_id,
            status="skipped",
            error="ASR provider is disabled",
        )
    try:
        opus_frames = [frame.payload for frame in _ordered_frames_for_asr_decode(active_turn.frames)]
        decoded = decode_opus_frames_to_wav(opus_frames)
        artifact = ASRAudioArtifact(
            session_id=session_summary["session_id"],
            turn_id=active_turn.turn_id,
            device_id=session_summary.get("device_id"),
            client_id=session_summary.get("client_id"),
            opus_frames=opus_frames,
            wav_bytes=decoded.wav_bytes,
            wav_path=None,
            sample_rate=decoded.sample_rate,
            channels=decoded.channels,
            frame_duration_ms=60,
        )
        return await _run_asr_artifact(
            state=state,
            core_client=core_client,
            asr_provider=asr_provider,
            tts_provider=tts_provider,
            settings=settings,
            session=session_summary,
            artifact=artifact,
            websocket=websocket,
            tts_tasks=tts_tasks,
            send_stt_to_device=settings.send_stt_to_device,
        )
    except (ASRProviderError, ValueError, RuntimeError) as exc:
        return state.update_asr_turn(
            session_summary["session_id"],
            active_turn.turn_id,
            status="error",
            error=str(exc),
        )


async def _run_asr_artifact(
    *,
    state: GatewayState,
    core_client: Any,
    asr_provider: Any,
    tts_provider: Any,
    settings: GatewaySettings,
    session: dict[str, Any],
    artifact: ASRAudioArtifact,
    websocket: WebSocket | None,
    tts_tasks: dict[str, asyncio.Task[Any]] | None,
    send_stt_to_device: bool,
) -> dict[str, Any]:
    if getattr(asr_provider, "provider_name", "disabled") == "disabled":
        turn = state.update_asr_turn(
            artifact.session_id,
            artifact.turn_id,
            status="skipped",
            error="ASR provider is disabled",
        )
        return {"status": "skipped", **(turn or {})}
    try:
        result = await asr_provider.transcribe(artifact)
    except ASRProviderError as exc:
        turn = state.update_asr_turn(
            artifact.session_id,
            artifact.turn_id,
            status="error",
            asr_provider=getattr(asr_provider, "provider_name", None),
            error=str(exc),
        )
        return {"status": "error", **(turn or {})}

    transcript = result.text.strip()
    if not transcript:
        turn = state.update_asr_turn(
            artifact.session_id,
            artifact.turn_id,
            status="no_text",
            asr_provider=result.provider,
            transcript="",
        )
        return {"status": "no_text", **(turn or {})}

    sent_stt = False
    if send_stt_to_device and websocket is not None:
        await websocket.send_json(
            {
                "type": "stt",
                "text": transcript,
                "session_id": artifact.session_id,
            }
        )
        sent_stt = True

    try:
        assistant_text = await core_client.complete_text(
            device_id=session.get("device_id"),
            client_id=session.get("client_id"),
            session_id=artifact.session_id,
            text=transcript,
            source="buddy_gateway_asr",
            metadata={
                "asr_provider": result.provider,
                "asr_turn_id": artifact.turn_id,
            },
        )
    except (BuddyCoreError, RuntimeError) as exc:
        turn = state.update_asr_turn(
            artifact.session_id,
            artifact.turn_id,
            status="buddy_core_error",
            asr_provider=result.provider,
            transcript=transcript,
            sent_stt_to_device=sent_stt,
            error=str(exc),
        )
        return {"status": "buddy_core_error", **(turn or {})}

    turn = state.update_asr_turn(
        artifact.session_id,
        artifact.turn_id,
        status="ok",
        asr_provider=result.provider,
        transcript=transcript,
        assistant_text=assistant_text,
        sent_stt_to_device=sent_stt,
    )
    if websocket is not None and getattr(tts_provider, "provider_name", "disabled") != "disabled":
        _start_tts_task(
            state=state,
            tts_provider=tts_provider,
            settings=settings,
            session_id=artifact.session_id,
            asr_turn_id=artifact.turn_id,
            text=assistant_text,
            websocket=websocket,
            tts_tasks=tts_tasks,
        )
    return {"status": "ok", **(turn or {})}


def _start_tts_task(
    *,
    state: GatewayState,
    tts_provider: Any,
    settings: GatewaySettings,
    session_id: str,
    asr_turn_id: str,
    text: str,
    websocket: WebSocket,
    tts_tasks: dict[str, asyncio.Task[Any]] | None,
) -> None:
    if tts_tasks is None:
        return
    previous = tts_tasks.pop(session_id, None)
    if previous and not previous.done():
        previous.cancel()
    task = asyncio.create_task(
        _run_tts_turn(
            state=state,
            tts_provider=tts_provider,
            settings=settings,
            session_id=session_id,
            asr_turn_id=asr_turn_id,
            text=text,
            websocket=websocket,
        )
    )
    tts_tasks[session_id] = task

    def _remove_completed(completed: asyncio.Task[Any]) -> None:
        if tts_tasks.get(session_id) is completed:
            tts_tasks.pop(session_id, None)

    task.add_done_callback(_remove_completed)


async def _run_tts_turn(
    *,
    state: GatewayState,
    tts_provider: Any,
    settings: GatewaySettings,
    session_id: str,
    asr_turn_id: str,
    text: str,
    websocket: WebSocket,
) -> dict[str, Any] | None:
    speak_text = sanitize_tts_text(text) or text.strip()
    turn = state.start_tts_turn(session_id, asr_turn_id=asr_turn_id, text=speak_text)
    if not turn:
        return None
    turn_id = turn["turn_id"]

    try:
        result = await tts_provider.synthesize(speak_text)
        pcm = _tts_result_to_device_pcm(result)
        opus_frames = encode_pcm16_mono_to_opus_frames(pcm, sample_rate=16000, frame_duration_ms=60)
        if not opus_frames:
            return state.update_tts_turn(
                session_id,
                turn_id,
                status="error",
                provider=result.provider,
                audio_format=result.audio_format,
                error="TTS produced no audio frames",
            )

        state.update_tts_turn(
            session_id,
            turn_id,
            status="sending",
            provider=result.provider,
            audio_format=result.audio_format,
            audio_frame_count=len(opus_frames),
        )
        await _send_tts_json(websocket, session_id, "start")
        await _send_tts_json(websocket, session_id, "sentence_start", speak_text)
        for index, opus_frame in enumerate(opus_frames):
            await websocket.send_bytes(opus_frame)
            if settings.tts_frame_delay_ms > 0 and index < len(opus_frames) - 1:
                await asyncio.sleep(settings.tts_frame_delay_ms / 1000)
        await _send_tts_json(websocket, session_id, "stop")
        return state.update_tts_turn(
            session_id,
            turn_id,
            status="ok",
            provider=result.provider,
            audio_format=result.audio_format,
            audio_frame_count=len(opus_frames),
        )
    except asyncio.CancelledError:
        state.update_tts_turn(session_id, turn_id, status="aborted", error="TTS playback aborted")
        raise
    except (TTSProviderError, ValueError, RuntimeError) as exc:
        try:
            await _send_tts_json(websocket, session_id, "stop")
        except RuntimeError:
            pass
        return state.update_tts_turn(
            session_id,
            turn_id,
            status="error",
            provider=getattr(tts_provider, "provider_name", None),
            error=str(exc),
        )


def _tts_result_to_device_pcm(result: TTSResult) -> bytes:
    audio_format = result.audio_format.strip().lower()
    if audio_format == "wav":
        return wav_bytes_to_pcm16_mono(result.audio_bytes, target_sample_rate=16000)
    if audio_format == "pcm":
        pcm = result.audio_bytes
        if result.channels > 1:
            pcm = audioop.tomono(pcm, 2, 1.0 / result.channels, 1.0 / result.channels)
        if result.sample_rate != 16000:
            pcm, _ = audioop.ratecv(pcm, 2, 1, result.sample_rate, 16000, None)
        return pcm
    raise ValueError(f"unsupported TTS audio format '{result.audio_format}'")


async def _send_tts_json(websocket: WebSocket, session_id: str, state: str, text: str | None = None) -> None:
    payload = {
        "type": "tts",
        "state": state,
        "session_id": session_id,
    }
    if text is not None:
        payload["text"] = text
    await websocket.send_json(payload)


async def _abort_tts_playback(
    *,
    websocket: WebSocket,
    session_id: str,
    tts_tasks: dict[str, asyncio.Task[Any]],
) -> None:
    task = tts_tasks.pop(session_id, None)
    if task and not task.done():
        task.cancel()
    await _send_tts_json(websocket, session_id, "stop")


def _is_listen_start(payload: dict[str, Any] | None) -> bool:
    return bool(payload and payload.get("type") == "listen" and payload.get("state") == "start")


def _is_listen_stop(payload: dict[str, Any] | None) -> bool:
    return bool(payload and payload.get("type") == "listen" and payload.get("state") == "stop")


def _ordered_frames_for_asr_decode(frames: list[ParsedAudioFrame]) -> list[ParsedAudioFrame]:
    if not frames or not all(isinstance(frame.timestamp, int) for frame in frames):
        return frames
    return sorted(
        frames,
        key=lambda frame: (
            frame.timestamp if frame.timestamp is not None else 0,
            frame.sequence if isinstance(frame.sequence, int) else 0,
        ),
    )


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
