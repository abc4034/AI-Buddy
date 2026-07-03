# Buddy Device Gateway v0.1/v0.2 Runbook

This runbook covers the first replacement steps for XiaoZhi Server.

## Scope

Buddy Device Gateway v0.1 is the protocol skeleton:

- HTTP OTA runs on `8003`.
- WebSocket runs on `8000`.
- The OTA response points the ESP32 to `ws://<host-ip>:8000/xiaozhi/v1/`.
- The WebSocket endpoint records `device-id`, `client-id`, text messages, and audio byte counters.
- It does not decode Opus.
- It does not call ASR, Buddy Core, or TTS.
- It does not produce audio replies.

The success signal is that real hardware can reach the new Gateway and the Gateway can show OTA, WebSocket, `hello`, `listen`, and audio byte events.

Buddy Device Gateway v0.2 adds a text-level debug loop:

- Gateway can call Buddy Core `/v1/chat/completions` through HTTP.
- Debug text carries `device_id`, `client_id`, `session_id`, and `source: buddy_gateway_debug` in metadata.
- HTTP debug clients can inject text with `POST /debug/sessions/{session_id}/inject-text`.
- WebSocket debug clients can send `{"type":"debug_text","text":"..."}` and receive `debug_text_result`.
- Real ESP32 clients still do not receive `stt`, `tts`, or audio replies from the Gateway.
- Gateway keeps only recent debug turns in memory; long-term persistence remains in Buddy Core memory.

## Start Gateway

Stop XiaoZhi Server first because the Gateway uses the same `8000` and `8003` ports:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_local_demo.ps1 -Ports 8000,8003
```

Start the Gateway from the repository root. Pass the computer WiFi/LAN IP so the OTA response advertises an address the ESP32 can reach:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_gateway.ps1 -AdvertiseHost 192.168.0.101
```

For v0.2 text-loop testing, start Buddy Core in another terminal first:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_core.ps1
```

Then start the Gateway and point it at Buddy Core:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_gateway.ps1 -AdvertiseHost 192.168.0.101 -BuddyCoreBaseUrl http://127.0.0.1:8010
```

`-BuddyCoreBaseUrl` should be the Buddy Core service root, such as `http://127.0.0.1:8010`, not a URL ending in `/v1`.

If `-AdvertiseHost` is omitted, the script tries to pick a private LAN IPv4 address and prefer physical WiFi/LAN adapters over virtual adapters. For hardware testing, passing the known host IP explicitly is still clearer.

To compare it with XiaoZhi Server on alternate ports:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_gateway.ps1 -BindHost 127.0.0.1 -HttpPort 18003 -WebSocketPort 18000 -AdvertiseHost 127.0.0.1 -BuddyCoreBaseUrl http://127.0.0.1:8010
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

Inject debug text into a known session:

```powershell
$body = @{ text = "I like apples" } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8003/debug/sessions/<session-id>/inject-text -Body $body -ContentType "application/json"
```

Or use the smoke script, which picks the latest session and prints the Buddy Core reply plus Memory panel URL:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_gateway_text_loop.ps1 -Text "I like apples"
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

For v0.2 text-loop testing:

1. Keep Buddy Core running on `8010`.
2. Keep the ESP32 connected to the Gateway.
3. Run `smoke_gateway_text_loop.ps1`.
4. Confirm the script prints an assistant reply from Buddy Core.
5. Open the printed Memory URL and confirm the episode appears under the hardware `device-id`.

Expected limitation: the device should not hear a Buddy reply in v0.1 or v0.2.

## Automated Tests

Gateway tests:

```powershell
conda run -n xiaozhi-env python -m pytest tests/test_gateway.py tests/test_gateway_core_client.py -q
```

Script tests:

```powershell
conda run -n xiaozhi-env python -m pytest tests/test_xiaozhi_scripts.py -q
```

Full regression:

```powershell
conda run -n xiaozhi-env python -m pytest -q
```

## Next Steps

- v0.3: add Opus decode, ASR, TTS, and binary audio reply handling.
- Keep ESP32 XiaoZhi firmware compatibility as the default constraint unless the firmware plan changes.
