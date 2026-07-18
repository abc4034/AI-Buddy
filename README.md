# AI Buddy

Local Buddy Core service for an ESP32-S3 XiaoZhi-compatible English companion education demo.

## First Demo Scope

- Current supported demo path: Windows PowerShell with conda `xiaozhi-env`.
- Ubuntu 22 and venv setup are kept as future portability notes, not the current demo acceptance path.
- Exposes an OpenAI-compatible `/v1/chat/completions` endpoint.
- Uses DeepSeek through an OpenAI-compatible client by default.
- Stores long-term child learning memory in `data/buddy_memory.db`.
- Uses `metadata.device_id` to separate child profiles and memory.
- Reads the first persona from config with `PERSONA=cheerful` by default.
- Keeps local model deployment available by changing environment variables.
- Keeps the existing XiaoZhi Server bridge path available for comparison and fallback.
- Adds Buddy Device Gateway as the replacement track for XiaoZhi Server. Gateway v0.5 can handle OTA, WebSocket, protocol messages, Opus audio capture, WAV decoding, ASR, Buddy Core memory/profile calls, TTS synthesis, and Opus audio replies to ESP32.

## Current Replacement Status

The project currently has two runnable hardware paths:

- XiaoZhi Server bridge: ESP32 still talks to XiaoZhi Server, while XiaoZhi Server forwards LLM calls into Buddy Core. This remains available as the compatibility fallback.
- Buddy Device Gateway: ESP32 talks directly to our new Gateway on the same XiaoZhi-compatible ports, `8003` for OTA and `8000` for WebSocket. v0.5 implements the Gateway ASR-to-TTS reply path; its explicit `listen stop` path works in tests, while the real ESP32 `auto` mode currently reaches ASR only during disconnect, after the socket has closed and cannot receive TTS.

Gateway milestones now in the repo:

- v0.1: OTA and `/xiaozhi/v1/` WebSocket skeleton, hardware `device-id/client-id`, `hello/listen`, and binary audio frame counters.
- v0.2: debug text loop from Gateway to Buddy Core `/v1/chat/completions`, carrying `device_id`, `client_id`, `session_id`, and `source: buddy_gateway_debug`.
- v0.3: XiaoZhi-style OTA compatibility tweaks, raw Opus and strict 16-byte audio header handling, per-session audio artifacts under `data/gateway_audio`, and debug WAV decoding.
- v0.4: XiaoZhi-inspired ASR provider architecture, implemented `qwen_chat_audio` and generic `http_file` ASR API providers, planned local/ASR-server/streaming provider slots, and transcript-to-Buddy-Core text loop.
- v0.5: XiaoZhi-style first full voice loop, implemented DashScope Qwen HTTP TTS provider, planned local/TTS-server/streaming TTS slots, 16k/mono/60ms Opus reply encoding, `tts` state messages, and minimal `abort` playback stop.

## Docs

For the current demo phase, prefer the Windows PowerShell + conda `xiaozhi-env` path.

- Windows local demo runbook: [docs/runbooks/windows-local-demo.md](docs/runbooks/windows-local-demo.md)
- Buddy Device Gateway v0.1-v0.5: [docs/runbooks/buddy-device-gateway-v0.1.md](docs/runbooks/buddy-device-gateway-v0.1.md)
- Buddy Core configuration: [docs/buddy-core-configuration.md](docs/buddy-core-configuration.md)
- Buddy Core vs old Buddy Brain naming: [docs/buddy-core-and-buddy-brain.md](docs/buddy-core-and-buddy-brain.md)
- Memory dashboard: [docs/runbooks/memory-dashboard.md](docs/runbooks/memory-dashboard.md)
- Stabilization roadmap: [docs/superpowers/plans/2026-07-03-buddy-core-stabilization-roadmap.md](docs/superpowers/plans/2026-07-03-buddy-core-stabilization-roadmap.md)
- Fused XiaoZhi Core Windows runbook: [docs/runbooks/buddy-xiaozhi-core-fusion.md](docs/runbooks/buddy-xiaozhi-core-fusion.md)

## XiaoZhi Core Fusion

