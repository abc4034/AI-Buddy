# XiaoZhi Server Buddy Brain Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the checked-in integration assets needed to route XiaoZhi server LLM calls to the local Buddy Brain service and prepare the local hardware handoff path.

**Architecture:** The repository owns a small `integrations/xiaozhi_server` package that renders XiaoZhi `data/.config.yaml` from a template and host LAN IP. PowerShell scripts prepare ignored runtime storage under `.run/`, start Buddy Brain, prepare the upstream XiaoZhi server checkout, and print the exact local OTA/WebSocket URLs. The upstream XiaoZhi source and runtime config stay untracked.

**Tech Stack:** Python 3.10+, standard library `string.Template` and `ipaddress`, PowerShell 5+, pytest, existing FastAPI Buddy Brain service, upstream `xinnan-tech/xiaozhi-esp32-server`.

## Global Constraints

- First demo runs in the local network on Windows host IP `192.168.2.9`.
- Device-facing URLs must use the LAN IP, never `127.0.0.1`.
- Buddy Brain listens on `0.0.0.0:8010`.
- XiaoZhi WebSocket listens on `0.0.0.0:8000`.
- XiaoZhi HTTP/OTA listens on `0.0.0.0:8003`.
- XiaoZhi LLM provider name is `BuddyBrainLLM`.
- XiaoZhi LLM provider uses `type: openai`.
- XiaoZhi LLM `base_url` is `http://<host-ip>:8010/v1`.
- XiaoZhi LLM `model_name` is `deepseek-v4-flash`.
- XiaoZhi LLM `api_key` is the non-secret local placeholder `local`.
- XiaoZhi memory is disabled with `selected_module.Memory: nomem`.
- XiaoZhi intent is disabled with `selected_module.Intent: nointent`.
- No API keys are written to tracked files.
- Upstream XiaoZhi source is downloaded or cloned only under `.run/`, which is ignored.
- Any firmware flashing or serial-port action must stop and wait for the user to plug the board or press `BOOT` / `RESET`.

---

## File Structure

- Create `integrations/__init__.py`: package marker.
- Create `integrations/xiaozhi_server/__init__.py`: package marker.
- Create `integrations/xiaozhi_server/xiaozhi_config_template.yaml`: minimal XiaoZhi config override template with `${HOST_IP}` placeholders.
- Create `integrations/xiaozhi_server/render_config.py`: validates LAN IP, renders template, writes `.run/xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml`.
- Create `tests/test_xiaozhi_config_renderer.py`: unit tests for rendering and validation.
- Create `scripts/render_xiaozhi_config.ps1`: auto-detects or accepts host LAN IP and calls the renderer.
- Create `scripts/setup_xiaozhi_server.ps1`: downloads the upstream server ZIP into `.run/` and prepares the runtime directory.
- Create `scripts/start_buddy_brain.ps1`: starts Buddy Brain with the existing app.
- Create `scripts/start_xiaozhi_server.ps1`: starts the upstream XiaoZhi server using conda.
- Create `scripts/print_local_demo_urls.ps1`: prints Buddy Brain, XiaoZhi OTA, and XiaoZhi WebSocket URLs for the current host IP.
- Modify `README.md`: add XiaoZhi bridge setup, service startup, and hardware pause-point instructions.

---

### Task 1: XiaoZhi Config Renderer

**Files:**
- Create: `integrations/__init__.py`
- Create: `integrations/xiaozhi_server/__init__.py`
- Create: `integrations/xiaozhi_server/xiaozhi_config_template.yaml`
- Create: `integrations/xiaozhi_server/render_config.py`
- Create: `tests/test_xiaozhi_config_renderer.py`

**Interfaces:**
- Consumes: no existing code except repository root layout.
- Produces:
  - `integrations.xiaozhi_server.render_config.render_config(host_ip: str) -> str`
  - `integrations.xiaozhi_server.render_config.default_output_path(repo_root: Path) -> Path`
  - CLI: `py -3.10 -m integrations.xiaozhi_server.render_config --host-ip 192.168.2.9`

