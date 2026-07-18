# Buddy XiaoZhi Core Fusion

## Architecture

The fused runtime uses two Windows processes. Buddy Core owns identity, persona, memory, and LLM responses on port `8010`. The vendored XiaoZhi runtime owns the native WebSocket, VAD, ASR, TTS queue, Opus output, abort behavior, OTA, and HTTP endpoints on ports `8000` and `8003`.

v0.5 Buddy Gateway remains in branch history only until the cleanup acceptance gate. Do not start it alongside XiaoZhi because both use the device ports.

## Start

Set the named ASR and TTS provider variables in Windows User scope before starting. The launcher copies only empty Process-scope values for `ASR_PROVIDER`, `ASR_HTTP_URL`, `ASR_MODEL`, `ASR_API_KEY`, `ASR_TIMEOUT_SECONDS`, `TTS_PROVIDER`, `TTS_HTTP_URL`, `TTS_MODEL`, `TTS_API_KEY`, `TTS_VOICE`, `TTS_LANGUAGE`, and `TTS_TIMEOUT_SECONDS`. Keys are passed through environment only.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_fusion.ps1 -AdvertiseHost <host-lan-ip> -CondaEnv xiaozhi-env
```

The ESP32 OTA URL is:

```text
http://<host-lan-ip>:8003/xiaozhi/ota/
```

The WebSocket URL is `ws://<host-lan-ip>:8000/xiaozhi/v1/`.

## Validate

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_local_demo_status.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_xiaozhi_fusion.ps1
conda run -n xiaozhi-env python -m pytest tests/xiaozhi_fusion/test_voice_loop.py -q
```

Useful endpoints are `http://127.0.0.1:8010/health`, `http://127.0.0.1:8003/health`, `http://127.0.0.1:8003/debug/sessions`, `http://127.0.0.1:8003/debug/asr/providers`, and `http://127.0.0.1:8003/debug/tts/providers`.

For a production software voice loop after the fused runtime is running, set the non-secret test switch in the current shell and run the focused test:

```powershell
$env:RUN_XIAOZHI_VOICE_LOOP = "1"
conda run -n xiaozhi-env python -m pytest tests/xiaozhi_fusion/test_voice_loop.py -q
```

It sends `hello`, manual `listen`, valid Opus input, and checks `stt` (when emitted), `tts start`, `tts sentence_start`, binary Opus, and `tts stop` on one socket. It also checks that Buddy Memory contains the device and one episode.

Hardware acceptance requires the same sequence on the ESP32 with audible returned Opus audio, correct device identity in Buddy Memory, and no v0.5 Gateway process listening on `8000` or `8003`.

## Stop And Roll Back

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_local_demo.ps1
```

The stop command relies on the owned `tmp/runtime/buddy-fusion.json` state file. It validates listener identity, stops XiaoZhi first, verifies `8000/8003` have released, then stops Buddy Core. It refuses unknown owners instead of killing an existing user service.

Rollback remains the v0.5 backup workflow:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\backup_v05_runtime.ps1
```

Restore only after reviewing the backup manifest and using the restore command printed by that workflow.