The supported hardware runtime is Buddy Core on `8010` plus the native XiaoZhi Server runtime on `8000` and `8003`. Start both in order with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_fusion.ps1 -AdvertiseHost <host-lan-ip> -CondaEnv xiaozhi-env
```

Use `http://<host-lan-ip>:8003/xiaozhi/ota/` as the device OTA URL. Check ownership and configuration with `check_local_demo_status.ps1`; it validates current listener PIDs against the atomic runtime state instead of trusting open ports. Run `smoke_xiaozhi_fusion.ps1` to replay a verified local hardware Opus capture through a unique same-socket voice loop, then stop only the owned runtime with `stop_local_demo.ps1`. The v0.5 Gateway remains branch history until the cleanup acceptance gate; do not run it on the XiaoZhi ports.

## Setup

The commands below are kept as setup notes. The currently supported hardware demo path is the Windows runbook above.

Use Python 3.10 or newer.

### Windows PowerShell

Use `py -3.10` so the venv is created with Python 3.10 even if `python` points to an older install.

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -3.10 -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

### Ubuntu 22.04

Install Python 3.10 and venv support first, then create the environment:

```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

After copying `.env.example` to `.env`, set `OPENAI_API_KEY` locally in `.env`. Do not commit `.env`.

The default hosted provider values in `.env.example` are:

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-v4-flash
PERSONA=cheerful
```

## Run

Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_core.ps1
```

Ubuntu 22.04:

```bash
source .venv/bin/activate
uvicorn buddy_brain.app:app --host 0.0.0.0 --port 8010
```

## Buddy Device Gateway

Use this path when testing the XiaoZhi Server replacement work. Stop XiaoZhi Server first because Gateway uses the same hardware ports:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_local_demo.ps1 -Ports 8000,8003
```

Start Gateway with the computer LAN IP that the ESP32 can reach:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_gateway.ps1 -AdvertiseHost <host-lan-ip>
```

For v0.5 voice-loop testing with Alibaba Bailian Qwen3-ASR and Qwen-TTS, configure ASR and TTS through local environment variables:

```powershell
[Environment]::SetEnvironmentVariable("ASR_PROVIDER", "qwen_chat_audio", "User")
[Environment]::SetEnvironmentVariable("ASR_HTTP_URL", "https://<asr-host>/compatible-mode/v1", "User")
[Environment]::SetEnvironmentVariable("ASR_MODEL", "qwen3-asr-flash-2025-09-08", "User")
[Environment]::SetEnvironmentVariable("ASR_API_KEY", "<your-asr-api-key>", "User")
[Environment]::SetEnvironmentVariable("TTS_PROVIDER", "dashscope_qwen_http", "User")
[Environment]::SetEnvironmentVariable("TTS_HTTP_URL", "https://<tts-host>/api/v1", "User")
[Environment]::SetEnvironmentVariable("TTS_MODEL", "qwen3-tts-instruct-flash", "User")
[Environment]::SetEnvironmentVariable("TTS_API_KEY", "<your-tts-api-key>", "User")
[Environment]::SetEnvironmentVariable("TTS_VOICE", "Cherry", "User")
[Environment]::SetEnvironmentVariable("TTS_LANGUAGE", "auto", "User")
```

`qwen3-asr-flash-2025-09-08` is the dated model alias configured for this Bailian workspace and verified in the local smoke test. Public Bailian examples may show `qwen3-asr-flash`; keep the workspace alias if your API call succeeds.

`qwen3-tts-instruct-flash` is the first v0.5 TTS model. v0.5 intentionally does not use `qwen3-tts-vd-2026-01-26`, because Voice Design requires creating and selecting a `voice_id` first.

Use `ASR_PROVIDER=http_file` only for providers that expose an OpenAI-style `/audio/transcriptions` multipart endpoint.

Then start Buddy Core and Gateway:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_core.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_gateway.ps1 -AdvertiseHost <host-lan-ip>
```

Set the ESP32 OTA URL to:

```text
http://<host-lan-ip>:8003/xiaozhi/ota/
```

Useful Gateway checks:

```powershell
Invoke-WebRequest http://127.0.0.1:8003/xiaozhi/ota/ -UseBasicParsing
Invoke-RestMethod http://127.0.0.1:8003/health
Invoke-RestMethod http://127.0.0.1:8003/debug/sessions
Invoke-RestMethod http://127.0.0.1:8003/debug/audio/sessions
Invoke-RestMethod http://127.0.0.1:8003/debug/asr/providers
Invoke-RestMethod http://127.0.0.1:8003/debug/tts/providers
```

