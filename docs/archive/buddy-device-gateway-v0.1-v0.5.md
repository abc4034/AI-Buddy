# Buddy Device Gateway v0.1-v0.5 Runbook

> Archived: v0.1-v0.5 was superseded by the fused XiaoZhi Core runtime. The implementation remains available in Git history on `codex/buddy-device-gateway-v0.5-voice-loop`; do not use these commands for the current runtime.

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

Buddy Device Gateway v0.3 adds audio ingress debugging:

- `GET /xiaozhi/ota/` is a XiaoZhi Server style text health check.
- OTA `POST /xiaozhi/ota/` prefers XiaoZhi version headers before body fields.
- WebSocket binary audio is stored as Opus debug frames.
- Plain binary WebSocket payloads are treated as raw Opus frames.
- XiaoZhi/MQTT-style 16-byte audio headers are accepted only when their length fields match the payload.
- Captured Opus frames can be decoded to WAV for inspection.
- Gateway still does not run ASR, call Buddy Core from audio, run TTS, or send audio replies to ESP32.

Buddy Device Gateway v0.4 adds ASR text-loop debugging:

- Gateway has a XiaoZhi-inspired ASR provider boundary.
- Implemented providers: `qwen_chat_audio`, for Alibaba Bailian Qwen3-ASR chat/audio requests, and `http_file`, for generic OpenAI-style `/audio/transcriptions` multipart APIs.
- Planned provider slots: `local_model`, `asr_server`, and `streaming_asr`. They return clear not-implemented errors in v0.4.
- `listen stop` triggers ASR for the current turn. If `listen stop` is missing, WebSocket disconnect triggers the last unfinished turn.
- The transcript is sent to Buddy Core with `source: buddy_gateway_asr`, plus `asr_provider` and `asr_turn_id` metadata.
- `SendSttToDevice` is a config switch. It is off by default; when enabled, Gateway sends a `stt` text message to the ESP32.
- Gateway still does not run TTS or send audio replies to ESP32.

Buddy Device Gateway v0.5 adds the first complete voice-loop path:

- Gateway has a XiaoZhi-inspired TTS provider boundary.
- Implemented provider: `dashscope_qwen_http`, for Alibaba Bailian DashScope Qwen-TTS HTTP requests.
- Planned provider slots: `local_model`, `tts_server`, and `streaming_tts`. They return clear not-implemented errors in v0.5.
- After ASR and Buddy Core succeed, Gateway synthesizes the full assistant reply with `qwen3-tts-instruct-flash`.
- Returned TTS audio is normalized to `16kHz / mono / 16-bit PCM`, encoded into `60ms` Opus frames, and sent to ESP32 as raw WebSocket bytes.
- Gateway sends `tts start`, `tts sentence_start`, Opus bytes, then `tts stop`.
- Explicit `listen stop` keeps the socket open through this sequence in tests. In observed real ESP32 `auto` mode, ASR is reached only during disconnect, so the socket is already closed and Gateway cannot return TTS on it.
- `abort` stops current playback at the Gateway level and sends `tts stop`.

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

For v0.4 ASR text-loop testing with Alibaba Bailian Qwen3-ASR, configure the ASR provider before starting Gateway. The PowerShell script hydrates the current process from Windows user environment variables, so this works even if the terminal was already open:

```powershell
[Environment]::SetEnvironmentVariable("ASR_PROVIDER", "qwen_chat_audio", "User")
[Environment]::SetEnvironmentVariable("ASR_HTTP_URL", "https://<asr-host>/compatible-mode/v1", "User")
[Environment]::SetEnvironmentVariable("ASR_MODEL", "qwen3-asr-flash-2025-09-08", "User")
[Environment]::SetEnvironmentVariable("ASR_API_KEY", "<your-asr-api-key>", "User")
```

`qwen3-asr-flash-2025-09-08` is the dated model alias configured for this Bailian workspace and verified in the local smoke test. Public Bailian examples may show `qwen3-asr-flash`; keep the workspace alias if your API call succeeds.

Use `ASR_PROVIDER=http_file` only for providers that expose an OpenAI-style `/audio/transcriptions` multipart endpoint.

For v0.5 TTS reply testing with Alibaba Bailian Qwen-TTS, configure the TTS provider before starting Gateway:

```powershell
[Environment]::SetEnvironmentVariable("TTS_PROVIDER", "dashscope_qwen_http", "User")
[Environment]::SetEnvironmentVariable("TTS_HTTP_URL", "https://<tts-host>/api/v1", "User")
[Environment]::SetEnvironmentVariable("TTS_MODEL", "qwen3-tts-instruct-flash", "User")
[Environment]::SetEnvironmentVariable("TTS_API_KEY", "<your-tts-api-key>", "User")
[Environment]::SetEnvironmentVariable("TTS_VOICE", "Cherry", "User")
[Environment]::SetEnvironmentVariable("TTS_LANGUAGE", "auto", "User")
```

`qwen3-tts-instruct-flash` is the first v0.5 model. Do not use `qwen3-tts-vd-2026-01-26` in v0.5 unless a Voice Design `voice_id` has already been created and selected.

Then start Buddy Core and Gateway:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_core.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_gateway.ps1 -AdvertiseHost 192.168.0.101
```

Equivalent explicit startup, without relying on environment variables except for the key:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_gateway.ps1 -AdvertiseHost 192.168.0.101 -AsrProvider qwen_chat_audio -AsrHttpUrl https://<asr-host>/compatible-mode/v1 -AsrModel qwen3-asr-flash-2025-09-08
```

