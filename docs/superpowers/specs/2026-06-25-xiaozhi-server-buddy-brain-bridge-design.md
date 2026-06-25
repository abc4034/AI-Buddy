# XiaoZhi Server Buddy Brain Bridge Design

Date: 2026-06-25

## Goal

This phase connects the already working `buddy-brain` service to an open-source XiaoZhi-compatible server so the ESP32-S3 device can eventually use our education logic while still reusing the XiaoZhi firmware and device protocol.

The successful demo path is:

```text
ESP32-S3 XiaoZhi firmware
  -> local XiaoZhi OTA / WebSocket service
  -> XiaoZhi ASR and TTS pipeline
  -> Buddy Brain OpenAI-compatible LLM endpoint
  -> DeepSeek API
  -> Buddy Brain SQLite long-term memory
```

This phase does not try to repair the current speaker path. The acceptance signal remains service logs, serial logs, screen text if available, and SQLite memory writes.

## Current Baseline

`buddy-brain` is already merged into `master` and verified:

- `GET /health`
- `POST /v1/chat/completions`
- OpenAI-compatible streaming and non-streaming responses
- DeepSeek through `OPENAI_BASE_URL=https://api.deepseek.com`
- SQLite memory at `data/buddy_memory.db`
- Test suite: `22 passed`

The Windows host has:

- LAN IP: `192.168.2.9`
- Python 3.10 available through `py -3.10`
- conda available
- Docker not available

The ESP32-S3 device is on the same Wi-Fi and was previously observed as:

- Device IP during earlier test: `192.168.2.14`
- Current OTA URL: `https://api.tenclass.net/xiaozhi/ota/`
- Firmware SKU: `bread-compact-wifi-lcd`
- Chip: ESP32-S3, 16 MB flash, 8 MB PSRAM

## Source Basis

The bridge targets the current open-source `xinnan-tech/xiaozhi-esp32-server` service. The repository documentation states that any LLM using an OpenAI-compatible API can be connected. Its `main/xiaozhi-server/config.yaml` provides:

- `selected_module.LLM` for selecting the active LLM provider.
- `selected_module.Memory: nomem` for disabling XiaoZhi memory.
- `LLM.<name>.type: openai` for OpenAI-compatible providers.
- Provider fields `base_url` or `url`, `model_name`, and `api_key`.

The OpenAI provider implementation reads `base_url` when present, falls back to `url`, and constructs `openai.OpenAI(api_key=..., base_url=...)`.

The upstream ESP32 firmware Kconfig has `CONFIG_OTA_URL`, defaulting to `https://api.tenclass.net/xiaozhi/ota/`. Therefore hardware routing to the local server eventually requires either a runtime way to change OTA URL or a firmware rebuild/flash using the local OTA URL.

## Recommended Approach

Use Windows host source deployment for this phase.

Why this approach:

- Docker is not installed on the host.
- conda and Python 3.10 are available.
- Running both `buddy-brain` and `xiaozhi-server` on Windows keeps the LAN address simple: `192.168.2.9`.
- The user already has the device and host on the same Wi-Fi.

The implementation should not vendor the full XiaoZhi server source into this repo. Instead, this repo should own small, reviewable integration assets:

- A checked-in XiaoZhi `.config.yaml` template.
- A config renderer that fills in the host LAN IP and Buddy Brain URL.
- Setup and run scripts that clone or update the upstream XiaoZhi server into ignored runtime storage.
- A local smoke-test sequence that verifies Buddy Brain first, then XiaoZhi server availability.
- A hardware handoff checklist for OTA/firmware routing.

## Runtime Layout

Use this local layout:

```text
AI Buddy/
  buddy_brain/
  scripts/
  integrations/xiaozhi_server/
    xiaozhi_config_template.yaml
    render_config.py
  data/
    buddy_memory.db
  .run/
    xiaozhi-esp32-server/
      main/xiaozhi-server/
        data/.config.yaml
```

`.run/`, `.env`, `data/`, and upstream XiaoZhi source remain untracked.

## XiaoZhi Server Configuration

The generated XiaoZhi `data/.config.yaml` should override only the fields needed for the demo:

```yaml
server:
  ip: 0.0.0.0
  port: 8000
  http_port: 8003
  websocket: ws://192.168.2.9:8000/xiaozhi/v1/
  vision_explain: http://192.168.2.9:8003/mcp/vision/explain
  auth:
    enabled: false

selected_module:
  LLM: BuddyBrainLLM
  Memory: nomem
  Intent: nointent

LLM:
  BuddyBrainLLM:
    type: openai
    base_url: http://192.168.2.9:8010/v1
    model_name: deepseek-v4-flash
    api_key: local
    temperature: 0.7
    max_tokens: 300

prompt: |
  You are Buddy, a warm English companion for a primary-school beginner.
  Keep replies short, child-friendly, and suitable for speech.
  Prefer simple English. Add a short Chinese explanation when it helps.
  Ask at most one follow-up question.
  Correct at most one clear English mistake per turn.
```