- [ ] **Step 1: Write failing renderer tests**

Create `tests/test_xiaozhi_config_renderer.py`:

```python
from pathlib import Path

import pytest

from integrations.xiaozhi_server.render_config import (
    default_output_path,
    render_config,
    write_config,
)


def test_render_config_uses_lan_ip_for_all_device_facing_urls():
    rendered = render_config("192.168.2.9")

    assert "websocket: ws://192.168.2.9:8000/xiaozhi/v1/" in rendered
    assert "vision_explain: http://192.168.2.9:8003/mcp/vision/explain" in rendered
    assert "base_url: http://192.168.2.9:8010/v1" in rendered
    assert "LLM: BuddyBrainLLM" in rendered
    assert "Memory: nomem" in rendered
    assert "Intent: nointent" in rendered
    assert "api_key: local" in rendered
    assert "${HOST_IP}" not in rendered


@pytest.mark.parametrize("bad_ip", ["127.0.0.1", "localhost", "999.1.1.1", ""])
def test_render_config_rejects_unusable_device_ip(bad_ip):
    with pytest.raises(ValueError):
        render_config(bad_ip)


def test_write_config_creates_parent_directories(tmp_path):
    output = tmp_path / ".run" / "xiaozhi-esp32-server" / "main" / "xiaozhi-server" / "data" / ".config.yaml"

    written = write_config("192.168.2.9", output)

    assert written == output
    assert output.exists()
    assert "BuddyBrainLLM" in output.read_text(encoding="utf-8")


def test_default_output_path_points_to_xiaozhi_runtime_data():
    repo_root = Path("C:/workspace/AI Buddy")

    path = default_output_path(repo_root)

    assert path.as_posix().endswith(".run/xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
py -3.10 -m pytest tests/test_xiaozhi_config_renderer.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'integrations'`.

- [ ] **Step 3: Add the renderer package and template**

Create `integrations/__init__.py`:

```python
"""Integration helpers for external AI Buddy services."""
```

Create `integrations/xiaozhi_server/__init__.py`:

```python
"""XiaoZhi server integration helpers."""
```

Create `integrations/xiaozhi_server/xiaozhi_config_template.yaml`:

```yaml
server:
  ip: 0.0.0.0
  port: 8000
  http_port: 8003
  websocket: ws://${HOST_IP}:8000/xiaozhi/v1/
  vision_explain: http://${HOST_IP}:8003/mcp/vision/explain
  auth:
    enabled: false

selected_module:
  LLM: BuddyBrainLLM
  Memory: nomem
  Intent: nointent

Intent:
  nointent:
    type: nointent

LLM:
  BuddyBrainLLM:
    type: openai
    base_url: http://${HOST_IP}:8010/v1
    model_name: deepseek-v4-flash
    api_key: local
    temperature: 0.7
    max_tokens: 300

prompt: |
  You are Buddy, a warm English companion for a primary-school beginner.
  Keep replies short, child-friendly, and suitable for speech.
  Prefer simple English. Add a short Chinese explanation when it helps.
  Ask at most one follow-up question.
  Correct at most one clear English mistake per turn.
```

Create `integrations/xiaozhi_server/render_config.py`:

