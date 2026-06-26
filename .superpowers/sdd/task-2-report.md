# Task 2 Report: Windows Operator Scripts

Implemented the Windows PowerShell operator scripts requested in Task 2 and added script validation tests.

## Delivered

- `scripts/render_xiaozhi_config.ps1`
- `scripts/setup_xiaozhi_server.ps1`
- `scripts/start_buddy_brain.ps1`
- `scripts/start_xiaozhi_server.ps1`
- `scripts/print_local_demo_urls.ps1`
- `tests/test_xiaozhi_scripts.py`

## TDD Evidence

1. Wrote `tests/test_xiaozhi_scripts.py` first.
2. Ran `py -3.10 -m pytest tests/test_xiaozhi_scripts.py -v`.
3. Confirmed the expected red state: all four tests failed because the scripts did not exist yet.
4. Added the scripts with minimal PowerShell logic to satisfy the tests.
5. Re-ran the focused tests and confirmed they passed.

## Verification

- Focused tests: `py -3.10 -m pytest tests/test_xiaozhi_scripts.py -v`
- PowerShell parse check: `powershell -NoProfile -Command "[scriptblock]::Create((Get-Content -Raw scripts/render_xiaozhi_config.ps1)) | Out-Null; [scriptblock]::Create((Get-Content -Raw scripts/setup_xiaozhi_server.ps1)) | Out-Null; [scriptblock]::Create((Get-Content -Raw scripts/start_buddy_brain.ps1)) | Out-Null; [scriptblock]::Create((Get-Content -Raw scripts/start_xiaozhi_server.ps1)) | Out-Null; [scriptblock]::Create((Get-Content -Raw scripts/print_local_demo_urls.ps1)) | Out-Null; 'Parse OK'"`
- Full suite: `py -3.10 -m pytest -v`

Results:

- Focused tests: passed
- Parse check: `Parse OK`
- Full suite: `34 passed, 1 warning`

## Commit

- `9ca2a1a feat: add xiaozhi operator scripts`

## Notes

- The scripts are written to be repeatable and `.run`-scoped, but their live runtime behavior was not exercised here because the task explicitly limited validation to script tests and PowerShell parse checks.

---

## Task 2 Review Fix Report

### Scope

- `scripts/setup_xiaozhi_server.ps1`
- `scripts/render_xiaozhi_config.ps1`
- `scripts/print_local_demo_urls.ps1`
- `scripts/start_buddy_brain.ps1`
- `scripts/start_xiaozhi_server.ps1`
- `tests/test_xiaozhi_scripts.py`

### RED

Updated `tests/test_xiaozhi_scripts.py` first to assert:

- `.run` confinement logic in `setup_xiaozhi_server.ps1`
- `$PSScriptRoot`-relative repo root handling
- stable private IPv4 selection without `InterfaceMetric`
- protected Buddy Brain and XiaoZhi host/port values
- `$PSScriptRoot`-relative startup defaults

Command:

- `py -3.10 -m pytest tests/test_xiaozhi_scripts.py -v`

Observed failure summary:

- `6 failed, 1 passed`
- failures covered missing `$PSScriptRoot` usage, `InterfaceMetric` sorting, missing `.run` boundary enforcement, and startup scripts depending on caller working directory

### GREEN

Applied minimal PowerShell fixes:

- `setup_xiaozhi_server.ps1` now resolves `-Destination` against the repo root, normalizes to absolute paths, verifies the target stays under the repo `.run` directory, and only then performs recursive removal
- `render_xiaozhi_config.ps1` now derives `--repo-root` from `$PSScriptRoot` and uses deterministic private IPv4 selection with `192.168.2.*` preference
- `print_local_demo_urls.ps1` now uses the same deterministic private IPv4 selection
- `start_buddy_brain.ps1` and `start_xiaozhi_server.ps1` now resolve defaults relative to `$PSScriptRoot`

### Verification

Focused tests:

- `py -3.10 -m pytest tests/test_xiaozhi_scripts.py -v`
- Result: `7 passed`

Parse check:

- `[System.Management.Automation.Language.Parser]::ParseFile(...)` across all five scripts
- Result: all five scripts returned `PARSE_OK`

Full suite:

- `py -3.10 -m pytest -v`
- Result: `37 passed, 1 warning`

---

## Task 2 Second Review Fix Report

### RED

- Added helper-level PowerShell tests in `tests/test_xiaozhi_scripts.py` before changing the scripts.
- Verified the new regression coverage failed against the pre-fix scripts because dot-sourcing executed the script bodies, helper functions were missing, `.run` root was not rejected, and the private-IP logic still accepted `172.2*`.
- Command: `py -3.10 -m pytest tests/test_xiaozhi_scripts.py -v`
- Result: `6 failed, 2 passed`

### GREEN

- Refactored `scripts/setup_xiaozhi_server.ps1` to expose `Get-RepoRoot`, `Test-IsStrictChildOfDirectory`, `Get-XiaoZhiSetupPaths`, and a guarded `Invoke-XiaoZhiSetup` entry point.
- Tightened setup path validation so `-Destination .run` and any destination resolving to the repo `.run` root are rejected before any recursive delete, and verified the download zip and extract directory also remain under repo `.run`.
- Refactored `scripts/render_xiaozhi_config.ps1` and `scripts/print_local_demo_urls.ps1` to expose real helper functions, skip main execution when dot-sourced, and use exact RFC1918 checks for `10.*`, `192.168.*`, and `172.16.*` through `172.31.*`.
- Preserved manual `-HostIp` handling and `$PSScriptRoot`-relative repo-root resolution.

### Verification

- Focused tests: `py -3.10 -m pytest tests/test_xiaozhi_scripts.py -v`
- Result: `8 passed`
- Parse checks: `powershell -NoProfile -ExecutionPolicy Bypass -Command "[scriptblock]::Create((Get-Content -Raw 'scripts/render_xiaozhi_config.ps1')) | Out-Null; Write-Output 'PARSE_OK scripts/render_xiaozhi_config.ps1'; [scriptblock]::Create((Get-Content -Raw 'scripts/setup_xiaozhi_server.ps1')) | Out-Null; Write-Output 'PARSE_OK scripts/setup_xiaozhi_server.ps1'; [scriptblock]::Create((Get-Content -Raw 'scripts/print_local_demo_urls.ps1')) | Out-Null; Write-Output 'PARSE_OK scripts/print_local_demo_urls.ps1'"`
- Result: `PARSE_OK` for all three scoped scripts
- Full suite: `py -3.10 -m pytest -v`
- Result: `38 passed, 1 warning`

### Commit

- Recorded in git history as `fix: strengthen xiaozhi script safety checks`.
- The exact final commit id is reported from `git rev-parse --short HEAD` after the last amend, because embedding the final hash inside the commit would change that hash again.
