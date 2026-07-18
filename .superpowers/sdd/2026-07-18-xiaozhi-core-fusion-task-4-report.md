# Task 4 Report: Validate XiaoZhi Qwen ASR

## Native Compatibility Decision

The native `qwen3_asr_flash` provider was evaluated first against the configured endpoint, model, key, and 30-second timeout. The DashScope-native request shape reached the service and returned HTTP `404`. This is concrete endpoint-shape incompatibility, not an authentication, quota, DNS, network, or local-configuration failure.

The compatibility-authorized selection is `buddy_qwen`. It uses only the verified OpenAI-compatible Qwen chat-completions request and transcript parsing path. It does not copy VAD, buffering, WAV finalization, session state, or turn handling. The rendered ignored configuration selects `type: buddy_qwen`; the environment-provided provider name is retained as configuration provenance.

## TDD And Live Results

- Red: provider-error module missing; then native timeout/status metadata and fallback-provider tests failed before implementation.
- Green: compatibility contract suite passed `18 passed, 1 xfailed`.
- The expected xfail records the native compatibility gate returning HTTP `404`.
- The selected fallback passed the live provider transcription test using the configured endpoint and model.
- Configuration and provenance tests passed `23 passed`.
- Upstream flat loader resolved `core.providers.asr.buddy_qwen`.

## Provenance

Recorded runtime changes:

- `core/buddy/__init__.py`
- `core/buddy/provider_errors.py`
- `core/providers/asr/qwen3_asr_flash.py`
- `core/providers/asr/buddy_qwen.py`

`provenance verify` and `scan-secrets` both passed. Runtime credentials are read Process-then-User and rendered only to ignored `xiaozhi_server/data/.config.yaml`; they are not accepted as command-line arguments or printed by the renderer.

## Commit

`feat: validate xiaozhi qwen asr`

## Pending Hardware Checkpoint

`scripts/smoke_xiaozhi_asr.ps1` is implemented and checks the pinned runtime log for a real device ID and a non-empty transcript. Real ESP32 speech validation remains pending for the user after implementation and review.
