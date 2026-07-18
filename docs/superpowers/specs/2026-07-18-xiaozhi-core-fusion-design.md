# Buddy Gateway XiaoZhi Core Fusion Design

## 1. Goal

Build the next Gateway version directly on the authenticated XiaoZhi Server speech core instead of reimplementing its VAD, turn segmentation, playback queue, rate control, abort, and connection lifecycle.

The success criterion is a real ESP32 using its existing XiaoZhi firmware completing three consecutive audible turns on one WebSocket session:

```text
ESP32 -> XiaoZhi speech core -> ASR -> Buddy Core -> TTS -> ESP32
```

Buddy Core remains the only owner of child profile, persona, memory, and LLM behavior.

## 2. Source and Version Policy

- Upstream repository: `https://github.com/xinnan-tech/xiaozhi-esp32-server.git`
- Fixed source commit: `8ec585102711516bf214b262f7d87bc04f9597e2`
- The source must be imported from an authenticated Git checkout or checksummed archive, not from the existing `.run` snapshot.
- Preserve the upstream directory structure and internal imports for the migrated server core.
- Preserve the MIT license and add one repository-level third-party notice. Do not add repetitive attribution comments to individual functions.
- Record every deliberate modification to upstream files in a concise patch inventory document.

## 3. Architecture

### 3.1 Runtime ownership

The XiaoZhi core becomes the owner of port `8000` and the full device WebSocket lifecycle:

- WebSocket handshake and session connection
- Opus decoding
- Silero VAD
- `listen start/stop/detect`
- automatic and manual turn segmentation
- ASR invocation
- LLM invocation
- TTS sentence/audio queues
- five-frame pre-buffer and 60ms rate controller
- `abort`, stop, disconnect, and cleanup

The current custom Gateway speech modules are not used in the new runtime:

- `buddy_gateway/session_runtime.py`
- `buddy_gateway/voice_pipeline.py`
- `buddy_gateway/audio_sender.py`

They remain only on the experimental branch and are not copied into the new branch.

### 3.2 Buddy-owned services

Buddy-owned code keeps these responsibilities:

- HTTP OTA on port `8003`
- health and debug endpoints
- Buddy Core on port `8010`
- device identity forwarding
- child profile, persona, memory, and LLM response generation
- Windows startup and validation scripts

OTA advertises the XiaoZhi speech core directly:

```text
ws://<LAN-IP>:8000/xiaozhi/v1/
```

There is no per-frame WebSocket adapter between ESP32 and XiaoZhi.

## 4. Source Integration Layout

Import the pinned XiaoZhi server source under a dedicated repository subtree while preserving its original package layout:

```text
xiaozhi_server/
  core/
  config/
  plugins_func/
  app.py
  ...required dependency closure
```

Only the dependency closure required for direct WebSocket speech operation is retained. Manager UI, database deployment, MQTT, MCP, intent tools, voiceprint, reporting, and unrelated providers are excluded unless an imported core module requires a small neutral interface.

The imported subtree is treated as upstream-owned code. Buddy-specific implementations are added through XiaoZhi's provider system rather than by replacing its pipeline.

## 5. Provider Fusion

### 5.1 ASR

Add a XiaoZhi ASR provider for the currently verified Qwen API. It implements XiaoZhi's native ASR provider contract and receives audio through the original XiaoZhi ASR/VAD pipeline.

Provider selection remains configuration-driven. The existing XiaoZhi local-model and ASR-server provider slots remain available where their required dependencies are present; unsupported slots must be reported clearly rather than silently falling back.

### 5.2 LLM and Buddy Core

Add `BuddyCoreLLMProvider` as a XiaoZhi LLM provider. It calls:

```text
POST http://127.0.0.1:8010/v1/chat/completions
```

Every request includes:

- `device_id`
- `client_id`
- XiaoZhi `session_id`
- `source: xiaozhi_core_fusion`

The provider returns Buddy Core's assistant text through XiaoZhi's normal LLM response path. XiaoZhi's own memory, persona, and LLM implementations are not used for the production Buddy path.

