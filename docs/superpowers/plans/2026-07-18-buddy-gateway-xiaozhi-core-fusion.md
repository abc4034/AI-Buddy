# Buddy Gateway v0.6 XiaoZhi Core Fusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every task has a mandatory independent review gate; do not start the next task until the reviewer reports no open findings.

**Goal:** Replace the v0.5 custom Buddy Gateway speech runtime with the authenticated XiaoZhi Server runtime while retaining Buddy Core as the sole owner of child identity, persona, memory, and LLM behavior.

**Architecture:** Vendor the complete XiaoZhi runtime pinned at commit `8ec585102711516bf214b262f7d87bc04f9597e2`. Its original `app.py` owns WebSocket `8000`, HTTP/OTA `8003`, VAD, ASR invocation, TTS queues, Opus sending, abort, and connection cleanup; Buddy Core remains a separate process on `8010` and is reached through a native XiaoZhi LLM provider.

**Tech Stack:** Python 3.10, XiaoZhi Server pinned runtime, FastAPI Buddy Core, `websockets==14.2`, `openai==2.8.1`, `httpx==0.28.1`, `opuslib_next==1.1.5`, PowerShell, conda `xiaozhi-env`, pytest.

## Global Constraints

- Work only on `codex/buddy-gateway-v0.6-xiaozhi-core-fusion`, based on v0.5 commit `22e4712814dfb19f1ecea9bd0e6bfbd24c057ac5`.
- Upstream source is `https://github.com/xinnan-tech/xiaozhi-esp32-server.git` at commit `8ec585102711516bf214b262f7d87bc04f9597e2`, tree `7b96e40bf6541e9b94bdf7c53de9266e3590464d`.
- Do not use the existing `.run` snapshot as source material and do not download an unpinned `main.zip`.
- Preserve the complete upstream runtime layout, upstream MIT license, retained dependency/model/asset notices, original-file SHA-256 manifest, and a patch inventory.
- The XiaoZhi process owns `8000` and `8003`; Buddy Core owns `8010`. No per-frame adapter or second speech pipeline is allowed.
- Production configuration must enforce local-only configuration, `Memory: nomem`, `Intent: nointent`, disabled end prompt/tools/MCP/context/voiceprint/reporting, and Buddy Core as the selected LLM.
- Buddy Core receives only the current user turn plus immutable `device_id`, `client_id`, `session_id`, and `source: xiaozhi_core_fusion` metadata.
- Secrets remain in ignored local files or Windows environment variables and must never appear in commits, test output, debug endpoints, or review packages.
- Windows and conda `xiaozhi-env` are the only required v0.6 execution path.
- Do not remove v0.5 Gateway code until Task 9 acceptance and rollback gates pass.
- After every task: run the listed tests, commit only that task, dispatch a fresh independent subagent to inspect the diff and test evidence, fix all findings, and re-review until approved.

## File Structure

### Retained

- `buddy_brain/`: Buddy Core, profile, persona, memory, LLM, and Memory panel.
- `config/devices.example.yaml`: device-to-child mapping example.
- `scripts/start_buddy_core.ps1`, `scripts/smoke_chat.ps1`, `scripts/smoke_two_devices.ps1`.
- Buddy Core tests and historical design/status documents.

### Added

- `xiaozhi_server/`: complete pinned `main/xiaozhi-server` subtree.
- `xiaozhi_server/core/buddy/session_context.py`: immutable per-connection identity registry.
- `xiaozhi_server/core/buddy/config_contract.py`: fail-closed production configuration validation.
- `xiaozhi_server/core/buddy/diagnostics.py`: bounded in-process session/event registry.
- `xiaozhi_server/core/providers/llm/buddy_core/buddy_core.py`: native XiaoZhi LLM provider for Buddy Core.
- `xiaozhi_server/core/providers/tts/buddy_qwen_http.py`: provider-only DashScope Qwen TTS integration using the upstream flat TTS loader contract.
- `integrations/xiaozhi_server/provenance.py`: source manifest generation and verification.
- `scripts/backup_v05_runtime.ps1`, `scripts/import_xiaozhi_runtime.ps1`, `scripts/start_buddy_fusion.ps1`, `scripts/smoke_xiaozhi_fusion.ps1`.
- `tests/xiaozhi_fusion/`: focused source, config, provider, lifecycle, HTTP, and concurrency tests.
- `third_party/xiaozhi-esp32-server/`: upstream license and source metadata.
- `THIRD_PARTY_NOTICES.md`, `docs/third-party/xiaozhi-core-patch-inventory.md`.

### Replaced

- `scripts/setup_xiaozhi_server.ps1`: unpinned download/string patch becomes pinned import and verification.
- `scripts/start_xiaozhi_server.ps1`: `.run` startup becomes vendored-runtime startup.
- `integrations/xiaozhi_server/render_config.py` and `xiaozhi_config_template.yaml`: target the fused runtime and validate ownership invariants.
- `scripts/check_local_demo_status.ps1`, `backup_local_demo_data.ps1`, `stop_local_demo.ps1`.
- `tests/test_xiaozhi_config_renderer.py`, `tests/test_xiaozhi_scripts.py`.

### Removed Only After Acceptance

- `buddy_gateway/`.
- `tests/test_gateway.py`, `test_gateway_audio.py`, `test_gateway_asr.py`, `test_gateway_tts.py`, `test_gateway_core_client.py`.
- `scripts/start_buddy_gateway.ps1` and `scripts/smoke_gateway_*.ps1`.
- `buddy_gateway` from the Hatch package list in `pyproject.toml`.

---

### Task 1: Freeze v0.5 Baseline and Create a Verified Rollback Backup

**Files:**
- Create: `scripts/backup_v05_runtime.ps1`
- Create: `scripts/scan_staged_secrets.ps1`
- Modify: `.gitignore`
- Modify: `tests/test_xiaozhi_scripts.py`

**Interfaces:**
- Produces: `New-V05RuntimeBackup -BackupRoot <path>` returning `BackupDir`, `ManifestPath`, and `ManifestSha256`.
- Produces: `Restore-V05RuntimeBackup -BackupDir <path> [-Apply] [-EnvironmentTarget Process|User]`; default is validation-only dry run.
- Produces: an ignored `tmp/v05-runtime-backup/<timestamp>/` containing `.env`, XiaoZhi `.config.yaml`, selected ASR/TTS environment values, and Gateway audio evidence when present.