After the ESP32 connects and sends audio, decode the latest captured Opus session to WAV:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_gateway_audio_capture.ps1
```

For v0.2 debug text loop testing, run Buddy Core on `8010`, keep the ESP32 connected to Gateway, then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_gateway_text_loop.ps1 -Text "I like apples"
```

For v0.4 ASR text-loop testing, run after the ESP32 has sent audio:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_gateway_asr_text_loop.ps1
```

The ASR smoke script selects a session that is present in both `/debug/sessions` and `/debug/audio/sessions`, so stale audio artifacts from before a Gateway restart are not treated as valid live sessions. It exits with an error unless ASR and Buddy Core both return an `ok` text loop result.

For v0.5 voice-loop diagnostics, use the following after an explicit `listen stop` test turn has completed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_gateway_voice_loop.ps1
```

The voice-loop smoke script checks the latest session for `asr_turns.status: ok`, `tts_turns.status: ok`, and nonzero outgoing Opus frame count. Current observed limitation: real ESP32 `auto` mode reaches ASR only during disconnect, so the WebSocket is closed before Gateway can return TTS audio; a real auto-mode hardware voice loop is not yet available.

## Test

```powershell
conda run -n xiaozhi-env python -m pytest -q
```

```bash
source .venv/bin/activate
python -m pytest -v
```

## Smoke Test

Start the server, then run:

```powershell
.\scripts\smoke_chat.ps1
```

Expected response:

- `object` is `chat.completion`
- `choices[0].message.content` contains a short bilingual Buddy answer, such as a brief Chinese greeting plus one simple English teaching sentence

If the request fails before JSON is returned, the usual cause is that the server is not running or `http://127.0.0.1:8010` is the wrong URL or port.

## Local Model Switch

Use the same API surface and change environment values:

```dotenv
OPENAI_BASE_URL=http://127.0.0.1:8001/v1
OPENAI_API_KEY=
MODEL_NAME=local-model-name
```

## XiaoZhi Server Handoff

For this local bridge demo, let the scripts auto-detect the current LAN host IP. If auto-detection ever picks the wrong adapter, pass `-HostIp <host-lan-ip>` explicitly.

Point the XiaoZhi server LLM provider at:

```text
BuddyCoreLLM:
  type: openai
  base_url: http://<host-lan-ip>:8010/v1
  api_key: local
  model_name: deepseek-v4-flash
  forward_device_metadata: true
```

Keep XiaoZhi server memory disabled for this demo. Buddy Core owns profile and memory persistence.

## XiaoZhi Local Bridge

This phase keeps the ESP32 firmware and XiaoZhi device protocol, but routes XiaoZhi server LLM calls to Buddy Core.

See the full Windows runbook: `docs/runbooks/windows-local-demo.md`.

Local URLs for the current Windows host:

```text
Buddy Core: http://<host-lan-ip>:8010
Buddy Core OpenAI base_url: http://<host-lan-ip>:8010/v1
XiaoZhi WebSocket: ws://<host-lan-ip>:8000/xiaozhi/v1/
XiaoZhi OTA: http://<host-lan-ip>:8003/xiaozhi/ota/
```

Print the current URLs:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\print_local_demo_urls.ps1
```

Prepare the XiaoZhi server runtime source under `.run/`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_xiaozhi_server.ps1
```

Render XiaoZhi `data/.config.yaml`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\render_xiaozhi_config.ps1
```

Start Buddy Core in terminal A:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_core.ps1
```

Smoke test Buddy Core in terminal B:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_chat.ps1
```

Start XiaoZhi server in terminal C after its conda environment and dependencies are installed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_xiaozhi_server.ps1
```

Check local demo status:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_local_demo_status.ps1
```

Back up memory and XiaoZhi config before reset or demo:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\backup_local_demo_data.ps1
```

Stop the local demo listeners:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_local_demo.ps1
```

The generated XiaoZhi config sets:

```yaml
selected_module:
  LLM: BuddyCoreLLM
  Memory: nomem
  Intent: nointent
```

Hardware routing pause point:

- Do not flash firmware until Buddy Core and XiaoZhi server both start successfully.
- The current ESP32 firmware still uses `https://api.tenclass.net/xiaozhi/ota/`.
- If no runtime OTA override is available, firmware must be rebuilt for `bread-compact-wifi-lcd` with the `CONFIG_OTA_URL` printed by `print_local_demo_urls.ps1`.
- When flashing is needed, stop and ask the user to plug in USB and press `BOOT` / `RESET`.
