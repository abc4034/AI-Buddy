# AI Buddy

Local Buddy Brain service for an ESP32-S3 XiaoZhi-compatible English companion education demo.

## First Demo Scope

- Runs locally on Windows or Ubuntu 22.
- Exposes an OpenAI-compatible `/v1/chat/completions` endpoint.
- Uses DeepSeek through an OpenAI-compatible client by default.
- Stores long-term child learning memory in `data/buddy_memory.db`.
- Keeps local model deployment available by changing environment variables.
- Does not require speaker output on the current hardware.

## Setup

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
```

## Run

Windows PowerShell:

```powershell
uvicorn buddy_brain.app:app --host 0.0.0.0 --port 8010
```

Ubuntu 22.04:

```bash
source .venv/bin/activate
uvicorn buddy_brain.app:app --host 0.0.0.0 --port 8010
```

## Test

```powershell
py -3.10 -m pytest -v
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

For this first local bridge demo, use the pinned Task 2 host `192.168.2.9` so the Buddy Brain, WebSocket, and OTA URLs all stay aligned with the current scripts.

Point the XiaoZhi server LLM provider at:

```text
base_url: http://192.168.2.9:8010/v1
api_key: local
model: deepseek-v4-flash
```

Keep XiaoZhi server memory disabled for this demo. Buddy Brain owns profile and memory persistence.

## XiaoZhi Local Bridge

This phase keeps the ESP32 firmware and XiaoZhi device protocol, but routes XiaoZhi server LLM calls to Buddy Brain.

Local URLs for the current Windows host:

```text
Buddy Brain: http://192.168.2.9:8010
Buddy Brain OpenAI base_url: http://192.168.2.9:8010/v1
XiaoZhi WebSocket: ws://192.168.2.9:8000/xiaozhi/v1/
XiaoZhi OTA: http://192.168.2.9:8003/xiaozhi/ota/
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
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\render_xiaozhi_config.ps1 -HostIp 192.168.2.9
```

Start Buddy Brain in terminal A:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_brain.ps1
```

Smoke test Buddy Brain in terminal B:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_chat.ps1
```

Start XiaoZhi server in terminal C after its conda environment and dependencies are installed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_xiaozhi_server.ps1
```

The generated XiaoZhi config sets:

```yaml
selected_module:
  LLM: BuddyBrainLLM
  Memory: nomem
  Intent: nointent
```

Hardware routing pause point:

- Do not flash firmware until Buddy Brain and XiaoZhi server both start successfully.
- The current ESP32 firmware still uses `https://api.tenclass.net/xiaozhi/ota/`.
- If no runtime OTA override is available, firmware must be rebuilt for `bread-compact-wifi-lcd` with `CONFIG_OTA_URL=http://192.168.2.9:8003/xiaozhi/ota/`.
- When flashing is needed, stop and ask the user to plug in USB and press `BOOT` / `RESET`.