- [ ] **Step 1: Record the current baseline**

Run:

```powershell
git rev-parse HEAD
conda run -n xiaozhi-env python -m pytest -q
```

Expected: HEAD descends from `22e4712`; test result is `148 passed, 1 warning` or better.

- [ ] **Step 2: Write failing backup tests**

Add tests that create fake `.env`, `.config.yaml`, audio evidence, and process/user environment values; invoke the dot-sourced PowerShell functions; then assert the backup contains those files and this manifest shape without printing secret values. Add staged-secret scanner tests for a safe diff, a fake `sk-test-*` fixture allowed only by explicit path, and an unapproved key rejected without echoing it:

```json
{
  "source_commit": "22e4712814dfb19f1ecea9bd0e6bfbd24c057ac5",
  "files": [{"relative_path": ".env", "sha256": "<64 lowercase hex>"}],
  "environment_file": "environment.json"
}
```

Run:

```powershell
conda run -n xiaozhi-env python -m pytest tests/test_xiaozhi_scripts.py -k v05_backup -q
```

Expected: FAIL because `New-V05RuntimeBackup` does not exist.

- [ ] **Step 3: Implement the backup function**

The script must use `Copy-Item -LiteralPath`, write UTF-8 JSON with `ConvertTo-Json`, and calculate hashes with `Get-FileHash -Algorithm SHA256`. Store only these environment names:

```powershell
$names = @(
  "ASR_PROVIDER", "ASR_HTTP_URL", "ASR_MODEL", "ASR_API_KEY", "ASR_TIMEOUT_SECONDS",
  "TTS_PROVIDER", "TTS_HTTP_URL", "TTS_MODEL", "TTS_API_KEY",
  "TTS_VOICE", "TTS_LANGUAGE", "TTS_TIMEOUT_SECONDS"
)
```

The command output may include paths and hashes, but never environment values.

Implement restore as a two-phase operation: resolve every destination under the repository or approved Windows environment target, verify every manifest hash before writing anything, and create a pre-restore snapshot. Without `-Apply`, print only the validated action list. With `-Apply`, restore files through temporary siblings followed by atomic rename and restore environment values only to the explicitly selected target. Reject hash mismatch, path traversal, missing files, and destinations outside the approved set.

`scan_staged_secrets.ps1` scans `git diff --cached --no-color` for `sk-*`, bearer tokens, and non-placeholder key assignments, supports only an explicit test-fixture allowlist, and exits nonzero without echoing the matched value.

- [ ] **Step 4: Expand ignore rules**

Add:

```gitignore
.coverage
.coverage.*
htmlcov/
coverage.xml
*.log
*.pid
build/
dist/
*.egg-info/
.mypy_cache/
.hypothesis/
audio_output/
```

- [ ] **Step 5: Verify and create the real backup**

Run:

```powershell
conda run -n xiaozhi-env python -m pytest tests/test_xiaozhi_scripts.py -k "v05_backup or v05_restore" -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\backup_v05_runtime.ps1
git status --short
```

Expected: tests pass; the backup path is under ignored `tmp/`; no backup or secret file appears in `git status`.

- [ ] **Step 6: Commit and review**

```powershell
git add .gitignore scripts/backup_v05_runtime.ps1 scripts/scan_staged_secrets.ps1 tests/test_xiaozhi_scripts.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\scan_staged_secrets.ps1
git commit -m "chore: freeze v0.5 rollback baseline"
```

Review gate: verify no secrets, unsafe recursive file operations, missing hashes, partial restore behavior, path traversal, or untracked backup files. Fix and re-review until approved.

---

### Task 2: Import and Authenticate the Complete Pinned XiaoZhi Runtime

**Files:**
- Create: `xiaozhi_server/**` from pinned `main/xiaozhi-server/**`
- Create: `integrations/xiaozhi_server/provenance.py`
- Create: `scripts/import_xiaozhi_runtime.ps1`
- Create: `third_party/xiaozhi-esp32-server/LICENSE`
- Create: `third_party/xiaozhi-esp32-server/UPSTREAM.json`
- Create: `third_party/xiaozhi-esp32-server/SOURCE_MANIFEST.json`
- Create: `third_party/xiaozhi-esp32-server/PATCH_MANIFEST.json`
- Create: `THIRD_PARTY_NOTICES.md`
- Create: `docs/third-party/xiaozhi-core-patch-inventory.md`
- Create: `docs/third-party/xiaozhi-core-patch-reasons.json`
- Create: `tests/xiaozhi_fusion/test_provenance.py`

**Interfaces:**
- `build_manifest(source_dir: Path, imported_dir: Path, metadata: dict) -> dict`
- `verify_manifest(imported_dir: Path, source_manifest: dict, patch_manifest: dict) -> list[str]`; empty list means every file is either byte-identical to upstream or is recorded as an allowed `added`, `modified`, or `deleted` Buddy patch.
- `update_patch_manifest(imported_dir: Path, source_manifest: dict, reasons: dict) -> dict`; it refuses any changed path absent from the reviewed reason map.
- `Import-XiaoZhiRuntime -SourceCheckout <path> -Destination <repo>/xiaozhi_server`.

- [ ] **Step 1: Write failing provenance tests**

Cover exact origin URL, commit, tree, archive SHA-256 format, per-file SHA-256, added/missing/modified-file detection, deterministic `update-patches`, unknown-patch refusal, and preservation of the root MIT license. The fixture manifest must use this metadata:

```python
EXPECTED = {
    "origin": "https://github.com/xinnan-tech/xiaozhi-esp32-server.git",
    "commit": "8ec585102711516bf214b262f7d87bc04f9597e2",
    "tree": "7b96e40bf6541e9b94bdf7c53de9266e3590464d",
}
```

Run:

```powershell
conda run -n xiaozhi-env python -m pytest tests/xiaozhi_fusion/test_provenance.py -q
```

Expected: FAIL because the provenance module and imported tree do not exist.

- [ ] **Step 2: Implement structured manifest generation**

Use `hashlib.sha256`, `Path.rglob("*")`, and sorted POSIX relative paths. Exclude only generated runtime state:

