# AI Buddy

AI Buddy is a Windows-first ESP32-S3 companion demo. It keeps the XiaoZhi device protocol and native speech pipeline while making Buddy Core the sole owner of child identity, persona, memory, and LLM conversation.

## Architecture

```text
ESP32 XiaoZhi firmware
  -> HTTP OTA :8003 / WebSocket :8000 / Opus
  -> fused XiaoZhi Core
       -> VAD -> ASR provider
       -> Buddy Core :8010
            -> device profile + persona
            -> SQLite memory
            -> LLM provider
       -> TTS provider -> 16 kHz Opus
  -> ESP32 playback
```

The supported runtime has two processes:

- `xiaozhi_server/` owns OTA, WebSocket, Opus, VAD, ASR, TTS, playback, and abort handling.
- `buddy_brain/` owns `device-id` identity, profile/persona configuration, SQLite memory, prompting, and the OpenAI-compatible `/v1/chat/completions` API.

The custom Buddy Device Gateway used during v0.1-v0.5 has been retired. Its runbook is archived at [docs/archive/buddy-device-gateway-v0.1-v0.5.md](docs/archive/buddy-device-gateway-v0.1-v0.5.md), and its implementation remains available in Git history.

## Current Runtime

Requirements:

- Windows PowerShell
- conda environment `xiaozhi-env`
- Python 3.10 or newer
- ESP32 and host on the same LAN

Configure Buddy Core in `.env` without committing secrets:

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=<your-key>
MODEL_NAME=deepseek-v4-flash
PERSONA=cheerful
```

ASR and TTS credentials are read from Process scope first, then Windows User environment, and rendered only into ignored `xiaozhi_server/data/.config.yaml`. See the [fusion runbook](docs/runbooks/buddy-xiaozhi-core-fusion.md) for the supported variables.

Start both services:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_fusion.ps1 -AdvertiseHost <host-lan-ip> -CondaEnv xiaozhi-env
```

Set the ESP32 OTA URL to:

```text
http://<host-lan-ip>:8003/xiaozhi/ota/
```

Runtime endpoints:

```text
Buddy Core:       http://127.0.0.1:8010
Memory dashboard: http://127.0.0.1:8010/memory
XiaoZhi OTA:      http://<host-lan-ip>:8003/xiaozhi/ota/
XiaoZhi WebSocket: ws://<host-lan-ip>:8000/xiaozhi/v1/
XiaoZhi health:   http://127.0.0.1:8003/health
Sessions:         http://127.0.0.1:8003/debug/sessions
```

Check or stop the owned runtime:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_local_demo_status.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_local_demo.ps1
```

## Local Model Interfaces

Local deployment remains configuration-driven. The current hosted Qwen ASR/TTS providers are selected by the production overlay, but these XiaoZhi provider boundaries remain in the repository:

- Local ASR: FunASR, sherpa-onnx, and Vosk.
- ASR server: FunASR WebSocket server.
- Streaming ASR: retained native streaming providers.
- Local or self-hosted LLM: point Buddy Core `OPENAI_BASE_URL` at an OpenAI-compatible server; XiaoZhi also retains Ollama and Xinference adapters.
- Local TTS server: FishSpeech, GPT-SoVITS v2/v3, PaddleSpeech, and the custom TTS adapter.

Provider dependencies and model files are installed separately. Switching a provider requires updating the validated XiaoZhi configuration overlay; it does not require replacing the speech pipeline.

## Tests

Run the complete suite:

```powershell
conda run -n xiaozhi-env python -m pytest -q
```

Run provenance and secret checks:

```powershell
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance verify
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance scan-secrets
```

Run the same-socket software voice loop after the services are running:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_xiaozhi_fusion.ps1
```

## Documentation

- [Fused XiaoZhi Core runbook](docs/runbooks/buddy-xiaozhi-core-fusion.md)
- [Buddy Core configuration](docs/buddy-core-configuration.md)
- [Memory dashboard](docs/runbooks/memory-dashboard.md)
- [Buddy Core naming](docs/buddy-core-and-buddy-brain.md)
- [Fusion patch inventory](docs/third-party/xiaozhi-core-patch-inventory.md)
- [Fusion acceptance and cleanup record](docs/status/2026-07-18-buddy-xiaozhi-fusion-acceptance.md)
- [Archived Gateway v0.1-v0.5 runbook](docs/archive/buddy-device-gateway-v0.1-v0.5.md)

## Licensing

The imported XiaoZhi ESP32 Server runtime is governed by the copied MIT license at [third_party/xiaozhi-esp32-server/LICENSE](third_party/xiaozhi-esp32-server/LICENSE). Repository-level attribution is in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Pinned origin and file-level provenance are recorded in:

- `third_party/xiaozhi-esp32-server/UPSTREAM.json`
- `third_party/xiaozhi-esp32-server/SOURCE_MANIFEST.json`
- `third_party/xiaozhi-esp32-server/PATCH_MANIFEST.json`

The repository does not currently declare a separate top-level license for original AI Buddy code.