Equivalent explicit v0.5 startup, without passing API keys on the command line:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_gateway.ps1 -AdvertiseHost 192.168.0.101 -AsrProvider qwen_chat_audio -AsrHttpUrl https://<asr-host>/compatible-mode/v1 -AsrModel qwen3-asr-flash-2025-09-08 -TtsProvider dashscope_qwen_http -TtsHttpUrl https://<tts-host>/api/v1 -TtsModel qwen3-tts-instruct-flash -TtsVoice Cherry -TtsLanguage auto
```

If `-AdvertiseHost` is omitted, the script tries to pick a private LAN IPv4 address and prefer physical WiFi/LAN adapters over virtual adapters. For hardware testing, passing the known host IP explicitly is still clearer.

To compare it with XiaoZhi Server on alternate ports:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_gateway.ps1 -BindHost 127.0.0.1 -HttpPort 18003 -WebSocketPort 18000 -AdvertiseHost 127.0.0.1 -BuddyCoreBaseUrl http://127.0.0.1:8010
```

## HTTP Checks

OTA health text:

```powershell
Invoke-WebRequest http://127.0.0.1:8003/xiaozhi/ota/ -UseBasicParsing
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

Recent audio sessions:

```powershell
Invoke-RestMethod http://127.0.0.1:8003/debug/audio/sessions
```

Current ASR provider:

```powershell
Invoke-RestMethod http://127.0.0.1:8003/debug/asr/providers
```

Current TTS provider:

```powershell
Invoke-RestMethod http://127.0.0.1:8003/debug/tts/providers
```

Decode captured Opus frames for a known session:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8003/debug/sessions/<session-id>/decode-audio
```

Open or download the decoded WAV after decoding:

```text
http://127.0.0.1:8003/debug/sessions/<session-id>/audio.wav
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

For v0.4 ASR text-loop testing, use the ASR smoke script after the ESP32 has sent at least one audio frame:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_gateway_asr_text_loop.ps1
```

The script picks the latest audio session, calls `/debug/sessions/{session_id}/transcribe-audio`, and prints the transcript, Buddy Core reply, and Memory URL.

For v0.5 voice-loop diagnostics, use the voice smoke script after an explicit `listen stop` test turn:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_gateway_voice_loop.ps1
```

The script checks that the latest ASR and TTS turns are successful and share the same ASR turn ID, then prints transcript, assistant reply, TTS provider, outgoing Opus frame count, and Memory URL.

For v0.3 audio capture testing, use the audio smoke script after the ESP32 has sent at least one audio frame:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_gateway_audio_capture.ps1
```

The script prints the selected session, frame counts, decode errors, WAV path, and audio URL.

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

For v0.3 audio capture testing:

1. Keep only Buddy Device Gateway on `8000` and `8003`.
2. Trigger listen on the ESP32 and speak once.
3. Confirm `/debug/audio/sessions` shows the hardware `device-id` and a nonzero `opus_frame_count`.
4. Run `smoke_gateway_audio_capture.ps1`.
5. Open the printed WAV path or audio URL and confirm it is a valid captured audio file.

For v0.4 ASR text-loop testing:

1. Keep Buddy Core running on `8010`.
2. Configure `ASR_PROVIDER=qwen_chat_audio`, `ASR_HTTP_URL`, `ASR_MODEL`, and `ASR_API_KEY`.
3. Trigger listen on the ESP32 and speak once.
4. If the device sends `listen stop`, Gateway auto-runs ASR. If not, disconnect or run the smoke script to trigger manually.
5. Confirm `/debug/sessions` shows an `asr_turns` item with `status: ok`, `transcript`, and `assistant_text`.
6. Open the printed Memory URL and confirm the transcript appears under the hardware `device-id`.

The ASR smoke script requires the selected session to exist in both `/debug/sessions` and `/debug/audio/sessions`, and it fails on `skipped`, `no_text`, `error`, or `buddy_core_error` results instead of printing a false success.

For v0.5 voice-loop diagnostics:

1. Keep Buddy Core running on `8010`.
2. Configure ASR and TTS environment variables.
3. Trigger an explicit `listen stop` test turn on the ESP32 and speak once.
4. Confirm the test path keeps the WebSocket open through the returned TTS audio.
5. Confirm `/debug/sessions` shows a latest `asr_turns` item with `status: ok` and a latest `tts_turns` item with `status: ok`.
6. Run `smoke_gateway_voice_loop.ps1`.
7. Open the printed Memory URL and confirm the transcript appears under the hardware `device-id`.

Expected limitation: the device should not hear a Buddy audio reply in v0.1, v0.2, v0.3, or v0.4. In v0.5, automated explicit `listen stop` coverage proves that TTS control messages and Opus frames are sent over an open socket; physical ESP32 speaker playback remains unverified. Observed real ESP32 `auto` mode still finalizes ASR only at disconnect. Because that WebSocket is already closed, Gateway cannot return TTS on the same socket, so a real auto-mode hardware voice loop is not yet available.

## Automated Tests

Gateway tests:

```powershell
conda run -n xiaozhi-env python -m pytest tests/test_gateway.py tests/test_gateway_audio.py tests/test_gateway_asr.py tests/test_gateway_tts.py tests/test_gateway_core_client.py -q
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

- v0.6: split Buddy Core replies into sentence-level TTS turns or upgrade to streaming TTS for lower latency.
- Later: implement `local_model`, `asr_server`, `streaming_asr`, `local_model` TTS, `tts_server`, streaming TTS, and VAD provider paths as needed.
- Keep ESP32 XiaoZhi firmware compatibility as the default constraint unless the firmware plan changes.