```python
EXCLUDED_PARTS = {"data", "tmp", "__pycache__"}

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

`verify_manifest` must report `missing:<path>`, `unrecorded-modification:<path>`, `patch-hash-mismatch:<path>`, and `unexpected:<path>` deterministically. Each patch record contains `path`, `status`, `reason`, `original_sha256`, and `current_sha256`; the hash on the absent side is `null` for added/deleted files. The `update-patches --reason-file docs/third-party/xiaozhi-core-patch-reasons.json` command derives status and hashes from the source/current trees and fails on any path not present in the reason file. Later tasks must run `update-patches` and `verify` after every change under `xiaozhi_server`.

- [ ] **Step 3: Implement the pinned import script**

The PowerShell script must:

1. Resolve and verify the source checkout stays outside `xiaozhi_server`.
2. Check `remote.origin.url`, commit, tree, and clean status.
3. Create a deterministic `git archive` under ignored `tmp/` and calculate SHA-256.
4. Copy the complete `main/xiaozhi-server` subtree.
5. Copy upstream `LICENSE`.
6. Generate `UPSTREAM.json` and `SOURCE_MANIFEST.json` through `provenance.py`.
7. Refuse `-Force` replacement unless the destination resolves exactly to `<repo>/xiaozhi_server`.

- [ ] **Step 4: Import from the authenticated checkout**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\import_xiaozhi_runtime.ps1 -SourceCheckout .\tmp\xiaozhi-reference
```

Expected: imported file count equals `git ls-tree -r --name-only <commit> -- main/xiaozhi-server` after stripping the subtree prefix; never hard-code a count. The three `music/*.mp3` files receive an explicit retain-with-license or recorded-delete decision before commit.

- [ ] **Step 5: Add notices and the empty patch inventory**

`UPSTREAM.json` records origin, commit, tree, archive SHA-256, import timestamp, and source subtree. `THIRD_PARTY_NOTICES.md` links the copied MIT license and records the provenance/license decision for model files, config assets, and the three MP3 files. Unknown asset licensing blocks the task. The patch inventory begins with:

```markdown
# XiaoZhi Core Patch Inventory

Pinned commit: `8ec585102711516bf214b262f7d87bc04f9597e2`

No speech-core runtime files modified at import checkpoint.
```

Classify the public-looking credential embedded in upstream `config.yaml` as unsafe for redistribution in this repository: blank the value, add that path/reason to `xiaozhi-core-patch-reasons.json`, run `update-patches`, and record the security-only default-config patch. Add a deterministic secret scan for `sk-*`, bearer tokens, and non-placeholder `api_key` values; allow only documented test fixtures.

- [ ] **Step 6: Verify, commit, and review**

```powershell
conda run -n xiaozhi-env python -m pytest tests/xiaozhi_fusion/test_provenance.py -q
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance update-patches --reason-file docs/third-party/xiaozhi-core-patch-reasons.json
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance verify
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance scan-secrets
git diff --check
git add xiaozhi_server integrations/xiaozhi_server/provenance.py scripts/import_xiaozhi_runtime.ps1 tests/xiaozhi_fusion/test_provenance.py third_party THIRD_PARTY_NOTICES.md docs/third-party/xiaozhi-core-patch-inventory.md docs/third-party/xiaozhi-core-patch-reasons.json
git commit -m "build: import pinned xiaozhi runtime"
```

Review gate: compare imported hashes to the authenticated checkout, inspect every retained license, and reject any unexplained source difference or unknown license.

---

### Task 3: Boot the Unmodified XiaoZhi Entrypoint on 8000 and 8003

**Files:**
- Modify: `integrations/xiaozhi_server/render_config.py`
- Modify: `integrations/xiaozhi_server/xiaozhi_config_template.yaml`
- Modify: `scripts/render_xiaozhi_config.ps1`
- Modify: `scripts/start_xiaozhi_server.ps1`
- Create: `scripts/check_xiaozhi_dependencies.ps1`
- Modify: `pyproject.toml`
- Modify: `tests/test_xiaozhi_config_renderer.py`
- Modify: `tests/test_xiaozhi_scripts.py`
- Create: `tests/xiaozhi_fusion/test_upstream_boot.py`

**Interfaces:**
- Default runtime directory: `<repo>/xiaozhi_server`.
- Default local config: `<repo>/xiaozhi_server/data/.config.yaml`.
- `Invoke-StartXiaoZhiServer` runs `conda run --no-capture-output -n xiaozhi-env python <absolute-repo-path>\xiaozhi_server\app.py` with working directory `xiaozhi_server`.

- [ ] **Step 1: Write failing path and boot tests**

Assert rendering no longer targets `.run`, startup rejects paths outside `<repo>/xiaozhi_server`, and a subprocess configured on alternate ports exposes both listeners:

```python
assert wait_tcp("127.0.0.1", 18000, timeout=30)
assert wait_http("http://127.0.0.1:18003/xiaozhi/ota/", timeout=30).status_code == 200
```

The test must terminate the process in `finally` and verify both ports are released.

- [ ] **Step 2: Redirect config rendering to the vendored runtime**

Change `default_output_path()` and PowerShell path guards to `xiaozhi_server/data/.config.yaml`. Keep LAN IP validation. Use only upstream-native providers in this checkpoint; no Buddy runtime file may be modified yet.

- [ ] **Step 3: Redirect startup to the vendored runtime**

Preflight requires `app.py`, `core/`, `config/`, and `data/.config.yaml`. The script refuses `.run` and prints the expected WebSocket/OTA endpoints without secrets.

- [ ] **Step 4: Align and verify the shared conda environment**

Keep the imported `xiaozhi_server/requirements.txt` as the authoritative pinned runtime dependency list. Change the Buddy package constraints to `openai>=2.8.1,<3` and `httpx>=0.28.1,<1`, and add `websockets==14.2`. `check_xiaozhi_dependencies.ps1` runs `python -m pip check` and imports the production-selected modules; on failure it prints this exact repair command without running it automatically:

```powershell
conda run -n xiaozhi-env python -m pip install -r .\xiaozhi_server\requirements.txt
```

- [ ] **Step 5: Prove the original entrypoint boots unchanged**

```powershell
conda run -n xiaozhi-env python -m pytest tests/xiaozhi_fusion/test_upstream_boot.py tests/test_xiaozhi_config_renderer.py tests/test_xiaozhi_scripts.py -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_xiaozhi_dependencies.ps1
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance verify
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance scan-secrets
```