```python
from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
from string import Template


TEMPLATE_PATH = Path(__file__).with_name("xiaozhi_config_template.yaml")


def validate_host_ip(host_ip: str) -> str:
    try:
        ip = ipaddress.ip_address(host_ip)
    except ValueError as exc:
        raise ValueError(f"host_ip must be an IPv4 LAN address, got {host_ip!r}") from exc

    if ip.version != 4 or ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        raise ValueError(f"host_ip must be reachable by the ESP32 on the LAN, got {host_ip!r}")

    return str(ip)


def render_config(host_ip: str) -> str:
    safe_ip = validate_host_ip(host_ip)
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    return template.substitute(HOST_IP=safe_ip)


def default_output_path(repo_root: Path) -> Path:
    return repo_root / ".run" / "xiaozhi-esp32-server" / "main" / "xiaozhi-server" / "data" / ".config.yaml"


def write_config(host_ip: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_config(host_ip), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render XiaoZhi server config for the AI Buddy local demo.")
    parser.add_argument("--host-ip", required=True, help="Windows host LAN IPv4 address reachable by the ESP32.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="AI Buddy repository root. Defaults to current directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output .config.yaml path. Defaults to .run/xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml.",
    )
    args = parser.parse_args()

    output = args.output or default_output_path(args.repo_root)
    written = write_config(args.host_ip, output)
    print(written)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run renderer tests**

Run:

```powershell
py -3.10 -m pytest tests/test_xiaozhi_config_renderer.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add integrations tests/test_xiaozhi_config_renderer.py
git commit -m "feat: add xiaozhi config renderer"
```

---

### Task 2: Windows Operator Scripts

**Files:**
- Create: `scripts/render_xiaozhi_config.ps1`
- Create: `scripts/setup_xiaozhi_server.ps1`
- Create: `scripts/start_buddy_brain.ps1`
- Create: `scripts/start_xiaozhi_server.ps1`
- Create: `scripts/print_local_demo_urls.ps1`
- Create: `tests/test_xiaozhi_scripts.py`

**Interfaces:**
- Consumes:
  - `integrations.xiaozhi_server.render_config`
  - `.run/` ignored runtime directory
- Produces:
  - repeatable PowerShell entry points for setup, config rendering, and service startup.

- [ ] **Step 1: Write script validation tests**

Create `tests/test_xiaozhi_scripts.py`:

```python
from pathlib import Path


SCRIPTS = [
    "render_xiaozhi_config.ps1",
    "setup_xiaozhi_server.ps1",
    "start_buddy_brain.ps1",
    "start_xiaozhi_server.ps1",
    "print_local_demo_urls.ps1",
]


def test_xiaozhi_scripts_exist_and_are_ascii_safe():
    for script_name in SCRIPTS:
        path = Path("scripts") / script_name
        assert path.exists(), f"missing {path}"
        text = path.read_text(encoding="utf-8")
        text.encode("ascii")
        assert "$ErrorActionPreference = \"Stop\"" in text


def test_render_script_calls_python_renderer():
    text = Path("scripts/render_xiaozhi_config.ps1").read_text(encoding="utf-8")

    assert "integrations.xiaozhi_server.render_config" in text
    assert "--host-ip" in text


def test_setup_script_keeps_upstream_source_under_run_directory():
    text = Path("scripts/setup_xiaozhi_server.ps1").read_text(encoding="utf-8")

    assert ".run" in text
    assert "xiaozhi-esp32-server" in text
    assert "refs/heads/main.zip" in text


def test_start_xiaozhi_script_uses_conda_environment():
    text = Path("scripts/start_xiaozhi_server.ps1").read_text(encoding="utf-8")

    assert "conda run" in text
    assert "xiaozhi-esp32-server" in text
    assert "python app.py" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
py -3.10 -m pytest tests/test_xiaozhi_scripts.py -v
```

Expected: FAIL because the scripts do not exist.

- [ ] **Step 3: Add `scripts/render_xiaozhi_config.ps1`**

Create `scripts/render_xiaozhi_config.ps1`:

```powershell
$ErrorActionPreference = "Stop"

param(
  [string]$HostIp = "",
  [string]$Output = ""
)

function Get-DefaultLanIp {
  $preferred = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
      $_.IPAddress -notlike "127.*" -and
      $_.IPAddress -notlike "169.254.*" -and
      $_.IPAddress -notlike "192.168.182.*" -and
      $_.IPAddress -notlike "192.168.254.*"
    } |
    Sort-Object -Property InterfaceMetric |
    Select-Object -First 1

  if (-not $preferred) {
    throw "Could not auto-detect a LAN IPv4 address. Pass -HostIp manually."
  }

  return $preferred.IPAddress
}

