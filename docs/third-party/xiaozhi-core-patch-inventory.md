# XiaoZhi Core Patch Inventory

Pinned commit: `8ec585102711516bf214b262f7d87bc04f9597e2`

No speech-core runtime files modified at import checkpoint.

Security-only default-config patch: `config.yaml` blanks the upstream shared weather API key. Its exact before/after hashes are maintained in `third_party/xiaozhi-esp32-server/PATCH_MANIFEST.json`.

Task 4 ASR compatibility patches:

- `core/buddy/__init__.py` and `core/buddy/provider_errors.py` add the typed provider-failure contract without changing ASR lifecycle behavior.
- `core/providers/asr/qwen3_asr_flash.py` passes endpoint and timeout to the native SDK and preserves typed failures for the native compatibility gate.
- `core/providers/asr/buddy_qwen.py` is the narrow, compatibility-authorized OpenAI chat-completions fallback. The configured endpoint returned HTTP `404` to the native DashScope request shape; no VAD, buffering, WAV finalization, session, or turn code was copied.