Expected: both listeners start; provenance verification reports no new or unrecorded difference beyond Task 2's security patch, and the entrypoint/speech core remain byte-identical.

- [ ] **Step 6: Run the protocol hardware checkpoint**

Start the unmodified runtime, point ESP32 OTA to `http://<LAN-IP>:8003/xiaozhi/ota/`, and confirm OTA POST, `/xiaozhi/v1/` connection, `hello`, `listen`, and incoming audio. An audible Buddy reply is not required yet.

- [ ] **Step 7: Commit and review**

```powershell
git add integrations/xiaozhi_server scripts/render_xiaozhi_config.ps1 scripts/start_xiaozhi_server.ps1 scripts/check_xiaozhi_dependencies.ps1 pyproject.toml tests/test_xiaozhi_config_renderer.py tests/test_xiaozhi_scripts.py tests/xiaozhi_fusion/test_upstream_boot.py
git commit -m "test: boot pinned xiaozhi runtime unchanged"
```

Review gate: prove no speech-core source file changed and both ports belong to the same `app.py` process.

---

### Task 4: Validate the Native Qwen ASR Provider

**Files:**
- Create: `xiaozhi_server/core/buddy/__init__.py`
- Create: `xiaozhi_server/core/buddy/provider_errors.py`
- Modify: `integrations/xiaozhi_server/render_config.py`
- Modify: `integrations/xiaozhi_server/xiaozhi_config_template.yaml`
- Modify: `scripts/render_xiaozhi_config.ps1`
- Create: `scripts/smoke_xiaozhi_asr.ps1`
- Create: `tests/xiaozhi_fusion/test_asr_provider_compatibility.py`
- Create only if the compatibility gate authorizes it: `xiaozhi_server/core/providers/asr/buddy_qwen.py`
- Modify when native error propagation is required: `xiaozhi_server/core/providers/asr/qwen3_asr_flash.py`
- Modify: `docs/third-party/xiaozhi-core-patch-reasons.json`
- Modify: `docs/third-party/xiaozhi-core-patch-inventory.md`
- Modify: `third_party/xiaozhi-esp32-server/PATCH_MANIFEST.json`

**Interfaces:**
- Upstream flat-loader contract: `core.providers.asr.<type>.ASRProvider`.
- ASR contract: `speech_to_text(opus_data, session_id, artifacts) -> (text, file_path)`.
- `ASRProviderFailure(public_code: str)` distinguishes typed provider failure from valid empty recognition.
- `ASR_PROVIDER`, `ASR_HTTP_URL`, `ASR_MODEL`, `ASR_API_KEY`, and `ASR_TIMEOUT_SECONDS` are read from Process first, then Windows User environment, and rendered only into ignored `xiaozhi_server/data/.config.yaml`.

- [ ] **Step 1: Write provider and secret-injection tests**

Assert renderer output uses environment values without command-line keys or stdout leakage. Test valid transcript, valid empty transcript, timeout, authentication error, service error, and malformed response as distinct outcomes.

- [ ] **Step 2: Implement secure environment rendering**

Add Process-then-User lookup for the five named ASR variables to `render_config.py` and `render_xiaozhi_config.ps1`. Require key/URL/model and a positive timeout for live mode, render them only into ignored `xiaozhi_server/data/.config.yaml`, pass no key as a command argument, and redact values from exceptions/output. The selected provider passes the explicit timeout to its HTTP/SDK call. Re-run the secret-injection and real timeout tests and require PASS before any live call.

- [ ] **Step 3: Run the live native compatibility gate**

Use the configured model and a short known WAV:

```powershell
conda run -n xiaozhi-env python -m pytest tests/xiaozhi_fusion/test_asr_provider_compatibility.py -m live_provider -q
```

When it passes, select `type: qwen3_asr_flash`. Create flat `core/providers/asr/buddy_qwen.py` only when the native provider cannot address the workspace endpoint/model; 401, quota, DNS, or malformed local configuration do not authorize a fallback. If authorized, port only the verified HTTP request and transcript parsing from `buddy_gateway/asr.py` into `ASRProviderBase`; do not copy buffering, WAV construction, VAD, session state, or finalization. Run the same valid/empty/timeout/auth/service/malformed contract tests against the fallback before selection.

- [ ] **Step 4: Preserve provider failures without treating silence as failure**

Define `ASRProviderFailure(public_code)` in `core/buddy/provider_errors.py`. In the selected provider, transport/SDK timeout, authentication, service, and malformed-response exceptions raise that type; a syntactically valid response with no transcript still returns `("", file_path)`. Remove only the native catch that converts actual exceptions into empty text, leaving normal empty recognition unchanged. Task 7 adds the base-layer catch and lifecycle notification.

- [ ] **Step 5: Validate real hardware transcription**

Start only the pinned runtime, speak once, and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_xiaozhi_asr.ps1
```

Expected: real device ID and non-empty transcript; no Buddy Core/TTS acceptance is required.

- [ ] **Step 6: Update and verify provenance, then commit**

```powershell
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance update-patches --reason-file docs/third-party/xiaozhi-core-patch-reasons.json
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance verify
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance scan-secrets
conda run -n xiaozhi-env python -m pytest tests/xiaozhi_fusion/test_asr_provider_compatibility.py -q
git add xiaozhi_server integrations/xiaozhi_server scripts/render_xiaozhi_config.ps1 scripts/smoke_xiaozhi_asr.ps1 tests/xiaozhi_fusion docs/third-party third_party/xiaozhi-esp32-server/PATCH_MANIFEST.json
git commit -m "feat: validate xiaozhi qwen asr"
```

Review gate: verify the upstream flat loader resolves the selected type, normal silence is not an error, secrets are absent, and no VAD/buffering/turn logic was copied.

---

### Task 5: Enforce Buddy Ownership and Add the Native Buddy Core LLM Provider

**Files:**
- Create: `xiaozhi_server/core/buddy/config_contract.py`
- Create: `xiaozhi_server/core/buddy/session_context.py`
- Create: `xiaozhi_server/core/providers/llm/buddy_core/buddy_core.py`
- Modify: `xiaozhi_server/app.py`
- Modify: `xiaozhi_server/core/connection.py`
- Modify: `xiaozhi_server/core/handle/helloHandle.py`
- Modify: `integrations/xiaozhi_server/xiaozhi_config_template.yaml`
- Create: `tests/xiaozhi_fusion/test_config_contract.py`
- Create: `tests/xiaozhi_fusion/test_session_context.py`
- Create: `tests/xiaozhi_fusion/test_buddy_core_provider.py`
- Modify: `docs/third-party/xiaozhi-core-patch-reasons.json`
- Modify: `docs/third-party/xiaozhi-core-patch-inventory.md`
- Modify: `third_party/xiaozhi-esp32-server/PATCH_MANIFEST.json`

**Interfaces:**
- `SessionContext(session_id: str, device_id: str, client_id: str, source: str = "xiaozhi_core_fusion")`, frozen dataclass.
- `register_context(context)`, `get_context(session_id)`, `remove_context(session_id)` guarded by `threading.RLock`.
- `validate_effective_config(config: dict) -> None`, raising `ValueError` on any ownership violation.
- XiaoZhi LLM provider contract remains `response(session_id, dialogue)`.
- Production `base_url` is exactly `http://127.0.0.1:8010`; a different loopback URL is accepted only by Task 7 fault-test mode.