If the upstream provider interface does not expose connection metadata, modify the narrowest provider invocation point to pass immutable session metadata. This modification is part of the direct fusion, not a second speech pipeline.

### 5.3 TTS

Add or configure a XiaoZhi TTS provider for the currently verified Qwen TTS API. It produces the audio format expected by XiaoZhi's existing encoder and send queue.

XiaoZhi remains responsible for sentence queuing, Opus framing, five-frame pre-buffering, rate control, `tts start/sentence_start/stop`, and abort behavior.

## 6. OTA, Health, and Debug

The Buddy HTTP service remains on `8003` and does not accept device WebSocket audio.

Required endpoints:

- `GET/POST /xiaozhi/ota/`
- `GET /health`
- `GET /debug/sessions`
- `GET /debug/asr/providers`
- `GET /debug/tts/providers`

Debug information is emitted by narrow event hooks in the XiaoZhi connection lifecycle. Hooks copy bounded diagnostic events to the Buddy debug registry; they do not control VAD, turn finalization, playback, or connection cleanup.

Debug failure must never interrupt the XiaoZhi speech path. API keys and raw authorization headers are never returned.

## 7. Configuration and Startup

Use one Buddy configuration overlay to select the XiaoZhi provider implementations and service URLs while leaving upstream speech parameters at their pinned defaults unless explicitly changed.

The Windows startup command launches:

1. Buddy Core on `8010`
2. Buddy OTA/debug HTTP service on `8003`
3. XiaoZhi WebSocket speech core on `8000`

The startup script validates port ownership and refuses to start if the legacy `.run` XiaoZhi Server or experimental Gateway already occupies `8000/8003`.

Secrets remain in process/user environment variables and are never written to Git.

## 8. Error and Lifecycle Policy

- Malformed audio and provider failures follow XiaoZhi's pinned connection behavior unless a proven hardware incompatibility requires a documented patch.
- ASR, Buddy Core, and TTS failures remain session-local and must leave the connection able to accept another utterance.
- Device abort uses XiaoZhi's original abort and queue-clearing path.
- Disconnect uses XiaoZhi's original cleanup path and never attempts playback on a closed socket.
- Debug hooks are best-effort and cannot change connection state.
- No fallback to the custom v0.6 speech pipeline is permitted inside one running connection.

## 9. Migration Strategy

Implementation starts from the v0.5 checkpoint on branch:

```text
codex/buddy-gateway-v0.6-xiaozhi-core-fusion
```

The experimental custom-pipeline branch remains untouched as a comparison artifact. Migration proceeds in independently reviewed checkpoints:

1. Import and authenticate pinned upstream source plus licenses.
2. Boot the original WebSocket core unchanged and pass protocol-level hardware connection tests.
3. Add Qwen ASR provider and validate transcription.
4. Add Buddy Core LLM provider and validate profile/memory metadata.
5. Add Qwen TTS provider and validate audible playback through the original queue.
6. Add OTA/debug event integration without changing speech ownership.
7. Run regression, two-device isolation, abort recovery, and real-hardware acceptance.

Every checkpoint requires focused automated tests and an independent subagent review with no open findings before the next checkpoint begins.

## 10. Acceptance

The fusion is accepted only when all conditions hold:

- The authenticated XiaoZhi commit and imported-file hashes are recorded.
- ESP32 firmware remains unchanged.
- OTA points directly to the original XiaoZhi WebSocket core.
- Auto mode completes three consecutive audible turns on one WebSocket without `listen stop` or disconnect finalization.
- Hardware abort stops the current reply and the same connection handles the next turn.
- Buddy Core Memory shows the real device ID and three corresponding episodes.
- A two-device test proves session, VAD, provider, queue, abort, and memory isolation.
- Full automated tests pass.
- Final independent source-alignment and code-quality reviews report no open findings.

## 11. Rollback

- `codex/buddy-device-gateway-v0.5-voice-loop` remains the stable rollback branch.
- `codex/buddy-gateway-v0.6-xiaozhi-pipeline` remains the experimental rewritten-pipeline branch.
- The new fusion branch does not rewrite either branch's history.
