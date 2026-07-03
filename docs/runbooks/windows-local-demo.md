# Windows Local Demo Runbook

This runbook is the supported path for the current LAN demo phase.

## Scope

- Platform: Windows PowerShell.
- Conda environment: `xiaozhi-env`.
- Buddy Core port: `8010`.
- XiaoZhi WebSocket port: `8000`.
- XiaoZhi OTA/HTTP port: `8003`.
- ESP32 firmware remains XiaoZhi-compatible.

## Preflight

Open PowerShell from the repository root:

```powershell
cd "<repo-root>"
conda activate xiaozhi-env
```

Run the test suite when validating changes:

```powershell
conda run -n xiaozhi-env python -m pytest -q
```

## Back Up Demo Data

Run this before memory reset, config rendering, or a hardware demo:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\backup_local_demo_data.ps1
```

The script copies these files when present:

- `data\buddy_memory.db`
- `.run\xiaozhi-esp32-server\main\xiaozhi-server\data\.config.yaml`

## Prepare XiaoZhi Runtime

If `.run\xiaozhi-esp32-server` is missing or was overwritten, prepare it again:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_xiaozhi_server.ps1
```

This also reapplies the runtime patch that forwards `device_id`, `client_id`, and `session_id` into Buddy Core metadata.

## Render Config

Let the script auto-detect the LAN IP:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\render_xiaozhi_config.ps1
```

If auto-detection picks the wrong adapter, pass the WiFi/LAN IP explicitly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\render_xiaozhi_config.ps1 -HostIp 192.168.0.101
```

Print the URLs for the current host:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\print_local_demo_urls.ps1
```

## Start Services

Terminal A:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_core.ps1
```

Terminal B:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_xiaozhi_server.ps1
```

Terminal C, optional live XiaoZhi log:

```powershell
Get-Content -LiteralPath ".\.run\xiaozhi-esp32-server\main\xiaozhi-server\tmp\server.log" -Wait -Tail 80
```

## Check Status

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_local_demo_status.ps1
```

The important checks are:

- `8010` is listening for Buddy Core.
- `8000` is listening for XiaoZhi WebSocket.
- `8003` is listening for XiaoZhi OTA/HTTP.
- `.config.yaml` contains `BuddyCoreLLM`.
- `.config.yaml` contains `forward_device_metadata: true`.
- Runtime patch markers exist in XiaoZhi provider and connection files.

## Software Smoke Test

With Buddy Core running:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_chat.ps1
```

Expected:

- JSON response object is `chat.completion`.
- `choices[0].message.content` contains a short Buddy reply.

To verify that two debug devices map to separate profiles and memory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_two_devices.ps1
```

Then open the two printed memory URLs. They should show different `Device`, `Client ID`, and `User ID` values.

More details: `docs/runbooks/memory-dashboard.md`.

## Hardware Test

1. Put the computer and ESP32 on the same WiFi.
2. Set the ESP32 OTA URL to the printed `XiaoZhi OTA URL`.
3. Restart or reconnect the ESP32.
4. Confirm `tmp\server.log` shows an OTA request.
5. Confirm `tmp\server.log` shows a WebSocket connection with `device-id`.
6. Speak one short sentence.
7. Confirm logs show ASR text, Buddy Core response, and TTS output.
8. Open memory dashboard:

```text
http://127.0.0.1:8010/memory
```

For the current test device, the URL may look like:

```text
http://127.0.0.1:8010/memory?device_id=fc%3A01%3A2c%3Acf%3A17%3A54
```

## Stop Services

To stop the local demo listeners on ports `8000`, `8003`, and `8010`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_local_demo.ps1
```

Preview without stopping:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_local_demo.ps1 -WhatIf
```

## Known Non-Blocking Issues

- Some XiaoZhi logs can display mojibake in PowerShell. Use timestamps, port numbers, `device-id`, and English markers to confirm the chain.
- Weather plugin authentication errors do not block the voice demo.
- Voiceprint warnings do not block the voice demo.