- [ ] **Step 1: Write failing ownership and concurrency tests**

Cover manager URL/secret, remote config, Memory, Intent, end prompt, tools, MCP, context providers, VLLM, voiceprint, reporting, wrong LLM, registration/removal, client-id fallback, two interleaved sessions on one shared provider, and two overlapping turns in the same session.

```python
assert request.json()["messages"] == [{"role": "user", "content": "current turn"}]
assert request.json()["metadata"] == {
    "device_id": "fc:01", "client_id": "client-a",
    "session_id": "session-a", "source": "xiaozhi_core_fusion",
}
```

- [ ] **Step 2: Implement fail-closed configuration validation**

Before `load_config()`, reject a non-empty manager URL in local `data/.config.yaml` so remote configuration is never fetched. After merge and before listener construction, validate every Buddy ownership invariant without rewriting invalid values.

- [ ] **Step 3: Implement immutable identity and cleanup**

Register after headers/device ID are available with `client-id` fallback. Remove inside connection cleanup `finally`, including failed setup and repeated close.

At the start of each top-level `chat(query)`, immediately after appending that query, build an invocation-local dialogue snapshot. Pass that snapshot through the unchanged `response(session_id, dialogue)` signature. A later worker may mutate shared `Dialogue`, but cannot change the older invocation's final user turn.

- [ ] **Step 4: Implement `BuddyCoreLLMProvider`**

Select only the final non-empty user turn. Read `base_url` from validated config, append `/v1/chat/completions`, send `stream: false` with immutable metadata and explicit timeout, and yield the assistant string once. Never retain device metadata on the provider instance. Production validation pins the URL to `http://127.0.0.1:8010`; only the fully gated Task 7 fault configuration may select another loopback port.

- [ ] **Step 5: Render the ownership overlay**

Render `buddy_mode: true`, local-only manager settings, `Memory: nomem`, `Intent: nointent`, `end_prompt.enable: false`, Buddy Core LLM, no tools/MCP/context/voiceprint/reporting, and neutral XiaoZhi prompt. In Buddy mode, add two narrow upstream guards: `ConnectionHandler` does not construct/initialize `UnifiedToolHandler`, and `helloHandle.py` does not create an MCP client even when device features advertise MCP. Tests prove both native paths remain unchanged when Buddy mode is false.

- [ ] **Step 6: Update provenance, test, commit, and review**

```powershell
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance update-patches --reason-file docs/third-party/xiaozhi-core-patch-reasons.json
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance verify
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance scan-secrets
conda run -n xiaozhi-env python -m pytest tests/xiaozhi_fusion/test_config_contract.py tests/xiaozhi_fusion/test_session_context.py tests/xiaozhi_fusion/test_buddy_core_provider.py tests/test_app.py tests/test_memory.py tests/test_repository.py -q
git add xiaozhi_server integrations/xiaozhi_server tests/xiaozhi_fusion docs/third-party third_party/xiaozhi-esp32-server/PATCH_MANIFEST.json
git commit -m "feat: route xiaozhi turns through buddy core"
```

Review gate: inspect identity lifetime, interleaved-device isolation, current-turn-only forwarding, prompt/memory ownership, and remote-config bypasses.

---

### Task 6: Add Qwen TTS Through the Native Flat Provider Boundary

**Files:**
- Create: `xiaozhi_server/core/providers/tts/buddy_qwen_http.py`
- Modify: `integrations/xiaozhi_server/render_config.py`
- Modify: `integrations/xiaozhi_server/xiaozhi_config_template.yaml`
- Modify: `scripts/render_xiaozhi_config.ps1`
- Create: `scripts/smoke_xiaozhi_tts.ps1`
- Create: `tests/xiaozhi_fusion/test_qwen_tts_provider.py`
- Modify: `docs/third-party/xiaozhi-core-patch-reasons.json`
- Modify: `docs/third-party/xiaozhi-core-patch-inventory.md`
- Modify: `third_party/xiaozhi-esp32-server/PATCH_MANIFEST.json`

**Interfaces:**
- Upstream flat-loader contract: `core.providers.tts.<type>.TTSProvider`.
- `async text_to_speak(text, output_file) -> bytes | str | None`.
- `TTS_PROVIDER`, `TTS_HTTP_URL`, `TTS_MODEL`, `TTS_API_KEY`, `TTS_VOICE`, `TTS_LANGUAGE`, and `TTS_TIMEOUT_SECONDS` use the same Process-then-User environment policy and ignored config rendering as ASR.

- [ ] **Step 1: Write failing provider and secret-injection tests**

Mock inline audio and audio URL responses; cover timeout, 401, service error, malformed JSON, and valid audio. Assert no WebSocket send, Opus encoder, queue, VAD, or connection-state operation exists in the provider.

- [ ] **Step 2: Implement secure environment rendering**

Add Process-then-User lookup for all seven named TTS variables to the Python renderer and PowerShell wrapper. Require URL/model/key/voice and a positive timeout for live mode, render only into ignored runtime config, pass no key as a command argument, and redact values from output/errors. Re-run the secret-injection and real timeout tests and require PASS before provider smoke.

- [ ] **Step 3: Implement synthesis only**

