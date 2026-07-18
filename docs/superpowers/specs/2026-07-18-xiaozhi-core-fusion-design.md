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
- Preserve every retained dependency, model, and asset license/notice required by its source. Import is blocked when provenance is unknown or a license is incompatible with repository distribution.

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

### 3.2 HTTP and Buddy ownership

The pinned XiaoZhi `app.py` remains the runtime entrypoint and owns both network listeners in one process:

- WebSocket speech core on `8000`
- XiaoZhi `SimpleHttpServer` on `8003`

The existing Buddy OTA response, health routes, and bounded debug routes are fused into XiaoZhi's `SimpleHttpServer`; no separate Buddy HTTP process and no cross-process diagnostic transport are introduced.

Buddy-owned code keeps these responsibilities:

- Buddy Core on port `8010`
- device identity forwarding
- child profile, persona, memory, and LLM response generation
- Windows startup and validation scripts

The fused HTTP service advertises the XiaoZhi speech core directly:

```text
ws://<LAN-IP>:8000/xiaozhi/v1/
```

There is no per-frame WebSocket adapter between ESP32 and XiaoZhi. The production runtime consists of two processes only: Buddy Core (`8010`) and fused XiaoZhi (`8000` plus `8003`).

## 4. Source Integration Layout

Import the complete pinned `main/xiaozhi-server` runtime subtree under a dedicated repository path while preserving its original package layout:

```text
xiaozhi_server/
  core/
  config/
  plugins_func/
  app.py
  ...complete pinned runtime subtree
```

The first checkpoint imports the complete runtime subtree and proves that the unmodified entrypoint boots. No modules are pruned and no compatibility stubs are added in this version. Manager UI, database deployment, MQTT, tools, voiceprint, reporting, and unrelated providers are disabled through production configuration, not removed from the source tree. Any future pruning requires a separate mechanically generated import/runtime-closure plan.

The imported subtree is treated as upstream-owned code. Buddy-specific implementations are added through XiaoZhi's provider system rather than by replacing its pipeline. Every upstream-file modification is listed in the patch inventory and covered by a focused test.

## 5. Provider Fusion

### 5.1 ASR

First evaluate and configure the pinned native `qwen3_asr_flash` provider against the currently verified Qwen API. Add a provider implementation only if a focused compatibility test proves that the native provider cannot use the required endpoint/model. Any new implementation follows XiaoZhi's native ASR contract and receives audio through the original XiaoZhi ASR/VAD pipeline.

Provider selection remains configuration-driven. The existing XiaoZhi local-model and ASR-server provider slots remain available where their required dependencies are present; unsupported slots must be reported clearly rather than silently falling back.

### 5.2 LLM and Buddy Core

Add `BuddyCoreLLMProvider` as a XiaoZhi LLM provider. It calls:

```text
POST http://127.0.0.1:8010/v1/chat/completions
```

Every Buddy Core request contains this exact top-level metadata object:

```json
{
  "metadata": {
    "device_id": "<device-id header>",
    "client_id": "<client-id header or device-id fallback>",
    "session_id": "<xiaozhi session id>",
    "source": "xiaozhi_core_fusion"
  }
}
```

The values are captured once per connection in an immutable `SessionContext` and stored in a concurrency-safe in-process registry keyed by XiaoZhi `session_id`. `BuddyCoreLLMProvider.response(session_id, dialogue)` performs a read-only lookup for each call. It never stores mutable device metadata on the shared provider instance. The registry entry is removed during connection teardown.

Every request therefore includes:

- `device_id`
- `client_id`
- XiaoZhi `session_id`
- `source: xiaozhi_core_fusion`

The provider selects only the final current-turn `user` message from XiaoZhi's dialogue and sends that text plus immutable metadata to Buddy Core. It does not forward XiaoZhi system messages or accumulated user/assistant history. Buddy Core reconstructs history from its own memory and remains the sole persona, prompt, and conversational-memory authority. A missing current user message is a provider error. The provider returns Buddy Core's assistant text through XiaoZhi's normal LLM response path. XiaoZhi's own memory, persona, and LLM implementations are not used for the production Buddy path.

Other XiaoZhi LLM providers retain the native `(session_id, dialogue)` contract. No shared-provider signature change is required. Tests must interleave two sessions on one provider instance and prove identity metadata cannot cross.

### 5.3 TTS

Add or configure a XiaoZhi TTS provider for the currently verified Qwen TTS API. It produces the audio format expected by XiaoZhi's existing encoder and send queue.

XiaoZhi remains responsible for sentence queuing, Opus framing, five-frame pre-buffering, rate control, `tts start/sentence_start/stop`, and abort behavior.

## 6. OTA, Health, and Debug

XiaoZhi's in-process `SimpleHttpServer` remains on `8003` and does not accept device WebSocket audio.

Required endpoints:

- `GET/POST /xiaozhi/ota/`
- `GET /health`
- `GET /debug/sessions`
- `GET /debug/asr/providers`
- `GET /debug/tts/providers`

Debug information is emitted by narrow event hooks in the XiaoZhi connection lifecycle into an in-process bounded registry served by `SimpleHttpServer`. There is no IPC. Allowed events are connection open/close, listen state, ASR completion/error, Buddy Core completion/error, TTS start/stop/error, and abort. Audio frames, PCM/Opus payloads, per-frame VAD probabilities, prompts, API keys, authorization headers, and full upstream configuration are prohibited.

Each session retains at most 20 lifecycle/turn events; the registry retains at most 20 completed sessions plus active sessions. Registry writes are non-blocking in-memory copies. Debug exceptions are caught and logged at debug level, queue/backpressure is impossible because hooks do not enqueue work, and debug failure must never interrupt the XiaoZhi speech path.