Buddy Brain remains the real prompt and memory owner. The XiaoZhi `prompt` should be short because Buddy Brain will rebuild the final educational prompt internally.

`Intent: nointent` is preferred for the first bridge because Buddy Brain does not yet implement tool-calling semantics. If later smart-home or media controls matter, intent can be re-enabled with a provider that supports function calls.

## Service Startup Flow

The operator flow should be:

1. Render XiaoZhi config for the current LAN IP.
2. Start `buddy-brain` on `0.0.0.0:8010`.
3. Verify `http://127.0.0.1:8010/health`.
4. Run the existing Buddy Brain smoke test.
5. Start XiaoZhi server on `0.0.0.0:8000` and HTTP OTA on `0.0.0.0:8003`.
6. Verify the XiaoZhi startup logs show:
   - OTA URL equivalent to `http://192.168.2.9:8003/xiaozhi/ota/`
   - WebSocket URL equivalent to `ws://192.168.2.9:8000/xiaozhi/v1/`
7. Only after both services are healthy, move to hardware routing.

## Hardware Routing Flow

The current device still points at XiaoZhi cloud OTA. The local services alone will not capture device traffic until the device requests local OTA.

The first attempt should avoid flashing if there is a supported runtime configuration path. If no runtime OTA change is available, build and flash the official firmware for `bread-compact-wifi-lcd` with:

```text
CONFIG_OTA_URL=http://192.168.2.9:8003/xiaozhi/ota/
```

When flashing is needed, the assistant must pause and ask the user to:

- Plug the ESP32 board into USB.
- Confirm the COM port.
- Press and hold `BOOT` if the board does not enter download mode.
- Tap `RESET` when requested.

No destructive erase or flash command should run without first confirming the detected chip, flash size, and target port.

## Validation

Phase success requires:

1. Buddy Brain runs on `0.0.0.0:8010`.
2. `scripts/smoke_chat.ps1` returns a normal Buddy answer.
3. Generated XiaoZhi config points LLM calls to `http://192.168.2.9:8010/v1`.
4. XiaoZhi server starts with the generated `data/.config.yaml`.
5. XiaoZhi server logs show the local OTA and WebSocket addresses.
6. A direct test call from XiaoZhi server or an equivalent OpenAI-compatible client reaches Buddy Brain.
7. After hardware routing, ESP32 sends speech text through the local XiaoZhi server.
8. Buddy Brain writes the hardware-originated turn into `episodes`.
9. Memory updates are visible in `profile` or `memory_events` for durable facts.

## Risks And Mitigations

XiaoZhi server dependency setup may be slow or fragile on Windows.

- Mitigation: use conda as upstream documentation recommends. If Windows setup fails on native audio libraries, fall back to the Ubuntu 22 VM with bridged networking.

The first local XiaoZhi ASR/TTS configuration may require external provider keys.

- Mitigation: first prove LLM bridge with text or service-level tests. Then choose the simplest ASR/TTS path that starts on the host. Hardware audio output is not a first acceptance condition.

The ESP32 cannot reach `127.0.0.1`.

- Mitigation: all device-facing URLs use `192.168.2.9`, not localhost.

Firewall may block ports `8000`, `8003`, or `8010`.

- Mitigation: test from the host first, then from another LAN client if available. If the device cannot connect, add a Windows firewall allow rule for Python on those ports.

Buddy Brain OpenAI-compatible endpoint may not support a XiaoZhi-specific field.

- Mitigation: the OpenAI provider sends standard chat completion fields. Buddy Brain currently ignores unknown extra fields through Pydantic settings where applicable; if a request model rejects an unexpected payload, add a focused compatibility test before changing parsing.

The local OTA URL requires firmware flashing.

- Mitigation: keep firmware changes minimal: official XiaoZhi firmware, current board type, only OTA URL changed. Pause for user hardware actions.

Secrets may leak into tracked files.

- Mitigation: API keys stay in `.env`, conda environment variables, or XiaoZhi local `data/.config.yaml` under `.run`; none are committed.

## Out Of Scope

- Repairing or replacing the speaker amplifier.
- Building a production cloud deployment.
- Adding a web admin UI.
- Multi-child onboarding.
- Custom TTS voice design.
- Local GPU model deployment.
- Changing XiaoZhi protocol internals unless pure configuration fails.