Port only the verified DashScope request and audio download from `buddy_gateway/tts.py`. Subclass upstream `TTSProviderBase`, honor configured model/voice/language/timeout, and return bytes or write `output_file`. Keep upstream retries, normalization, Opus framing, queues, rate control, and playback unchanged.

- [ ] **Step 4: Run audible provider and original-queue smoke**

```powershell
conda run -n xiaozhi-env python -m pytest tests/xiaozhi_fusion/test_qwen_tts_provider.py -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_xiaozhi_tts.ps1
```

Expected: playable synthesis and nonzero Opus frames sent by the original XiaoZhi queue.

- [ ] **Step 5: Update provenance, commit, and review**

```powershell
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance update-patches --reason-file docs/third-party/xiaozhi-core-patch-reasons.json
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance verify
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance scan-secrets
git add xiaozhi_server integrations/xiaozhi_server scripts/render_xiaozhi_config.ps1 scripts/smoke_xiaozhi_tts.ps1 tests/xiaozhi_fusion docs/third-party third_party/xiaozhi-esp32-server/PATCH_MANIFEST.json
git commit -m "feat: add xiaozhi qwen tts provider"
```

Review gate: verify flat-loader resolution, secret handling, and absence of copied queue, Opus, playback, abort, or speech-state logic.

---

### Task 7: Add Bounded Diagnostics and Race-Safe Native Failure Recovery

**Files:**
- Create: `xiaozhi_server/core/buddy/diagnostics.py`
- Modify: `xiaozhi_server/core/buddy/config_contract.py`
- Modify: `xiaozhi_server/config/config_loader.py`
- Modify: `xiaozhi_server/core/http_server.py`
- Modify: `xiaozhi_server/core/connection.py`
- Modify: `xiaozhi_server/core/providers/asr/base.py`
- Modify: `xiaozhi_server/core/providers/tts/base.py`
- Modify: `xiaozhi_server/core/handle/receiveAudioHandle.py`
- Modify: `xiaozhi_server/core/handle/textHandler/listenMessageHandler.py`
- Modify: `xiaozhi_server/core/handle/sendAudioHandle.py`
- Modify: `xiaozhi_server/core/handle/abortHandle.py`
- Create: `xiaozhi_server/core/providers/asr/buddy_fault.py`
- Create: `tests/xiaozhi_fusion/test_diagnostics.py`
- Create: `tests/xiaozhi_fusion/test_provider_failure_recovery.py`
- Modify: `tests/xiaozhi_fusion/test_config_contract.py`
- Create: `tests/fixtures/fault_provider_server.py`
- Create: `scripts/run_xiaozhi_fault_injection.ps1`
- Modify: `docs/third-party/xiaozhi-core-patch-reasons.json`
- Modify: `docs/third-party/xiaozhi-core-patch-inventory.md`
- Modify: `third_party/xiaozhi-esp32-server/PATCH_MANIFEST.json`

**Interfaces:**
- `record_event(session_id: str, event_type: str, payload: dict) -> None`.
- `session_summaries() -> list[dict]`, maximum 20 completed sessions plus active sessions and 20 events per session.
- `notify_provider_failure(stage, sentence_id, asr_invocation_generation, public_error_code)`.
- `BUDDY_XIAOZHI_CONFIG_PATH` is honored only under the complete loopback fault-test gate; production always reads `data/.config.yaml`.

- [ ] **Step 1: Write failing bounded-registry tests**

Allow only connection open/close, listen, ASR completion/error, Buddy completion/error, TTS start/stop/error, and abort. Reject or redact payload keys matching audio, pcm, opus, prompt, key, token, authorization, headers, or config. Inject a registry exception and prove the speech caller continues.

- [ ] **Step 2: Write failing stale-failure tests**

Cover:

1. Turn A LLM/TTS failure arriving after `conn.sentence_id` advances to turn B.
2. Two auto-mode ASR invocations without another `listen start`, with the older failure arriving last.
3. A current provider failure calling native `handleAbortMessage`, clearing queues, sending one `tts stop`, and accepting a successful next turn.
4. LLM catch returning without enqueuing upstream fallback `MIDDLE`/`LAST` messages.
5. A failure passing the initial check, a newer turn starting before the scheduled callback executes, and the event-loop callback refusing to abort the newer turn.

- [ ] **Step 3: Implement diagnostics without queues or IPC**

Use a `threading.RLock`, bounded `deque(maxlen=20)`, primitive JSON-safe payloads, and best-effort exception handling. Add `/health`, `/debug/sessions`, `/debug/asr/providers`, and `/debug/tts/providers` to the existing `SimpleHttpServer`. Add narrow best-effort event calls after the owning actions in `listenMessageHandler.py`, `sendAudioHandle.py`, and `abortHandle.py`; do not infer events by reparsing frames or duplicate lifecycle decisions.

- [ ] **Step 4: Implement the narrow failure hook**

Increment `asr_invocation_generation` exactly at each existing `handle_voice_stop`/ASR invocation boundary. `notify_provider_failure` schedules an `_abort_if_still_current` coroutine on `conn.loop`; that coroutine, immediately before awaiting native `handleAbortMessage(conn)`, rechecks sentence ID or ASR generation, connection open/closed state, and stop event. A stale or closed callback records no abort. Do not perform the decisive check only in the provider thread, and do not reimplement queue clearing, speaking reset, rate control, or WebSocket lifecycle.

- [ ] **Step 5: Patch existing catches to notify and return**

Keep the upstream TTS retry loop. `ASRProviderFailure` reaches `ASRProviderBase.handle_voice_stop`; valid empty transcripts do not. Notify only on typed ASR failure, Buddy provider failure, final TTS exhaustion, and the existing worker catch. After notification, return/continue without adding fallback text or audio. Store bounded public codes such as `asr_timeout`, `buddy_invalid_response`, and `tts_failed`; log raw exception text locally only.

- [ ] **Step 6: Add deterministic localhost-only fault injection**