## 7. Configuration and Startup

Use one Buddy production configuration overlay to select provider implementations and service URLs while leaving upstream speech parameters at pinned defaults unless explicitly changed. The following invariants are mandatory for the Buddy path:

- `manager-api.url` and `manager-api.secret` are empty
- `read_config_from_api: false`
- `selected_module.Memory: nomem`
- `selected_module.Intent: nointent`
- Buddy Core is the selected LLM provider
- `end_prompt.enable: false`
- no tool/function-call, MCP tool, context-provider, VLLM, voiceprint, reporting, or manager-API behavior may alter a user turn
- XiaoZhi's system prompt is neutral, and `BuddyCoreLLMProvider` strips system messages before the Buddy call

After XiaoZhi finishes loading and merging configuration but before either listener starts, startup validates the effective configuration against every invariant above. It fails closed on any mismatch. Per-device manager configuration is therefore unreachable in the Buddy production path rather than merely ignored by convention.

The Windows startup command launches in this order:

1. Confirm `8000`, `8003`, and `8010` are available or owned by the expected process.
2. Start Buddy Core on `8010` and wait for its health endpoint.
3. Start the pinned XiaoZhi `app.py` working from the fused server directory; it starts WebSocket `8000` and HTTP `8003` in one process.
4. Wait for both fused endpoints and print their URLs/provider selections without secrets.

On shutdown, stop the fused XiaoZhi process first, wait for `8000/8003` release, then stop Buddy Core. Startup refuses to continue if a legacy `.run` XiaoZhi Server, experimental Gateway, or unknown process owns any required port.

Secrets remain in process/user environment variables and are never written to Git.

## 8. Error and Lifecycle Policy

- Malformed audio follows XiaoZhi's pinned connection behavior unless a proven hardware incompatibility requires a documented patch.
- ASR, Buddy Core, and TTS calls use explicit provider-level timeouts.
- Add one narrow connection lifecycle hook, `ConnectionHandler.notify_provider_failure(stage, sentence_id, asr_invocation_generation, public_error_code)`. It records one bounded debug event and schedules the existing `handleAbortMessage(conn)` coroutine on the connection event loop only when the failure still belongs to the active turn. The native abort path remains the only owner of `client_abort`, queue clearing, `tts stop`, rate-controller reset, and speaking-state reset.
- For LLM/TTS failures, `sentence_id` is required and must still equal `conn.sentence_id`; a stale failure is logged and ignored. For ASR, which runs before a reply `sentence_id` is allocated, a monotonic diagnostic-only `asr_invocation_generation` increments immediately at each existing `handle_voice_stop`/ASR invocation boundary. ASR captures that value for the invocation, and a failure with `sentence_id=None` aborts only while the captured generation is still current. The generation is used only as a stale-callback guard and never participates in VAD, turn segmentation, queueing, or playback.
- The hook is called only at existing provider failure boundaries: ASR invocation failure, Buddy provider timeout/invalid response, final exhausted TTS synthesis failure, and the existing TTS worker catch. Each patched catch calls the hook and returns immediately without writing fallback `MIDDLE`, `LAST`, audio, or control messages afterward. The upstream TTS retry loop remains intact.
- The failure patch must not override or duplicate TTS text/audio workers, queue processing, playback, rate control, `handleAbortMessage`, `clear_queues`, `clearSpeakStatus`, or any WebSocket lifecycle method. It passes only stage, sentence ID, the ASR invocation generation, and a bounded public error code; raw exception text is logged locally and never stored in debug state.
- Tests inject timeout, cancellation, malformed response, and partial TTS failure at every provider boundary and require a successful next turn on the same connection. One auto-mode test starts no new `listen` session, overlaps two ASR invocations, delivers the older failure late, and proves it cannot abort the newer turn.
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

1. Before migration, export the effective v0.5 environment/config manifest to an ignored local backup directory, record its location and SHA-256 in the test log, and verify it can start v0.5. Then import and authenticate the complete pinned runtime, models/assets used at runtime, dependencies, and licenses. Record origin URL, commit ID, tree ID, archive SHA-256, generated per-file SHA-256 manifest, modification status, and license provenance. Stop if any retained code, model, asset, or dependency has unknown provenance, a missing required notice, or an incompatible distribution license.
2. Boot the original XiaoZhi `app.py` unchanged, prove it owns `8000/8003`, and pass protocol-level hardware connection tests before applying Buddy patches.
3. Configure and validate the pinned native `qwen3_asr_flash` provider. Add a Qwen ASR provider only if the documented compatibility test fails.
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
- Startup/port ownership, provider timeout recovery, debug-hook failure, metadata-registry cleanup, and interleaved two-device identity tests pass.
- A rollback smoke drill restores the recorded v0.5 backup, starts the v0.5 services, and passes health, OTA, and one hardware voice turn without changing Buddy Core data.
- Final independent source-alignment and code-quality reviews report no open findings.

## 11. Rollback

- `codex/buddy-device-gateway-v0.5-voice-loop` remains the stable rollback branch.
- `codex/buddy-gateway-v0.6-xiaozhi-pipeline` remains the experimental rewritten-pipeline branch.
- The new fusion branch does not rewrite either branch's history.
- Rollback trigger: any failure of three-turn hardware acceptance, abort recovery, two-device identity isolation, or provider-failure recovery.
- Procedure: stop fused XiaoZhi, verify `8000/8003` are released, stop Buddy Core, switch to the v0.5 branch, restore the recorded and hash-verified v0.5 environment/config backup, start Buddy Core then the v0.5 Gateway, and run its health/OTA/voice smoke checks.
- Buddy Core SQLite/profile files are not migrated by this work, so rollback does not transform or delete memory data. Fusion debug state is in-memory and may be discarded.
