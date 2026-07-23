# Buddy XiaoZhi Fusion Acceptance And Cleanup

## Result

The supported hardware runtime is the two-process Buddy Core and fused XiaoZhi Core architecture. Hardware acceptance was completed before the custom Buddy Device Gateway implementation from v0.1-v0.5 was removed from packaging and runtime startup.

Hardware acceptance completed before cleanup with a real ESP32 device:

- OTA and `/xiaozhi/v1/` WebSocket connection succeeded on ports `8003` and `8000`.
- The server received the real `device-id` and `client-id`.
- Native XiaoZhi VAD/ASR produced non-empty transcripts.
- Buddy Core produced replies and persisted device-scoped memory.
- Native XiaoZhi TTS returned audible Opus audio to the ESP32.
- Client `abort` events stopped playback without stopping either service.

## Replacement Coverage

The deleted Gateway test categories are covered by the fused runtime suite:

| Retired Gateway responsibility | Fused coverage |
| --- | --- |
| OTA, WebSocket listeners, and process ownership | `tests/xiaozhi_fusion/test_upstream_boot.py`, `test_windows_process_lifecycle.py` |
| Opus encode/decode and complete voice ordering | `tests/xiaozhi_fusion/test_voice_loop.py` |
| ASR configuration, success, silence, and provider failures | `tests/xiaozhi_fusion/test_asr_provider_compatibility.py` |
| Device metadata and concurrent-session isolation | `tests/xiaozhi_fusion/test_session_context.py`, `test_buddy_core_provider.py` |
| TTS synthesis and native queue ownership | `tests/xiaozhi_fusion/test_qwen_tts_provider.py` |
| Abort and next-turn recovery | `tests/xiaozhi_fusion/test_provider_failure_recovery.py` |
| Windows launch, status, stop, and smoke scripts | `tests/test_xiaozhi_scripts.py` |
| Upstream source, license, patch, and secret provenance | `tests/xiaozhi_fusion/test_provenance.py` |

## Retained Extension Interfaces

Cleanup intentionally retains XiaoZhi's provider system. Local ASR providers include FunASR, sherpa-onnx, and Vosk; FunASR server and streaming ASR adapters also remain. Buddy Core can use a local OpenAI-compatible LLM, while XiaoZhi retains Ollama and Xinference adapters. FishSpeech, GPT-SoVITS, PaddleSpeech, and custom TTS server adapters remain available.

These interfaces are not selected by the current production overlay and may require additional model files or dependencies.

## Licensing

The repository-level third-party notice remains at `THIRD_PARTY_NOTICES.md`. The copied upstream MIT license and provenance records remain under `third_party/xiaozhi-esp32-server/`. No XiaoZhi provider, model, asset, license, or provenance file was removed by this cleanup.

The repository does not currently include a separate root license for original AI Buddy code.