if ([string]::IsNullOrWhiteSpace($HostIp)) {
  $HostIp = Get-DefaultLanIp
}

$argsList = @(
  "-3.10",
  "-m",
  "integrations.xiaozhi_server.render_config",
  "--host-ip",
  $HostIp,
  "--repo-root",
  (Get-Location).Path
)

if (-not [string]::IsNullOrWhiteSpace($Output)) {
  $argsList += @("--output", $Output)
}

Write-Host "Rendering XiaoZhi config for host IP $HostIp"
& py @argsList
```

- [ ] **Step 4: Add `scripts/setup_xiaozhi_server.ps1`**

Create `scripts/setup_xiaozhi_server.ps1`:

```powershell
$ErrorActionPreference = "Stop"

param(
  [string]$Destination = ".run\xiaozhi-esp32-server",
  [switch]$Force
)

$zipUrl = "https://github.com/xinnan-tech/xiaozhi-esp32-server/archive/refs/heads/main.zip"
$runDir = Split-Path -Parent $Destination
$zipPath = Join-Path $runDir "xiaozhi-esp32-server-main.zip"
$extractDir = Join-Path $runDir "xiaozhi-esp32-server-main"

if ((Test-Path $Destination) -and -not $Force) {
  Write-Host "XiaoZhi server already exists at $Destination"
  exit 0
}

if (Test-Path $Destination) {
  Remove-Item -Recurse -Force -LiteralPath $Destination
}
if (Test-Path $extractDir) {
  Remove-Item -Recurse -Force -LiteralPath $extractDir
}

New-Item -ItemType Directory -Force -Path $runDir | Out-Null
Write-Host "Downloading $zipUrl"
Invoke-WebRequest -UseBasicParsing $zipUrl -OutFile $zipPath

Write-Host "Extracting XiaoZhi server"
Expand-Archive -Force -LiteralPath $zipPath -DestinationPath $runDir
Move-Item -LiteralPath $extractDir -Destination $Destination

$serverDir = Join-Path $Destination "main\xiaozhi-server"
$dataDir = Join-Path $serverDir "data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

Write-Host "Prepared XiaoZhi server at $serverDir"
Write-Host "Next: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\render_xiaozhi_config.ps1"
```

- [ ] **Step 5: Add startup and URL scripts**

Create `scripts/start_buddy_brain.ps1`:

```powershell
$ErrorActionPreference = "Stop"

param(
  [int]$Port = 8010
)

if (-not (Test-Path ".env")) {
  Write-Warning ".env was not found. Buddy Brain may fail if OPENAI_API_KEY is not set in the environment."
}

Write-Host "Starting Buddy Brain on 0.0.0.0:$Port"
& py -3.10 -m uvicorn buddy_brain.app:app --host 0.0.0.0 --port $Port
```

Create `scripts/start_xiaozhi_server.ps1`:

```powershell
$ErrorActionPreference = "Stop"

param(
  [string]$ServerDir = ".run\xiaozhi-esp32-server\main\xiaozhi-server",
  [string]$CondaEnv = "xiaozhi-esp32-server"
)

if (-not (Test-Path (Join-Path $ServerDir "app.py"))) {
  throw "XiaoZhi server app.py not found. Run .\scripts\setup_xiaozhi_server.ps1 first."
}

if (-not (Test-Path (Join-Path $ServerDir "data\.config.yaml"))) {
  throw "XiaoZhi data\.config.yaml not found. Run .\scripts\render_xiaozhi_config.ps1 first."
}

Write-Host "Starting XiaoZhi server from $ServerDir with conda env $CondaEnv"
Push-Location $ServerDir
try {
  & conda run -n $CondaEnv python app.py
}
finally {
  Pop-Location
}
```

Create `scripts/print_local_demo_urls.ps1`:

```powershell
$ErrorActionPreference = "Stop"

param(
  [string]$HostIp = ""
)

