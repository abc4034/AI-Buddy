# Buddy Device Gateway v0.1 Runbook

This runbook covers the first replacement step for XiaoZhi Server.

## Scope

Buddy Device Gateway v0.1 is only a protocol skeleton:

- HTTP OTA runs on `8003`.
- WebSocket runs on `8000`.
- The OTA response points the ESP32 to `ws://<host-ip>:8000/xiaozhi/v1/`.
- The WebSocket endpoint records `device-id`, `client-id`, text messages, and audio byte counters.
- It does not decode Opus.
- It does not call ASR, Buddy Core, or TTS.
- It does not produce audio replies.

The success signal is that real hardware can reach the new Gateway and the Gateway can show OTA, WebSocket, `hello`, `listen`, and audio byte events.

## Start Gateway

Stop XiaoZhi Server first because the Gateway uses the same `8000` and `8003` ports:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_local_demo.ps1 -Ports 8000,8003
```

Start the Gateway from the repository root. Pass the computer WiFi/LAN IP so the OTA response advertises an address the ESP32 can reach:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_gateway.ps1 -AdvertiseHost 192.168.0.101
```

If `-AdvertiseHost` is omitted, the script tries to pick a private LAN IPv4 address and prefer physical WiFi/LAN adapters over virtual adapters. For hardware testing, passing the known host IP explicitly is still clearer.

To compare it with XiaoZhi Server on alternate ports:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_gateway.ps1 -BindHost 127.0.0.1 -HttpPort 18003 -WebSocketPort 18000 -AdvertiseHost 127.0.0.1
```

## HTTP Checks

OTA JSON check:

```powershell
Invoke-RestMethod http://127.0.0.1:8003/xiaozhi/ota/
```

JSON status:

```powershell
Invoke-RestMethod http://127.0.0.1:8003/health
```

Simulated OTA POST:

```powershell
$headers = @{
  "device-id" = "debug-device"
  "client-id" = "debug-client"
}
$body = @{
  board = @{ type = "esp32-s3" }
  version = "debug"
} | ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8003/xiaozhi/ota/ -Headers $headers -Body $body -ContentType "application/json"
```

Recent sessions:

```powershell
Invoke-RestMethod http://127.0.0.1:8003/debug/sessions
```

## Hardware Check

1. Put the computer and ESP32 on the same WiFi.
2. Stop XiaoZhi Server on `8000` and `8003`.
3. Start Buddy Device Gateway with `-AdvertiseHost <host-ip>`.
4. Set ESP32 OTA URL to:

```text
http://<host-ip>:8003/xiaozhi/ota/
```

5. Restart or reconnect the ESP32.
6. Confirm Gateway logs show an OTA request with `device-id` and `client-id`.
7. Confirm Gateway logs show a WebSocket connection on `/xiaozhi/v1/`.
8. Speak once or trigger listen on the device.
9. Confirm `/debug/sessions` shows `hello`, `listen`, and `audio_frame_count` / `audio_byte_count`.

Expected limitation: the device should not hear a Buddy reply in v0.1.

## Automated Tests

Run:

```powershell
conda run -n xiaozhi-env python -m pytest tests/test_gateway.py -q
```

Full regression:

```powershell
conda run -n xiaozhi-env python -m pytest -q
```

## Next Steps

- v0.2: add a text-level loop from Gateway to Buddy Core for debug clients.
- v0.3: add Opus decode, ASR, TTS, and binary audio reply handling.
- Keep ESP32 XiaoZhi firmware compatibility as the default constraint unless the firmware plan changes.