`fault_provider_server.py` binds only `127.0.0.1` on an alternate test port and exposes explicit one-shot modes: timeout, HTTP 500, malformed response, and partial TTS failure. The always-available flat `buddy_fault.py` ASR provider calls only that loopback server and exists solely for deterministic recovery tests. Add a narrow `config_loader.py` override: it reads `BUDDY_XIAOZHI_CONFIG_PATH` only when Process environment contains `BUDDY_FAULT_TEST_MODE=1`, requires an absolute path under ignored `<repo>/tmp/fault-config/`, and otherwise continues to read only `data/.config.yaml`. Immediately after choosing and reading either local config path, but before the branch that can call `get_config_from_api_async()`, reject any non-empty `manager-api.url`; do not defer this check to effective-config validation. The wrapper writes the separate fault config, exports both variables to the child only, never edits production config, and clears them in `finally`.

`validate_effective_config` accepts `buddy_fault`, alternate Buddy Core loopback URL, and fault TTS endpoint only when all conditions hold: loopback bind, non-production HTTP/WebSocket ports, `fault_test_mode: true`, `BUDDY_FAULT_TEST_MODE=1`, and approved config path. Tests require rejection for each missing condition, non-loopback host, production port, path escape, and alternate URL without fault mode. A dedicated loader test supplies a fault config with a manager URL, mocks `get_config_from_api_async`, and asserts startup rejects before that mock is called.

- [ ] **Step 7: Run focused and regression tests**

```powershell
conda run -n xiaozhi-env python -m pytest tests/xiaozhi_fusion/test_diagnostics.py tests/xiaozhi_fusion/test_provider_failure_recovery.py -q
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance update-patches --reason-file docs/third-party/xiaozhi-core-patch-reasons.json
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance verify
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance scan-secrets
conda run -n xiaozhi-env python -m pytest -q
```

- [ ] **Step 8: Commit and review**

```powershell
git add xiaozhi_server tests/xiaozhi_fusion tests/fixtures/fault_provider_server.py scripts/run_xiaozhi_fault_injection.ps1 docs/third-party third_party/xiaozhi-esp32-server/PATCH_MANIFEST.json
git commit -m "feat: add fused runtime diagnostics and recovery"
```

Review gate: audit every changed upstream line, stale callback behavior, secret/audio redaction, and the prohibition on a second speech controller.

---

### Task 8: Add Windows Orchestration, Status Checks, and Software Voice-Loop Validation

**Files:**
- Create: `scripts/start_buddy_fusion.ps1`
- Create: `scripts/smoke_xiaozhi_fusion.ps1`
- Modify: `scripts/check_local_demo_status.ps1`
- Modify: `scripts/stop_local_demo.ps1`
- Modify: `scripts/backup_local_demo_data.ps1`
- Modify: `tests/test_xiaozhi_scripts.py`
- Create: `tests/xiaozhi_fusion/test_voice_loop.py`
- Create: `tests/xiaozhi_fusion/test_windows_process_lifecycle.py`
- Modify: `README.md`
- Create: `docs/runbooks/buddy-xiaozhi-core-fusion.md`

**Interfaces:**
- `start_buddy_fusion.ps1 -AdvertiseHost <LAN-IP> -CondaEnv xiaozhi-env` starts Buddy Core, waits for `8010`, then starts fused XiaoZhi and waits for `8000/8003`.
- `check_local_demo_status.ps1` returns process/port ownership, effective config invariants, provider selection, provenance state, and recent session state.
- `stop_local_demo.ps1` stops fused XiaoZhi first, verifies `8000/8003` release, then stops Buddy Core.

- [ ] **Step 1: Write failing orchestration tests**

Mock port ownership, `Start-Process`, health responses, listener discovery, and shutdown. Assert unknown owners fail closed, the same real listener PID owns `8000/8003`, `8010` becomes healthy before XiaoZhi starts, and secrets never appear in output.

- [ ] **Step 2: Implement startup and coordinated shutdown**

Use `Start-Process -WindowStyle Hidden -PassThru` for the conda wrappers, but do not treat wrapper PIDs as service ownership. Start XiaoZhi with the absolute `xiaozhi_server\app.py` path. After readiness, resolve actual listener PIDs through `Get-NetTCPConnection`; `Resolve-ServiceListenerPid` receives an explicit expected absolute script/module identity, then validates `Win32_Process.ExecutablePath` belongs to `xiaozhi-env` and the command line contains that identity. Store real listener PIDs plus optional wrapper PIDs under ignored `tmp/runtime/`. Stop real listeners first, then wrappers, and verify port release. Remove stale PID files only after identity checks.

Before rendering ignored runtime configuration, copy only the named ASR/TTS variables from Windows User scope into Process scope when Process scope is empty. Pass keys through environment only, never PowerShell arguments. Redact values in errors and run `provenance scan-secrets` before every commit touching configuration or scripts.

- [ ] **Step 3: Run a real child-process lifecycle test**

Start an absolute-path minimal Python listener fixture through `conda run` on alternate ports, pass that fixture path as the expected identity, prove the wrapper PID differs when applicable, discover and validate the actual listener PID, stop it through the production helper, and assert the port is released. This test is Windows-only and must not be replaced by a mock.

- [ ] **Step 4: Implement software voice-loop test**

The test client sends XiaoZhi `hello`, `listen`, and valid Opus input, then asserts this sequence on the same socket:

```text
stt (optional) -> tts start -> tts sentence_start -> binary Opus frames -> tts stop
```

It also verifies the Buddy Memory endpoint contains the test device ID and one episode.

- [ ] **Step 5: Update status, backup, README, and runbook**

Document the two-process architecture, exact startup commands, OTA URL, debug endpoints, provider environment names, stop command, hardware acceptance, rollback command, and the fact that v0.5 Gateway remains only as branch history until cleanup.

- [ ] **Step 6: Run the full software gate**

```powershell
conda run -n xiaozhi-env python -m pytest -q
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance scan-secrets
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_fusion.ps1 -AdvertiseHost 192.168.0.101
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_local_demo_status.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_xiaozhi_fusion.ps1
```

Expected: all tests pass, all three ports are healthy with correct ownership, and software voice loop receives nonzero Opus frames.

- [ ] **Step 7: Commit and review**

```powershell
git add scripts tests README.md docs/runbooks/buddy-xiaozhi-core-fusion.md
git commit -m "feat: add fused runtime windows workflow"
```

Review gate: inspect process safety, readiness ordering, port reuse, stale PIDs, path validation, documentation accuracy, and smoke-test false positives.

---

### Task 9: Run Real-Hardware Acceptance and Operational Rollback Drill