function Get-DefaultLanIp {
  $preferred = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
      $_.IPAddress -notlike "127.*" -and
      $_.IPAddress -notlike "169.254.*" -and
      $_.IPAddress -notlike "192.168.182.*" -and
      $_.IPAddress -notlike "192.168.254.*"
    } |
    Sort-Object -Property InterfaceMetric |
    Select-Object -First 1

  if (-not $preferred) {
    throw "Could not auto-detect a LAN IPv4 address. Pass -HostIp manually."
  }

  return $preferred.IPAddress
}

if ([string]::IsNullOrWhiteSpace($HostIp)) {
  $HostIp = Get-DefaultLanIp
}

Write-Host "Buddy Brain health: http://$HostIp:8010/health"
Write-Host "Buddy Brain OpenAI base_url: http://$HostIp:8010/v1"
Write-Host "XiaoZhi OTA URL: http://$HostIp:8003/xiaozhi/ota/"
Write-Host "XiaoZhi WebSocket URL: ws://$HostIp:8000/xiaozhi/v1/"
Write-Host "Firmware OTA value, if flashing is needed: CONFIG_OTA_URL=http://$HostIp:8003/xiaozhi/ota/"
```

- [ ] **Step 6: Run script validation tests and PowerShell parse checks**

Run:

```powershell
py -3.10 -m pytest tests/test_xiaozhi_scripts.py -v
powershell -NoProfile -Command "[scriptblock]::Create((Get-Content -Raw scripts/render_xiaozhi_config.ps1)) | Out-Null; [scriptblock]::Create((Get-Content -Raw scripts/setup_xiaozhi_server.ps1)) | Out-Null; [scriptblock]::Create((Get-Content -Raw scripts/start_buddy_brain.ps1)) | Out-Null; [scriptblock]::Create((Get-Content -Raw scripts/start_xiaozhi_server.ps1)) | Out-Null; [scriptblock]::Create((Get-Content -Raw scripts/print_local_demo_urls.ps1)) | Out-Null; 'Parse OK'"
```

Expected: pytest passes and PowerShell prints `Parse OK`.

- [ ] **Step 7: Commit**

Run:

```powershell
git add scripts/render_xiaozhi_config.ps1 scripts/setup_xiaozhi_server.ps1 scripts/start_buddy_brain.ps1 scripts/start_xiaozhi_server.ps1 scripts/print_local_demo_urls.ps1 tests/test_xiaozhi_scripts.py
git commit -m "feat: add xiaozhi operator scripts"
```

---

### Task 3: Bridge Runbook Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes:
  - Scripts from Task 2.
  - Renderer from Task 1.
- Produces:
  - Operator instructions for local bridge setup and hardware pause points.

- [ ] **Step 1: Add README bridge section**

Append this section to `README.md`:

````markdown
## XiaoZhi Local Bridge

This phase keeps the ESP32 firmware and XiaoZhi device protocol, but routes XiaoZhi server LLM calls to Buddy Brain.

Local URLs for the current Windows host:

```text
Buddy Brain: http://192.168.2.9:8010
Buddy Brain OpenAI base_url: http://192.168.2.9:8010/v1
XiaoZhi WebSocket: ws://192.168.2.9:8000/xiaozhi/v1/
XiaoZhi OTA: http://192.168.2.9:8003/xiaozhi/ota/
```

Print the current URLs:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\print_local_demo_urls.ps1
```

Prepare the XiaoZhi server runtime source under `.run/`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_xiaozhi_server.ps1
```

Render XiaoZhi `data/.config.yaml`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\render_xiaozhi_config.ps1 -HostIp 192.168.2.9
```

Start Buddy Brain in terminal A:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_brain.ps1
```

Smoke test Buddy Brain in terminal B:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_chat.ps1
```

Start XiaoZhi server in terminal C after its conda environment and dependencies are installed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_xiaozhi_server.ps1
```

The generated XiaoZhi config sets:

```yaml
selected_module:
  LLM: BuddyBrainLLM
  Memory: nomem
  Intent: nointent
