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
- Does not require speaker output on the current hardware.

## Docs

For the current demo phase, prefer the Windows PowerShell + conda `xiaozhi-env` path.

- Windows local demo runbook: [docs/runbooks/windows-local-demo.md](docs/runbooks/windows-local-demo.md)
- Buddy Device Gateway v0.1: [docs/runbooks/buddy-device-gateway-v0.1.md](docs/runbooks/buddy-device-gateway-v0.1.md)
- Buddy Core configuration: [docs/buddy-core-configuration.md](docs/buddy-core-configuration.md)
- Buddy Core vs old Buddy Brain naming: [docs/buddy-core-and-buddy-brain.md](docs/buddy-core-and-buddy-brain.md)
- Memory dashboard: [docs/runbooks/memory-dashboard.md](docs/runbooks/memory-dashboard.md)
- Stabilization roadmap: [docs/superpowers/plans/2026-07-03-buddy-core-stabilization-roadmap.md](docs/superpowers/plans/2026-07-03-buddy-core-stabilization-roadmap.md)

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
