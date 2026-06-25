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

Use Python 3.10 or newer. On Windows, `py -3.10` is recommended if another Python version is the default.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env` and set `OPENAI_API_KEY` from your local environment. Do not commit `.env`.

## Run

```powershell
uvicorn buddy_brain.app:app --host 0.0.0.0 --port 8010
```

## Test

```powershell
python -m pytest -v
```

On Windows hosts where `python` is not 3.10+, run `py -3.10 -m pytest -v`.

## Smoke Test

Start the server, then run:

```powershell
.\scripts\smoke_chat.ps1
```

Expected response contains a `choices[0].message.content` value from Buddy.

## Local Model Switch

Use the same API surface and change environment values:

```dotenv
OPENAI_BASE_URL=http://127.0.0.1:8001/v1
OPENAI_API_KEY=not-needed
MODEL_NAME=local-model-name
```

## XiaoZhi Server Handoff

Point the XiaoZhi server LLM provider at:

```text
base_url: http://<host-lan-ip>:8010/v1
api_key: not-needed-by-buddy-brain
model: deepseek-v4-flash
```

Keep XiaoZhi server memory disabled for this demo. Buddy Brain owns profile and memory persistence.