```

Hardware routing pause point:

- Do not flash firmware until Buddy Brain and XiaoZhi server both start successfully.
- The current ESP32 firmware still uses `https://api.tenclass.net/xiaozhi/ota/`.
- If no runtime OTA override is available, firmware must be rebuilt for `bread-compact-wifi-lcd` with `CONFIG_OTA_URL=http://192.168.2.9:8003/xiaozhi/ota/`.
- When flashing is needed, stop and ask the user to plug in USB and press `BOOT` / `RESET`.
````

- [ ] **Step 2: Verify README mentions bridge commands**

Run:

```powershell
rg -n "XiaoZhi Local Bridge|render_xiaozhi_config|start_xiaozhi_server|CONFIG_OTA_URL" README.md
```

Expected: all four patterns are found.

- [ ] **Step 3: Run full unit tests**

Run:

```powershell
py -3.10 -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

Run:

```powershell
git add README.md
git commit -m "docs: add xiaozhi bridge runbook"
```

---

### Task 4: Local Bridge Smoke Preparation

**Files:**
- Modify only if tests expose a concrete issue:
  - `integrations/xiaozhi_server/render_config.py`
  - `scripts/*.ps1`
  - `README.md`

**Interfaces:**
- Consumes:
  - Tasks 1-3.
- Produces:
  - Generated ignored runtime config under `.run/xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml`.
  - Verified test suite.

- [ ] **Step 1: Render config for current LAN IP**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\render_xiaozhi_config.ps1 -HostIp 192.168.2.9
```

Expected: prints a path ending in `.run\xiaozhi-esp32-server\main\xiaozhi-server\data\.config.yaml`.

- [ ] **Step 2: Verify generated config content**

Run:

```powershell
Get-Content -Raw -Encoding UTF8 .run\xiaozhi-esp32-server\main\xiaozhi-server\data\.config.yaml
```

Expected content includes:

```text
websocket: ws://192.168.2.9:8000/xiaozhi/v1/
base_url: http://192.168.2.9:8010/v1
Memory: nomem
Intent: nointent
```

- [ ] **Step 3: Run full tests**

Run:

```powershell
py -3.10 -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 4: Confirm secrets are not tracked**

Run:

```powershell
git grep -n -E "sk-[A-Za-z0-9_-]{8,}|OPENAI_API_KEY=.*[A-Za-z0-9]" HEAD
```

Expected: no tracked secret values. `.env.example` may contain `OPENAI_API_KEY=` with an empty value only.

- [ ] **Step 5: Commit if fixes were needed**

If files changed, run:

```powershell
git add integrations scripts README.md tests
git commit -m "fix: prepare xiaozhi bridge smoke path"
```

Expected: no commit is required if the previous tasks already work.

---

## Final Verification

- [ ] Run:

```powershell
py -3.10 -m pytest -v
```

Expected: all tests pass.

- [ ] Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\print_local_demo_urls.ps1 -HostIp 192.168.2.9
```

Expected: prints Buddy Brain health URL, Buddy Brain OpenAI base URL, XiaoZhi OTA URL, XiaoZhi WebSocket URL, and `CONFIG_OTA_URL`.

- [ ] Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\render_xiaozhi_config.ps1 -HostIp 192.168.2.9
```

Expected: generates `.run\xiaozhi-esp32-server\main\xiaozhi-server\data\.config.yaml`.

- [ ] Run:

```powershell
git status --short --branch
```

Expected: implementation branch is clean except ignored `.run/`, `.env`, and `data/`.

## Hardware Handoff After This Plan

After the bridge assets pass local verification, the next human-assisted step is:

1. Start Buddy Brain.
2. Start XiaoZhi server.
3. Confirm XiaoZhi logs show local OTA and WebSocket URLs.
4. Pause and ask the user to plug the ESP32 board into USB.
5. Read serial and chip information again.
6. Try any available non-flashing OTA override first.
7. If flashing is required, confirm port, chip, flash size, and exact OTA URL before any flash command.