**Files:**
- Create: `docs/status/2026-07-18-buddy-xiaozhi-fusion-acceptance.md`
- Modify only when a tested defect is found: the smallest file owning that defect.

**Interfaces:**
- Acceptance evidence records session IDs, device IDs, timestamps, event status, frame counts, and commands; it never records API keys or raw audio.

- [ ] **Step 1: Run three consecutive auto-mode turns**

With ESP32 OTA set to `http://<LAN-IP>:8003/xiaozhi/ota/`, complete three audible turns without `listen stop` or disconnect finalization. Confirm one WebSocket session and three Buddy Memory episodes for the hardware device ID.

- [ ] **Step 2: Run abort recovery**

Interrupt a playing reply from hardware, confirm native `tts stop`, then complete another audible turn on the same connection.

- [ ] **Step 3: Run two-device isolation**

Connect two devices or one hardware device plus the protocol client. Interleave turns and prove device/client/session metadata, VAD state, ASR invocation, TTS queues, abort, and Buddy Memory do not cross.

- [ ] **Step 4: Run provider recovery cases**

Use the Task 7 loopback-only one-shot fault server to inject one bounded ASR, Buddy Core, and TTS failure separately against the protocol test client, not the production endpoints. For each, confirm a debug error event, native queue cleanup, no stale callback aborting the next turn, and a successful next turn on the same connection. Keep real hardware connected only for the normal and abort acceptance steps.

- [ ] **Step 5: Perform the v0.5 rollback drill**

Stop fused XiaoZhi, verify `8000/8003` release, and stop Buddy Core. While still on the fusion branch, run `Restore-V05RuntimeBackup -BackupDir <path>` as dry run, then repeat with `-Apply -EnvironmentTarget Process`; the backup also contains a copy of the restore script and manifest for audit. Switch to `codex/buddy-device-gateway-v0.5-voice-loop`, start v0.5, and pass health, OTA, and one voice turn. Stop v0.5, verify all three ports are released, return to the fusion branch, restart the fused services, and confirm Buddy memory data is unchanged. Any manifest mismatch or restore error stops before service startup and leaves the pre-restore snapshot available.

- [ ] **Step 6: Record evidence, commit, and review**

```powershell
git add docs/status/2026-07-18-buddy-xiaozhi-fusion-acceptance.md
git commit -m "test: record xiaozhi fusion hardware acceptance"
```

Review gate: independently compare logs/status evidence to every acceptance requirement. Any failed or ambiguous signal blocks cleanup.

---

### Task 10: Remove Superseded Gateway Code and Finish the Refactor

**Files:**
- Delete: `buddy_gateway/`
- Delete: `tests/test_gateway.py`
- Delete: `tests/test_gateway_audio.py`
- Delete: `tests/test_gateway_asr.py`
- Delete: `tests/test_gateway_tts.py`
- Delete: `tests/test_gateway_core_client.py`
- Delete: `scripts/start_buddy_gateway.ps1`
- Delete: `scripts/smoke_gateway_asr_text_loop.ps1`
- Delete: `scripts/smoke_gateway_audio_capture.ps1`
- Delete: `scripts/smoke_gateway_text_loop.ps1`
- Delete: `scripts/smoke_gateway_voice_loop.ps1`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Move: `docs/runbooks/buddy-device-gateway-v0.1.md` to `docs/archive/buddy-device-gateway-v0.1-v0.5.md`
- Modify: `docs/status/2026-07-18-buddy-xiaozhi-fusion-acceptance.md`

**Interfaces:**
- The production package list contains only `buddy_brain`; the fused XiaoZhi runtime is executed from its preserved source directory.
- No tracked file imports `buddy_gateway` or invokes an obsolete Gateway script.

- [ ] **Step 1: Prove equivalent fusion coverage exists**

Map each deleted test category to passing fusion tests: OTA/WebSocket, audio, ASR, Buddy metadata, TTS, abort, scripts, hardware, and two-device isolation. Add missing fusion coverage before deleting anything.

- [ ] **Step 2: Run the redundancy scan before deletion**

```powershell
rg -n "buddy_gateway|start_buddy_gateway|smoke_gateway_" -g "!docs/archive/**" -g "!docs/superpowers/**"
```

Classify every hit. Production/runtime hits must be migrated; historical design/status hits may remain as history.

- [ ] **Step 3: Delete the superseded package, tests, and scripts**

Remove only the listed tracked files. Do not delete `buddy_brain`, `data/buddy_memory.db`, Profile configuration, Memory documentation, or historical architecture/status documents.

- [ ] **Step 4: Update packaging and archive the runbook**

Change:

```toml
[tool.hatch.build.targets.wheel]
packages = ["buddy_brain"]
```

The archived runbook begins with a note that v0.1-v0.5 is superseded by the fused XiaoZhi runtime and remains available on `codex/buddy-device-gateway-v0.5-voice-loop`.

- [ ] **Step 5: Clean ignored local bytecode and audio evidence after backup**

Delete only verified ignored paths under this repository: `buddy_gateway/__pycache__`, `tests/__pycache__`, and `data/gateway_audio`. Resolve each absolute path and confirm it is under the repository before recursive removal. Preserve `data/buddy_memory.db`.

- [ ] **Step 6: Run final verification**

```powershell
conda run -n xiaozhi-env python -m pytest -q
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance verify
conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance scan-secrets
rg -n "buddy_gateway|start_buddy_gateway|smoke_gateway_" -g "!docs/archive/**" -g "!docs/superpowers/**"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_local_demo_status.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_xiaozhi_fusion.ps1
```

Expected: tests and provenance pass; runtime redundancy scan has no hits; fused software/hardware smoke remains green.

- [ ] **Step 7: Commit and final independent reviews**

```powershell
git add -A buddy_gateway tests scripts pyproject.toml README.md docs/runbooks docs/archive docs/status
git commit -m "refactor: retire custom buddy gateway runtime"
```

Run two fresh independent reviews:

1. Source-alignment review: prove original XiaoZhi VAD, ASR invocation, queues, rate control, playback, abort, and WebSocket lifecycle remain the owners.
2. Code-quality/acceptance review: inspect regressions, security, secrets, process handling, rollback evidence, redundant code, and test gaps.

Fix every finding and repeat both reviews until both report Approved. Then run the full test and hardware smoke once more before pushing the branch.
