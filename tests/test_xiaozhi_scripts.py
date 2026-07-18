import hashlib
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

SCRIPTS = [
    "backup_local_demo_data.ps1",
    "backup_v05_runtime.ps1",
    "check_local_demo_status.ps1",
    "render_xiaozhi_config.ps1",
    "check_xiaozhi_dependencies.ps1",
    "setup_xiaozhi_server.ps1",
    "start_buddy_core.ps1",
    "start_buddy_gateway.ps1",
    "start_buddy_brain.ps1",
    "start_xiaozhi_server.ps1",
    "stop_local_demo.ps1",
    "print_local_demo_urls.ps1",
    "smoke_chat.ps1",
    "smoke_gateway_audio_capture.ps1",
    "smoke_gateway_asr_text_loop.ps1",
    "smoke_gateway_voice_loop.ps1",
    "smoke_gateway_text_loop.ps1",
    "smoke_two_devices.ps1",
    "scan_staged_secrets.ps1",
]


def run_powershell(command: str, *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    ps_command = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "$OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        + command
    )
    env = os.environ.copy()
    env.pop("PYTEST_CURRENT_TEST", None)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            "PowerShell command failed with exit code "
            f"{result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or "") + (result.stdout or "")


def test_xiaozhi_scripts_exist_and_are_ascii_safe():
    for script_name in SCRIPTS:
        path = SCRIPTS_DIR / script_name
        assert path.exists(), f"missing {path}"
        text = path.read_text(encoding="utf-8")
        text.encode("ascii")
        assert '$ErrorActionPreference = "Stop"' in text


def test_smoke_chat_sends_debug_device_metadata():
    text = (SCRIPTS_DIR / "smoke_chat.ps1").read_text(encoding="utf-8")

    assert "metadata = @{" in text
    assert '$DeviceId = "debug-smoke-chat"' in text
    assert '$SessionId = "debug-smoke-session"' in text


def test_smoke_chat_accepts_device_metadata_parameters():
    text = (SCRIPTS_DIR / "smoke_chat.ps1").read_text(encoding="utf-8")

    assert "[string]$DeviceId" in text
    assert "[string]$ClientId" in text
    assert "[string]$SessionId" in text
    assert "device_id = $DeviceId" in text
    assert "client_id = $ClientId" in text
    assert "session_id = $SessionId" in text


def test_smoke_two_devices_script_runs_two_distinct_debug_devices():
    text = (SCRIPTS_DIR / "smoke_two_devices.ps1").read_text(encoding="utf-8")

    assert 'DeviceA = "debug-device-a"' in text
    assert 'DeviceB = "debug-device-b"' in text
    assert "smoke_chat.ps1" in text
    assert "-DeviceId $DeviceA" in text
    assert "-DeviceId $DeviceB" in text
    assert "[uri]::EscapeDataString($DeviceA)" in text
    assert "[uri]::EscapeDataString($DeviceB)" in text
    assert "/memory?device_id=" in text


def test_smoke_two_devices_script_prints_full_encoded_memory_urls(tmp_path: Path):
    source_script = SCRIPTS_DIR / "smoke_two_devices.ps1"
    script_path = tmp_path / "smoke_two_devices.ps1"
    smoke_chat_path = tmp_path / "smoke_chat.ps1"
    script_path.write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")
    smoke_chat_path.write_text(
        "\n".join(
            [
                "param(",
                "  [string]$DeviceId,",
                "  [string]$ClientId,",
                "  [string]$SessionId,",
                "  [string]$Url",
                ")",
                '$ErrorActionPreference = "Stop"',
                'Write-Host ("stub:{0}:{1}:{2}:{3}" -f $DeviceId, $ClientId, $SessionId, $Url)',
            ]
        ),
        encoding="utf-8",
    )

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f"& '{script_path}' -DeviceA 'fc:01' -DeviceB 'debug b' -MemoryBaseUrl 'http://127.0.0.1:8010/memory'",
                "}",
            ]
        )
    )

    assert "Memory URL A: http://127.0.0.1:8010/memory?device_id=fc%3A01" in result.stdout
    assert "Memory URL B: http://127.0.0.1:8010/memory?device_id=debug%20b" in result.stdout


def test_setup_paths_require_strict_child_directory_under_run():
    script_path = SCRIPTS_DIR / "setup_xiaozhi_server.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; Get-XiaoZhiSetupPaths -Destination '.run' | ConvertTo-Json -Compress }}",
        check=False,
    )

    assert result.returncode != 0
    assert "strict child" in combined_output(result)


def test_setup_paths_keep_all_runtime_artifacts_inside_repo_run():
    script_path = SCRIPTS_DIR / "setup_xiaozhi_server.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; Get-XiaoZhiSetupPaths -Destination '.run\\xiaozhi-esp32-server' | ConvertTo-Json -Compress }}"
    )
    paths = json.loads(result.stdout)

    assert paths["DestinationPath"].endswith("\\.run\\xiaozhi-esp32-server")
    assert paths["DestinationPath"] != paths["RunRoot"]
    assert paths["ZipPath"].startswith(paths["RunRoot"] + "\\")
    assert paths["ExtractDir"].startswith(paths["RunRoot"] + "\\")


def test_setup_entrypoint_flow_uses_stubbed_download_and_extract_under_repo_run():
    script_path = SCRIPTS_DIR / "setup_xiaozhi_server.ps1"
    unique_root = REPO_ROOT / ".run" / f"pytest-xiaozhi-setup-{uuid.uuid4().hex}"
    destination = unique_root / "server"
    destination_suffix = f"\\.run\\{unique_root.name}\\server"
    zip_path = unique_root / "xiaozhi-esp32-server-main.zip"
    destination_arg = str(Path(".run") / unique_root.name / "server").replace("/", "\\")

    if unique_root.exists():
        shutil.rmtree(unique_root)

    try:
        result = run_powershell(
            "\n".join(
                [
                    "& {",
                    f". '{script_path}'",
                    "function Invoke-WebRequest {",
                    "  param([string]$Uri, [string]$OutFile)",
                    "  Set-Content -Path $OutFile -Value 'fake zip'",
                    "}",
                    "function Expand-Archive {",
                    "  param([string]$LiteralPath, [string]$DestinationPath)",
                    "  $server = Join-Path $DestinationPath 'xiaozhi-esp32-server-main\\main\\xiaozhi-server'",
                    "  New-Item -ItemType Directory -Force -Path (Join-Path $server 'core\\providers\\llm\\openai') | Out-Null",
                    "  Set-Content -Path (Join-Path $server 'core\\providers\\llm\\openai\\openai.py') -Encoding utf8 -Value @'",
                    "class LLMProvider:",
                    "    def __init__(self, config):",
                    "        self.api_key = config.get(\"api_key\")",
                    "    def _apply_thinking_disabled(self, request_params):",
                    "        pass",
                    "    def response(self, session_id, dialogue, **kwargs):",
                    "        request_params = {}",
                    "        self._apply_thinking_disabled(request_params)",
                    "        responses = self.client.chat.completions.create(**request_params)",
                    "    def response_with_functions(self, session_id, dialogue, functions=None, **kwargs):",
                    "        request_params = {}",
                    "        self._apply_thinking_disabled(request_params)",
                    "        stream = self.client.chat.completions.create(**request_params)",
                    "'@",
                    "  Set-Content -Path (Join-Path $server 'core\\connection.py') -Encoding utf8 -Value @'",
                    "class ConnectionHandler:",
                    "    def chat(self):",
                    "        response_message = []",
                    "        llm_responses = self.llm.response_with_functions(",
                    "            self.session_id,",
                    "            self.dialogue.get_llm_dialogue_with_memory(memory_str, self.config.get(\"voiceprint\", {})),",
                    "            functions=functions,",
                    "        )",
                    "        llm_responses = self.llm.response(",
                    "            self.session_id,",
                    "            self.dialogue.get_llm_dialogue_with_memory(memory_str, self.config.get(\"voiceprint\", {})),",
                    "        )",
                    "'@",
                    "}",
                    f"$destination = '{destination_arg}'",
                    "$paths = Get-XiaoZhiSetupPaths -Destination $destination",
                    "Invoke-XiaoZhiSetup -Destination $destination -Force",
                    "[pscustomobject]@{",
                    "  DestinationExists = Test-Path -LiteralPath $paths.DestinationPath",
                    "  DataDirExists = Test-Path -LiteralPath (Join-Path $paths.DestinationPath 'main\\xiaozhi-server\\data')",
                    "  ZipExists = Test-Path -LiteralPath $paths.ZipPath",
                    "  ExtractDirExists = Test-Path -LiteralPath $paths.ExtractDir",
                    "  DestinationPath = $paths.DestinationPath",
                    "  ZipPath = $paths.ZipPath",
                    "  RunRoot = $paths.RunRoot",
                    "  DataDir = Join-Path $paths.DestinationPath 'main\\xiaozhi-server\\data'",
                    "} | ConvertTo-Json -Compress",
                    "}",
                ]
            )
        )
        payload = json.loads(result.stdout.splitlines()[-1])

        assert payload["DestinationExists"] is True
        assert payload["DataDirExists"] is True
        assert payload["ZipExists"] is True
        assert payload["ExtractDirExists"] is False
        assert payload["DestinationPath"].endswith(destination_suffix)
        assert payload["DataDir"].endswith(destination_suffix + "\\main\\xiaozhi-server\\data")
        assert payload["ZipPath"].startswith(payload["RunRoot"] + "\\")
        assert payload["ZipPath"].endswith(f"\\.run\\{unique_root.name}\\xiaozhi-esp32-server-main.zip")
        assert zip_path.read_text(encoding="utf-8").strip() == "fake zip"
    finally:
        if unique_root.exists():
            shutil.rmtree(unique_root)


def test_setup_patch_adds_xiaozhi_device_metadata_forwarding(tmp_path):
    script_path = SCRIPTS_DIR / "setup_xiaozhi_server.ps1"
    server_dir = tmp_path / "xiaozhi-server"
    provider_path = server_dir / "core" / "providers" / "llm" / "openai" / "openai.py"
    connection_path = server_dir / "core" / "connection.py"
    provider_path.parent.mkdir(parents=True)
    connection_path.parent.mkdir(parents=True, exist_ok=True)
    provider_path.write_text(
        "\n".join(
            [
                "class LLMProvider:",
                "    def __init__(self, config):",
                "        self.api_key = config.get(\"api_key\")",
                "    def _apply_thinking_disabled(self, request_params):",
                "        pass",
                "    def response(self, session_id, dialogue, **kwargs):",
                "        request_params = {}",
                "        self._apply_thinking_disabled(request_params)",
                "        responses = self.client.chat.completions.create(**request_params)",
                "    def response_with_functions(self, session_id, dialogue, functions=None, **kwargs):",
                "        request_params = {}",
                "        self._apply_thinking_disabled(request_params)",
                "        stream = self.client.chat.completions.create(**request_params)",
            ]
        ),
        encoding="utf-8",
    )
    connection_path.write_text(
        "\n".join(
            [
                "class ConnectionHandler:",
                "    def chat(self):",
                "        response_message = []",
                "        llm_responses = self.llm.response_with_functions(",
                "            self.session_id,",
                "            self.dialogue.get_llm_dialogue_with_memory(memory_str, self.config.get(\"voiceprint\", {})),",
                "            functions=functions,",
                "        )",
                "        llm_responses = self.llm.response(",
                "            self.session_id,",
                "            self.dialogue.get_llm_dialogue_with_memory(memory_str, self.config.get(\"voiceprint\", {})),",
                "        )",
            ]
        ),
        encoding="utf-8",
    )

    for _ in range(2):
        run_powershell(
            f"& {{ . '{script_path}'; Update-XiaoZhiDeviceMetadataPatch -ServerDir '{server_dir}' }}"
        )

    provider_text = provider_path.read_text(encoding="utf-8")
    connection_text = connection_path.read_text(encoding="utf-8")
    assert provider_text.count("forward_device_metadata") == 3
    assert provider_text.count("_apply_device_metadata(request_params, session_id, kwargs)") == 2
    assert "metadata[\"device_id\"] = device_id" in provider_text
    assert connection_text.count("llm_kwargs = {}") == 1
    assert connection_text.count("**llm_kwargs") == 2


def test_render_private_ipv4_helper_matches_rfc1918_only():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; @('10.1.2.3', '192.168.1.5', '172.16.0.1', '172.31.9.9', '172.200.1.1', '8.8.8.8') | ForEach-Object {{ [pscustomobject]@{{ Ip = $_; Private = Test-PrivateIPv4 $_ }} }} | ConvertTo-Json -Compress }}"
    )
    rows = {row["Ip"]: row["Private"] for row in json.loads(result.stdout)}

    assert rows["10.1.2.3"] is True
    assert rows["192.168.1.5"] is True
    assert rows["172.16.0.1"] is True
    assert rows["172.31.9.9"] is True
    assert rows["172.200.1.1"] is False
    assert rows["8.8.8.8"] is False


def test_render_auto_detection_prefers_physical_lan_ip_over_virtual_adapters():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "@(",
                "  [pscustomobject]@{ IPAddress = '192.168.254.1'; InterfaceAlias = 'VMware Network Adapter VMnet8' },",
                "  [pscustomobject]@{ IPAddress = '192.168.0.101'; InterfaceAlias = 'WLAN' },",
                "  [pscustomobject]@{ IPAddress = '10.0.0.8'; InterfaceAlias = 'vEthernet (Default Switch)' }",
                ") | Select-PreferredLanIp",
                "}",
            ]
        )
    )

    assert result.stdout.strip() == "192.168.0.101"


def test_render_auto_detection_uses_first_private_ip_when_only_strings_are_available():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; @('172.200.1.1', '10.0.0.5', '192.168.2.20') | Select-PreferredLanIp }}"
    )

    assert result.stdout.strip() == "10.0.0.5"


def test_render_script_preserves_manual_host_ip_and_repo_root():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:py { param([Parameter(ValueFromRemainingArguments = $true)] $Args) $Args | ConvertTo-Json -Compress }",
                "'TTS_HTTP_URL','TTS_MODEL','TTS_API_KEY','TTS_VOICE','TTS_LANGUAGE' | ForEach-Object { [Environment]::SetEnvironmentVariable($_, 'test-value', 'Process') }",
                "[Environment]::SetEnvironmentVariable('TTS_PROVIDER', 'buddy_qwen_http', 'Process')",
                "[Environment]::SetEnvironmentVariable('TTS_TIMEOUT_SECONDS', '7.5', 'Process')",
                f"& '{script_path}' -HostIp '192.168.0.101'",
                "}",
            ]
        ),
        cwd=REPO_ROOT.parent,
    )

    args = json.loads(result.stdout.splitlines()[-1])
    repo_root_arg = args[args.index("--repo-root") + 1]

    assert "192.168.0.101" in args
    assert Path(repo_root_arg) == REPO_ROOT
    assert not repo_root_arg.endswith("\\AI Buddy\\.worktrees")


def test_render_script_rejects_invalid_manual_host_ip_before_calling_py():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"

    for host_ip in ("127.0.0.1", "8.8.8.8", "169.254.1.2", "localhost"):
        result = run_powershell(
            "\n".join(
                [
                    "& {",
                    "function global:py { throw 'py should not be called' }",
                    f"& '{script_path}' -HostIp '{host_ip}'",
                    "}",
                ]
            ),
            check=False,
        )

        assert result.returncode != 0, host_ip
        combined = combined_output(result).lower()
        assert "hostip" in combined
        assert "py should not be called" not in combined


def test_render_script_rejects_non_finite_asr_timeout():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"

    for timeout in ("NaN", "Infinity", "-Infinity"):
        result = run_powershell(
            "\n".join(
                [
                    "& {",
                    f". '{script_path}'",
                    "'ASR_PROVIDER','ASR_HTTP_URL','ASR_MODEL','ASR_API_KEY' | ForEach-Object { [Environment]::SetEnvironmentVariable($_, 'test-value', 'Process') }",
                    f"[Environment]::SetEnvironmentVariable('ASR_TIMEOUT_SECONDS', '{timeout}', 'Process')",
                    "Assert-LiveAsrEnvironment",
                    "}",
                ]
            ),
            check=False,
        )

        assert result.returncode != 0, timeout
        assert "ASR_TIMEOUT_SECONDS" in combined_output(result)


def test_render_script_rejects_output_outside_runtime_before_calling_py(tmp_path: Path):
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"
    output = tmp_path / "outside" / ".config.yaml"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:py { throw 'py should not be called' }",
                f"& '{script_path}' -HostIp '192.168.2.9' -Output '{output}'",
                "}",
            ]
        ),
        check=False,
    )

    assert result.returncode != 0
    combined = combined_output(result).lower()
    assert "xiaozhi_server" in combined
    assert "py should not be called" not in combined


def test_render_script_allows_custom_output_under_runtime_data():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"
    output = REPO_ROOT / "xiaozhi_server" / "data" / "custom.config.yaml"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:py { param([Parameter(ValueFromRemainingArguments = $true)] $Args) $Args | ConvertTo-Json -Compress }",
                "'TTS_HTTP_URL','TTS_MODEL','TTS_API_KEY','TTS_VOICE','TTS_LANGUAGE' | ForEach-Object { [Environment]::SetEnvironmentVariable($_, 'test-value', 'Process') }",
                "[Environment]::SetEnvironmentVariable('TTS_PROVIDER', 'buddy_qwen_http', 'Process')",
                "[Environment]::SetEnvironmentVariable('TTS_TIMEOUT_SECONDS', '7.5', 'Process')",
                f"& '{script_path}' -HostIp '192.168.2.9' -Output '{output}'",
                "}",
            ]
        )
    )
    args = json.loads(result.stdout.splitlines()[-1])

    output_arg = args[args.index("--output") + 1]
    assert output_arg.endswith("\\xiaozhi_server\\data\\custom.config.yaml")


def test_render_script_rejects_nested_output_under_runtime_data_before_calling_py():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"
    output = REPO_ROOT / "xiaozhi_server" / "data" / "nested" / "custom.config.yaml"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:py { throw 'py should not be called' }",
                f"& '{script_path}' -HostIp '192.168.2.9' -Output '{output}'",
                "}",
            ]
        ),
        check=False,
    )

    assert result.returncode != 0
    combined = combined_output(result).lower()
    assert "xiaozhi_server" in combined
    assert "py should not be called" not in combined


def test_demo_url_script_auto_detection_prefers_physical_lan_ip_over_virtual_adapters():
    script_path = SCRIPTS_DIR / "print_local_demo_urls.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "@(",
                "  [pscustomobject]@{ IPAddress = '192.168.254.1'; InterfaceAlias = 'VMware Network Adapter VMnet8' },",
                "  [pscustomobject]@{ IPAddress = '192.168.0.101'; InterfaceAlias = 'WLAN' },",
                "  [pscustomobject]@{ IPAddress = '10.0.0.8'; InterfaceAlias = 'vEthernet (Default Switch)' }",
                ") | Select-PreferredLanIp",
                "}",
            ]
        )
    )

    assert result.stdout.strip() == "192.168.0.101"


def test_demo_url_script_auto_detection_uses_first_private_ip_when_only_strings_are_available():
    script_path = SCRIPTS_DIR / "print_local_demo_urls.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; @('172.200.1.1', '10.0.0.5', '192.168.2.20') | Select-PreferredLanIp }}"
    )

    assert result.stdout.strip() == "10.0.0.5"


def test_demo_url_script_rejects_invalid_manual_host_ip_values():
    script_path = SCRIPTS_DIR / "print_local_demo_urls.ps1"

    for host_ip in ("127.0.0.1", "8.8.8.8", "169.254.1.2", "localhost"):
        result = run_powershell(
            f"& {{ . '{script_path}'; Invoke-PrintLocalDemoUrls -HostIp '{host_ip}' }}",
            check=False,
        )

        assert result.returncode != 0, host_ip
        assert "HostIp" in combined_output(result)


def test_demo_url_script_prints_expected_urls_for_valid_manual_host_ip():
    script_path = SCRIPTS_DIR / "print_local_demo_urls.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; Invoke-PrintLocalDemoUrls -HostIp '192.168.0.101' }}"
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    assert lines == [
        "Buddy Core health: http://192.168.0.101:8010/health",
        "Buddy Core OpenAI base_url: http://192.168.0.101:8010/v1",
        "XiaoZhi OTA URL: http://192.168.0.101:8003/xiaozhi/ota/",
        "XiaoZhi WebSocket URL: ws://192.168.0.101:8000/xiaozhi/v1/",
        "Firmware OTA value, if flashing is needed: CONFIG_OTA_URL=http://192.168.0.101:8003/xiaozhi/ota/",
    ]


def test_start_buddy_brain_script_uses_fixed_host_and_port_by_default():
    script_path = SCRIPTS_DIR / "start_buddy_brain.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:conda { param([Parameter(ValueFromRemainingArguments = $true)] $Args) $Args | ConvertTo-Json -Compress }",
                f". '{script_path}'",
                "function Test-BuddyCoreHealthy { param([int]$Port) return $false }",
                "Invoke-StartBuddyCore -Port 8010",
                "}",
            ]
        )
    )
    args = json.loads(result.stdout.splitlines()[-1])

    assert [str(arg) for arg in args] == [
        "run",
        "--no-capture-output",
        "-n",
        "xiaozhi-env",
        "python",
        "-m",
        "uvicorn",
        "buddy_brain.app:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8010",
    ]


def test_start_buddy_brain_script_exits_when_buddy_core_already_running():
    script_path = SCRIPTS_DIR / "start_buddy_brain.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "function Test-BuddyCoreHealthy { param([int]$Port) return $true }",
                "function global:conda { throw 'conda should not be called' }",
                "Invoke-StartBuddyCore -Port 8010",
                "}",
            ]
        )
    )

    assert "already running" in result.stdout
    assert "conda should not be called" not in combined_output(result)


def test_start_buddy_brain_script_rejects_non_contract_port_before_calling_conda():
    script_path = SCRIPTS_DIR / "start_buddy_brain.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:conda { throw 'conda should not be called' }",
                f"& '{script_path}' -Port 8011",
                "}",
            ]
        ),
        check=False,
    )

    assert result.returncode != 0
    combined = combined_output(result).lower()
    assert "8010" in combined
    assert "conda should not be called" not in combined


def test_start_buddy_core_script_delegates_to_existing_buddy_core_entrypoint():
    text = (SCRIPTS_DIR / "start_buddy_core.ps1").read_text(encoding="utf-8")

    assert "start_buddy_brain.ps1" in text
    assert "Invoke-StartBuddyCore" in text
    assert 'CondaEnv = "xiaozhi-env"' in text


def test_start_buddy_gateway_script_invokes_gateway_server_with_overrides():
    script_path = SCRIPTS_DIR / "start_buddy_gateway.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:conda { param([Parameter(ValueFromRemainingArguments = $true)] $Args) $Args | ConvertTo-Json -Compress }",
                f". '{script_path}'",
                "Invoke-StartBuddyGateway -BindHost '127.0.0.1' -HttpPort 18003 -WebSocketPort 18000 -AdvertiseHost '192.168.0.101' -BuddyCoreBaseUrl 'http://127.0.0.1:18010' -AudioArtifactDir 'tmp\\gateway-audio' -AudioSessionLimit 3 -AsrProvider 'http_file' -AsrHttpUrl 'https://asr.example.test/compatible-mode/v1' -AsrModel 'qwen3-asr-flash-2025-09-08' -AsrTimeoutSeconds 45 -TtsProvider 'dashscope_qwen_http' -TtsHttpUrl 'https://tts.example.test/api/v1' -TtsModel 'qwen3-tts-instruct-flash' -TtsVoice 'Cherry' -TtsLanguage 'English' -TtsTimeoutSeconds 30 -TtsFrameDelayMs 5 -SendSttToDevice",
                "}",
            ]
        )
    )
    args = json.loads(result.stdout.splitlines()[-1])

    assert [str(arg) for arg in args] == [
        "run",
        "--no-capture-output",
        "-n",
        "xiaozhi-env",
        "python",
        "-m",
        "buddy_gateway.server",
        "--host",
        "127.0.0.1",
        "--http-port",
        "18003",
        "--websocket-port",
        "18000",
        "--advertise-host",
        "192.168.0.101",
        "--buddy-core-base-url",
        "http://127.0.0.1:18010",
        "--audio-artifact-dir",
        "tmp\\gateway-audio",
        "--audio-session-limit",
        "3",
        "--asr-provider",
        "http_file",
        "--asr-http-url",
        "https://asr.example.test/compatible-mode/v1",
        "--asr-model",
        "qwen3-asr-flash-2025-09-08",
        "--asr-timeout-seconds",
        "45",
        "--tts-provider",
        "dashscope_qwen_http",
        "--tts-http-url",
        "https://tts.example.test/api/v1",
        "--tts-model",
        "qwen3-tts-instruct-flash",
        "--tts-voice",
        "Cherry",
        "--tts-language",
        "English",
        "--tts-timeout-seconds",
        "30",
        "--tts-frame-delay-ms",
        "5",
        "--send-stt-to-device",
    ]


def test_start_buddy_gateway_script_uses_xiaozhi_compatible_ports_by_default():
    text = (SCRIPTS_DIR / "start_buddy_gateway.ps1").read_text(encoding="utf-8")

    assert "[int]$HttpPort = 8003" in text
    assert "[int]$WebSocketPort = 8000" in text
    assert '[string]$BuddyCoreBaseUrl = "http://127.0.0.1:8010"' in text
    assert '[string]$TtsModel = ""' in text
    assert '[string]$TtsVoice = ""' in text
    assert 'CondaEnv = "xiaozhi-env"' in text


def test_start_buddy_gateway_script_auto_detects_physical_lan_advertise_host():
    script_path = SCRIPTS_DIR / "start_buddy_gateway.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:conda { param([Parameter(ValueFromRemainingArguments = $true)] $Args) $Args | ConvertTo-Json -Compress }",
                f". '{script_path}'",
                "function Get-NetIPAddress {",
                "  @(",
                "    [pscustomobject]@{ IPAddress = '192.168.254.1'; InterfaceAlias = 'VMware Network Adapter VMnet8' },",
                "    [pscustomobject]@{ IPAddress = '192.168.0.101'; InterfaceAlias = 'WLAN' },",
                "    [pscustomobject]@{ IPAddress = '10.0.0.8'; InterfaceAlias = 'vEthernet (Default Switch)' }",
                "  )",
                "}",
                "Invoke-StartBuddyGateway -HttpPort 18003 -WebSocketPort 18000",
                "}",
            ]
        )
    )
    args = json.loads(result.stdout.splitlines()[-1])

    assert args[args.index("--advertise-host") + 1] == "192.168.0.101"
    assert args[args.index("--buddy-core-base-url") + 1] == "http://127.0.0.1:8010"


def test_smoke_gateway_text_loop_injects_text_into_latest_session_and_prints_memory_url():
    script_path = SCRIPTS_DIR / "smoke_gateway_text_loop.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "$script:Calls = @()",
                "function New-MockWebResponse {",
                "  param([string]$Json)",
                "  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)",
                "  [pscustomobject]@{ RawContentStream = [System.IO.MemoryStream]::new($bytes) }",
                "}",
                "function Invoke-WebRequest {",
                "  param(",
                "    [string]$Uri,",
                "    [string]$Method = 'Get',",
                "    $Body,",
                "    [string]$ContentType,",
                "    [switch]$UseBasicParsing",
                "  )",
                "  $script:Calls += [pscustomobject]@{ Uri = $Uri; Method = $Method; Body = $Body; ContentType = $ContentType }",
                "  if ($Uri -like '*/debug/sessions' -and $Method -eq 'Get') {",
                "    return New-MockWebResponse '{\"session_count\":1,\"sessions\":[{\"session_id\":\"session-a\",\"device_id\":\"fc:01\",\"client_id\":\"client-a\"}]}'",
                "  }",
                "  if ($Uri -like '*/debug/sessions/session-a/inject-text') {",
                "    return New-MockWebResponse '{\"status\":\"ok\",\"assistant_text\":\"\\u6211\\u559c\\u6b22\\u82f9\\u679c\\u3002\"}'",
                "  }",
                "  throw \"unexpected uri $Uri\"",
                "}",
                "Invoke-SmokeGatewayTextLoop -GatewayBaseUrl 'http://127.0.0.1:8003' -MemoryBaseUrl 'http://127.0.0.1:8010/memory' -Text 'I like apples'",
                "$script:Calls | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )

    assert "Assistant: \u6211\u559c\u6b22\u82f9\u679c\u3002" in result.stdout
    assert "Memory URL: http://127.0.0.1:8010/memory?device_id=fc%3A01" in result.stdout
    calls = json.loads(result.stdout.splitlines()[-1])
    assert calls[0]["Uri"] == "http://127.0.0.1:8003/debug/sessions"
    assert calls[1]["Uri"] == "http://127.0.0.1:8003/debug/sessions/session-a/inject-text"
    assert json.loads(calls[1]["Body"]) == {"text": "I like apples"}


def test_smoke_gateway_audio_capture_decodes_latest_audio_session():
    script_path = SCRIPTS_DIR / "smoke_gateway_audio_capture.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "$script:Calls = @()",
                "function New-MockWebResponse {",
                "  param([string]$Json)",
                "  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)",
                "  [pscustomobject]@{ RawContentStream = [System.IO.MemoryStream]::new($bytes) }",
                "}",
                "function Invoke-WebRequest {",
                "  param(",
                "    [string]$Uri,",
                "    [string]$Method = 'Get',",
                "    $Body,",
                "    [string]$ContentType,",
                "    [switch]$UseBasicParsing",
                "  )",
                "  $script:Calls += [pscustomobject]@{ Uri = $Uri; Method = $Method; Body = $Body; ContentType = $ContentType }",
                "  if ($Uri -like '*/debug/audio/sessions' -and $Method -eq 'Get') {",
                "    return New-MockWebResponse '{\"session_count\":1,\"sessions\":[{\"session_id\":\"session-a\",\"device_id\":\"fc:01\",\"client_id\":\"client-a\",\"opus_frame_count\":3}]}'",
                "  }",
                "  if ($Uri -like '*/debug/sessions/session-a/decode-audio') {",
                "    return New-MockWebResponse '{\"status\":\"ok\",\"session_id\":\"session-a\",\"opus_frame_count\":3,\"decoded_frame_count\":3,\"decode_error_count\":0,\"wav_path\":\"data/gateway_audio/session-a/audio.wav\",\"audio_url\":\"http://127.0.0.1:8003/debug/sessions/session-a/audio.wav\"}'",
                "  }",
                "  throw \"unexpected uri $Uri\"",
                "}",
                "Invoke-SmokeGatewayAudioCapture -GatewayBaseUrl 'http://127.0.0.1:8003'",
                "$script:Calls | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )

    assert "Session: session-a" in result.stdout
    assert "Device: fc:01" in result.stdout
    assert "Opus frames: 3" in result.stdout
    assert "Decoded frames: 3" in result.stdout
    assert "Decode errors: 0" in result.stdout
    assert "WAV path: data/gateway_audio/session-a/audio.wav" in result.stdout
    assert "Audio URL: http://127.0.0.1:8003/debug/sessions/session-a/audio.wav" in result.stdout
    calls = json.loads(result.stdout.splitlines()[-1])
    assert calls[0]["Uri"] == "http://127.0.0.1:8003/debug/audio/sessions"
    assert calls[1]["Uri"] == "http://127.0.0.1:8003/debug/sessions/session-a/decode-audio"


def test_smoke_gateway_asr_text_loop_transcribes_latest_session_and_prints_memory_url():
    script_path = SCRIPTS_DIR / "smoke_gateway_asr_text_loop.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "$script:Calls = @()",
                "function New-MockWebResponse {",
                "  param([string]$Json)",
                "  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)",
                "  [pscustomobject]@{ RawContentStream = [System.IO.MemoryStream]::new($bytes) }",
                "}",
                "function Invoke-WebRequest {",
                "  param(",
                "    [string]$Uri,",
                "    [string]$Method = 'Get',",
                "    $Body,",
                "    [string]$ContentType,",
                "    [switch]$UseBasicParsing",
                "  )",
                "  $script:Calls += [pscustomobject]@{ Uri = $Uri; Method = $Method; Body = $Body; ContentType = $ContentType }",
                "  if ($Uri -like '*/debug/sessions' -and $Method -eq 'Get') {",
                "    return New-MockWebResponse '{\"session_count\":1,\"sessions\":[{\"session_id\":\"session-a\",\"device_id\":\"fc:01\",\"client_id\":\"client-a\",\"audio_frame_count\":3}]}'",
                "  }",
                "  if ($Uri -like '*/debug/audio/sessions' -and $Method -eq 'Get') {",
                "    return New-MockWebResponse '{\"session_count\":1,\"sessions\":[{\"session_id\":\"session-a\",\"device_id\":\"fc:01\",\"client_id\":\"client-a\",\"opus_frame_count\":3}]}'",
                "  }",
                "  if ($Uri -like '*/debug/sessions/session-a/transcribe-audio') {",
                "    return New-MockWebResponse '{\"status\":\"ok\",\"turn_id\":\"asr-a\",\"transcript\":\"I like apples\",\"assistant_text\":\"Apple means ping guo.\",\"asr_provider\":\"http_file\"}'",
                "  }",
                "  throw \"unexpected uri $Uri\"",
                "}",
                "Invoke-SmokeGatewayAsrTextLoop -GatewayBaseUrl 'http://127.0.0.1:8003' -MemoryBaseUrl 'http://127.0.0.1:8010/memory'",
                "$script:Calls | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )

    assert "Session: session-a" in result.stdout
    assert "Transcript: I like apples" in result.stdout
    assert "Assistant: Apple means ping guo." in result.stdout
    assert "Memory URL: http://127.0.0.1:8010/memory?device_id=fc%3A01" in result.stdout
    calls = json.loads(result.stdout.splitlines()[-1])
    assert calls[0]["Uri"] == "http://127.0.0.1:8003/debug/sessions"
    assert calls[1]["Uri"] == "http://127.0.0.1:8003/debug/audio/sessions"
    assert calls[2]["Uri"] == "http://127.0.0.1:8003/debug/sessions/session-a/transcribe-audio"


def test_smoke_gateway_asr_text_loop_fails_when_transcription_status_is_not_ok():
    script_path = SCRIPTS_DIR / "smoke_gateway_asr_text_loop.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "function New-MockWebResponse {",
                "  param([string]$Json)",
                "  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)",
                "  [pscustomobject]@{ RawContentStream = [System.IO.MemoryStream]::new($bytes) }",
                "}",
                "function Invoke-WebRequest {",
                "  param(",
                "    [string]$Uri,",
                "    [string]$Method = 'Get',",
                "    $Body,",
                "    [string]$ContentType,",
                "    [switch]$UseBasicParsing",
                "  )",
                "  if ($Uri -like '*/debug/sessions' -and $Method -eq 'Get') {",
                "    return New-MockWebResponse '{\"session_count\":1,\"sessions\":[{\"session_id\":\"session-a\",\"device_id\":\"fc:01\",\"client_id\":\"client-a\",\"audio_frame_count\":3}]}'",
                "  }",
                "  if ($Uri -like '*/debug/audio/sessions' -and $Method -eq 'Get') {",
                "    return New-MockWebResponse '{\"session_count\":1,\"sessions\":[{\"session_id\":\"session-a\",\"device_id\":\"fc:01\",\"client_id\":\"client-a\",\"opus_frame_count\":3}]}'",
                "  }",
                "  if ($Uri -like '*/debug/sessions/session-a/transcribe-audio') {",
                "    return New-MockWebResponse '{\"status\":\"buddy_core_error\",\"error\":\"Buddy Core unavailable\",\"asr_provider\":\"qwen_chat_audio\"}'",
                "  }",
                "  throw \"unexpected uri $Uri\"",
                "}",
                "Invoke-SmokeGatewayAsrTextLoop -GatewayBaseUrl 'http://127.0.0.1:8003'",
                "}",
            ]
        ),
        check=False,
    )

    assert result.returncode != 0
    assert "buddy_core_error" in combined_output(result)
    assert "Buddy Core unavailable" in combined_output(result)


def test_smoke_gateway_asr_text_loop_uses_latest_live_session_not_stale_audio_artifact():
    script_path = SCRIPTS_DIR / "smoke_gateway_asr_text_loop.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "$script:Calls = @()",
                "function New-MockWebResponse {",
                "  param([string]$Json)",
                "  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)",
                "  [pscustomobject]@{ RawContentStream = [System.IO.MemoryStream]::new($bytes) }",
                "}",
                "function Invoke-WebRequest {",
                "  param(",
                "    [string]$Uri,",
                "    [string]$Method = 'Get',",
                "    $Body,",
                "    [string]$ContentType,",
                "    [switch]$UseBasicParsing",
                "  )",
                "  $script:Calls += [pscustomobject]@{ Uri = $Uri; Method = $Method; Body = $Body; ContentType = $ContentType }",
                "  if ($Uri -like '*/debug/sessions' -and $Method -eq 'Get') {",
                "    return New-MockWebResponse '{\"session_count\":1,\"sessions\":[{\"session_id\":\"session-live\",\"device_id\":\"fc:01\",\"client_id\":\"client-a\",\"audio_frame_count\":8}]}'",
                "  }",
                "  if ($Uri -like '*/debug/audio/sessions' -and $Method -eq 'Get') {",
                "    return New-MockWebResponse '{\"session_count\":2,\"sessions\":[{\"session_id\":\"session-stale\",\"device_id\":\"old-device\",\"client_id\":\"old-client\",\"opus_frame_count\":3},{\"session_id\":\"session-live\",\"device_id\":\"fc:01\",\"client_id\":\"client-a\",\"opus_frame_count\":8}]}'",
                "  }",
                "  if ($Uri -like '*/debug/sessions/session-live/transcribe-audio') {",
                "    return New-MockWebResponse '{\"status\":\"ok\",\"turn_id\":\"asr-a\",\"transcript\":\"hello\",\"assistant_text\":\"hi\",\"asr_provider\":\"qwen_chat_audio\"}'",
                "  }",
                "  throw \"unexpected uri $Uri\"",
                "}",
                "Invoke-SmokeGatewayAsrTextLoop -GatewayBaseUrl 'http://127.0.0.1:8003'",
                "$script:Calls | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )

    calls = json.loads(result.stdout.splitlines()[-1])
    assert calls[0]["Uri"] == "http://127.0.0.1:8003/debug/sessions"
    assert calls[1]["Uri"] == "http://127.0.0.1:8003/debug/audio/sessions"
    assert calls[2]["Uri"] == "http://127.0.0.1:8003/debug/sessions/session-live/transcribe-audio"


def test_smoke_gateway_voice_loop_reports_latest_completed_tts_turn():
    script_path = SCRIPTS_DIR / "smoke_gateway_voice_loop.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "$script:Calls = @()",
                "function New-MockWebResponse {",
                "  param([string]$Json)",
                "  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)",
                "  [pscustomobject]@{ RawContentStream = [System.IO.MemoryStream]::new($bytes) }",
                "}",
                "function Invoke-WebRequest {",
                "  param(",
                "    [string]$Uri,",
                "    [string]$Method = 'Get',",
                "    $Body,",
                "    [string]$ContentType,",
                "    [switch]$UseBasicParsing",
                "  )",
                "  $script:Calls += [pscustomobject]@{ Uri = $Uri; Method = $Method; Body = $Body; ContentType = $ContentType }",
                "  if ($Uri -like '*/debug/sessions' -and $Method -eq 'Get') {",
                "    return New-MockWebResponse '{\"session_count\":1,\"sessions\":[{\"session_id\":\"session-a\",\"device_id\":\"fc:01\",\"client_id\":\"client-a\",\"asr_turns\":[{\"turn_id\":\"asr-a\",\"status\":\"ok\",\"transcript\":\"hello\",\"assistant_text\":\"hi\"}],\"tts_turns\":[{\"asr_turn_id\":\"asr-a\",\"status\":\"ok\",\"provider\":\"dashscope_qwen_http\",\"text\":\"hi\",\"audio_frame_count\":4}]}]}'",
                "  }",
                "  throw \"unexpected uri $Uri\"",
                "}",
                "Invoke-SmokeGatewayVoiceLoop -GatewayBaseUrl 'http://127.0.0.1:8003' -MemoryBaseUrl 'http://127.0.0.1:8010/memory'",
                "$script:Calls | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )

    assert "Session: session-a" in result.stdout
    assert "Device: fc:01" in result.stdout
    assert "Transcript: hello" in result.stdout
    assert "Assistant: hi" in result.stdout
    assert "TTS provider: dashscope_qwen_http" in result.stdout
    assert "TTS frames sent: 4" in result.stdout
    assert "Memory URL: http://127.0.0.1:8010/memory?device_id=fc%3A01" in result.stdout
    calls = json.loads(result.stdout.splitlines()[-1])
    assert calls["Uri"] == "http://127.0.0.1:8003/debug/sessions"


def test_smoke_gateway_voice_loop_fails_when_tts_turn_is_not_ok():
    script_path = SCRIPTS_DIR / "smoke_gateway_voice_loop.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "function New-MockWebResponse {",
                "  param([string]$Json)",
                "  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)",
                "  [pscustomobject]@{ RawContentStream = [System.IO.MemoryStream]::new($bytes) }",
                "}",
                "function Invoke-WebRequest {",
                "  param([string]$Uri, [string]$Method = 'Get', [switch]$UseBasicParsing)",
                "  return New-MockWebResponse '{\"session_count\":1,\"sessions\":[{\"session_id\":\"session-a\",\"device_id\":\"fc:01\",\"asr_turns\":[{\"turn_id\":\"asr-a\",\"status\":\"ok\",\"transcript\":\"hello\",\"assistant_text\":\"hi\"}],\"tts_turns\":[{\"status\":\"error\",\"provider\":\"dashscope_qwen_http\",\"error\":\"TTS HTTP 401\"}]}]}'",
                "}",
                "Invoke-SmokeGatewayVoiceLoop -GatewayBaseUrl 'http://127.0.0.1:8003'",
                "}",
            ]
        ),
        check=False,
    )

    assert result.returncode != 0
    assert "TTS HTTP 401" in combined_output(result)


def test_smoke_gateway_voice_loop_fails_when_tts_turn_targets_an_older_asr_turn():
    script_path = SCRIPTS_DIR / "smoke_gateway_voice_loop.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "function New-MockWebResponse {",
                "  param([string]$Json)",
                "  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)",
                "  [pscustomobject]@{ RawContentStream = [System.IO.MemoryStream]::new($bytes) }",
                "}",
                "function Invoke-WebRequest {",
                "  param([string]$Uri, [string]$Method = 'Get', [switch]$UseBasicParsing)",
                "  return New-MockWebResponse '{\"session_count\":1,\"sessions\":[{\"session_id\":\"session-a\",\"device_id\":\"fc:01\",\"asr_turns\":[{\"turn_id\":\"asr-old\",\"status\":\"ok\",\"transcript\":\"old\",\"assistant_text\":\"old reply\"},{\"turn_id\":\"asr-new\",\"status\":\"ok\",\"transcript\":\"hello\",\"assistant_text\":\"hi\"}],\"tts_turns\":[{\"asr_turn_id\":\"asr-old\",\"status\":\"ok\",\"provider\":\"dashscope_qwen_http\",\"audio_frame_count\":4}]}]}'",
                "}",
                "Invoke-SmokeGatewayVoiceLoop -GatewayBaseUrl 'http://127.0.0.1:8003'",
                "}",
            ]
        ),
        check=False,
    )

    assert result.returncode != 0
    assert "asr-new" in combined_output(result)
    assert "asr-old" in combined_output(result)


def test_smoke_gateway_voice_loop_does_not_fall_back_to_an_older_paired_session():
    script_path = SCRIPTS_DIR / "smoke_gateway_voice_loop.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "function New-MockWebResponse {",
                "  param([string]$Json)",
                "  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)",
                "  [pscustomobject]@{ RawContentStream = [System.IO.MemoryStream]::new($bytes) }",
                "}",
                "function Invoke-WebRequest {",
                "  param([string]$Uri, [string]$Method = 'Get', [switch]$UseBasicParsing)",
                "  return New-MockWebResponse '{\"session_count\":2,\"sessions\":[{\"session_id\":\"session-old\",\"device_id\":\"fc:01\",\"asr_turns\":[{\"turn_id\":\"asr-old\",\"status\":\"ok\",\"transcript\":\"old\",\"assistant_text\":\"old reply\"}],\"tts_turns\":[{\"asr_turn_id\":\"asr-old\",\"status\":\"ok\",\"provider\":\"dashscope_qwen_http\",\"audio_frame_count\":4}]},{\"session_id\":\"session-new\",\"device_id\":\"fc:02\",\"asr_turns\":[{\"turn_id\":\"asr-new\",\"status\":\"ok\",\"transcript\":\"new\",\"assistant_text\":\"new reply\"}],\"tts_turns\":[]}]}'",
                "}",
                "Invoke-SmokeGatewayVoiceLoop -GatewayBaseUrl 'http://127.0.0.1:8003'",
                "}",
            ]
        ),
        check=False,
    )

    assert result.returncode != 0
    assert "asr-new" in combined_output(result)
    assert "Session: session-old" not in result.stdout


def test_smoke_gateway_voice_loop_does_not_fall_back_when_latest_asr_failed():
    script_path = SCRIPTS_DIR / "smoke_gateway_voice_loop.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "function New-MockWebResponse {",
                "  param([string]$Json)",
                "  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)",
                "  [pscustomobject]@{ RawContentStream = [System.IO.MemoryStream]::new($bytes) }",
                "}",
                "function Invoke-WebRequest {",
                "  param([string]$Uri, [string]$Method = 'Get', [switch]$UseBasicParsing)",
                "  return New-MockWebResponse '{\"session_count\":1,\"sessions\":[{\"session_id\":\"session-a\",\"device_id\":\"fc:01\",\"asr_turns\":[{\"turn_id\":\"asr-old\",\"status\":\"ok\",\"transcript\":\"old\",\"assistant_text\":\"old reply\"},{\"turn_id\":\"asr-new\",\"status\":\"error\",\"error\":\"ASR HTTP 401\"}],\"tts_turns\":[{\"asr_turn_id\":\"asr-old\",\"status\":\"ok\",\"provider\":\"dashscope_qwen_http\",\"audio_frame_count\":4}]}]}'",
                "}",
                "Invoke-SmokeGatewayVoiceLoop -GatewayBaseUrl 'http://127.0.0.1:8003'",
                "}",
            ]
        ),
        check=False,
    )

    assert result.returncode != 0
    assert "asr-new" in combined_output(result)
    assert "ASR HTTP 401" in combined_output(result)
    assert "Session: session-a" not in result.stdout


def test_stop_local_demo_script_stops_unique_listener_processes_only():
    script_path = SCRIPTS_DIR / "stop_local_demo.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "function Get-NetTCPConnection {",
                "  @(",
                "    [pscustomobject]@{ LocalPort = 8000; OwningProcess = 111 },",
                "    [pscustomobject]@{ LocalPort = 8003; OwningProcess = 111 },",
                "    [pscustomobject]@{ LocalPort = 8010; OwningProcess = 222 },",
                "    [pscustomobject]@{ LocalPort = 9000; OwningProcess = 333 }",
                "  )",
                "}",
                "function Get-Process { param([int]$Id) [pscustomobject]@{ Id = $Id; ProcessName = \"python\" } }",
                "$script:Stopped = @()",
                "function Stop-Process { param([int]$Id, [switch]$Force) $script:Stopped += $Id }",
                "Invoke-StopLocalDemo | Out-Null",
                "$script:Stopped | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )

    assert json.loads(result.stdout.splitlines()[-1]) == [111, 222]


def test_stop_local_demo_script_normalizes_comma_separated_ports():
    script_path = SCRIPTS_DIR / "stop_local_demo.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "ConvertTo-PortList -Ports '8000,8003' | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )

    assert json.loads(result.stdout.splitlines()[-1]) == [8000, 8003]


def test_stop_local_demo_script_entrypoint_splits_comma_separated_ports():
    script_path = SCRIPTS_DIR / "stop_local_demo.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function Get-NetTCPConnection {",
                "  @(",
                "    [pscustomobject]@{ LocalPort = 8000; OwningProcess = 111 },",
                "    [pscustomobject]@{ LocalPort = 8003; OwningProcess = 111 },",
                "    [pscustomobject]@{ LocalPort = 8010; OwningProcess = 222 }",
                "  )",
                "}",
                "function Get-Process { param([int]$Id) [pscustomobject]@{ Id = $Id; ProcessName = \"python\" } }",
                "$global:Stopped = @()",
                "function Stop-Process { param([int]$Id, [switch]$Force) $global:Stopped += $Id }",
                f"& '{script_path}' -Ports 8000,8003 | Out-Null",
                "$global:Stopped | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )

    assert json.loads(result.stdout.splitlines()[-1]) == 111


def test_backup_local_demo_data_copies_existing_database_and_config(tmp_path: Path):
    script_path = SCRIPTS_DIR / "backup_local_demo_data.ps1"
    db_path = tmp_path / "data" / "buddy_memory.db"
    config_path = tmp_path / ".run" / "xiaozhi" / "data" / ".config.yaml"
    backup_root = tmp_path / "backup"
    db_path.parent.mkdir(parents=True)
    config_path.parent.mkdir(parents=True)
    db_path.write_text("memory", encoding="utf-8")
    config_path.write_text("config", encoding="utf-8")

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                f"Invoke-BackupLocalDemoData -DatabasePath '{db_path}' -XiaoZhiConfigPath '{config_path}' -BackupRoot '{backup_root}' | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )
    payload = json.loads(result.stdout)

    assert payload["DatabaseBackup"].endswith("buddy_memory.db")
    assert payload["XiaoZhiConfigBackup"].endswith("xiaozhi.config.yaml")
    assert (backup_root / "buddy_memory.db").read_text(encoding="utf-8") == "memory"
    assert (backup_root / "xiaozhi.config.yaml").read_text(encoding="utf-8") == "config"


def copy_v05_backup_script_to_fake_repo(tmp_path: Path) -> Path:
    fake_repo = tmp_path / "repo"
    script_dir = fake_repo / "scripts"
    script_dir.mkdir(parents=True)
    script_path = script_dir / "backup_v05_runtime.ps1"
    script_path.write_text(
        (SCRIPTS_DIR / "backup_v05_runtime.ps1").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return fake_repo


def test_v05_backup_creates_hashed_manifest_for_runtime_artifacts(tmp_path: Path):
    fake_repo = copy_v05_backup_script_to_fake_repo(tmp_path)
    config_path = fake_repo / ".run" / "xiaozhi-esp32-server" / "main" / "xiaozhi-server" / "data" / ".config.yaml"
    audio_path = fake_repo / "data" / "gateway_audio" / "session-a" / "audio.wav"
    backup_root = fake_repo / "tmp" / "v05-runtime-backup"
    config_path.parent.mkdir(parents=True)
    audio_path.parent.mkdir(parents=True)
    (fake_repo / ".env").write_text("DEMO_VALUE=fixture\n", encoding="utf-8")
    config_path.write_text("selected_module: fixture\n", encoding="utf-8")
    audio_path.write_bytes(b"RIFFfixtureWAVE")

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                "$env:ASR_PROVIDER = 'fixture-asr'",
                "$env:TTS_PROVIDER = 'fixture-tts'",
                f"New-V05RuntimeBackup -BackupRoot '{backup_root}' | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )
    payload = json.loads(result.stdout)
    manifest_path = Path(payload["ManifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert Path(payload["BackupDir"]).parent == backup_root
    assert manifest_path.exists()
    assert payload["ManifestSha256"].isalnum() and len(payload["ManifestSha256"]) == 64
    assert manifest["source_commit"] == "22e4712814dfb19f1ecea9bd0e6bfbd24c057ac5"
    assert manifest["environment_file"] == "environment.json"
    assert {entry["relative_path"] for entry in manifest["files"]} == {
        ".env",
        ".run/xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml",
        "data/gateway_audio/session-a/audio.wav",
        "environment.json",
    }
    assert all(len(entry["sha256"]) == 64 and entry["sha256"].islower() for entry in manifest["files"])
    environment = json.loads((Path(payload["BackupDir"]) / "environment.json").read_text(encoding="utf-8"))
    assert set(environment) == {"process", "user"}
    assert set(environment["process"]) == {"ASR_PROVIDER", "TTS_PROVIDER"}


@pytest.mark.parametrize(
    "case_name",
    ("unignored-repository-root", "outside-repository", "gateway-audio-overlap"),
)
def test_v05_backup_rejects_unapproved_or_overlapping_roots_before_creation(
    tmp_path: Path, case_name: str
):
    fake_repo = copy_v05_backup_script_to_fake_repo(tmp_path / case_name)
    if case_name == "unignored-repository-root":
        backup_root = fake_repo / "runtime-backup"
    elif case_name == "outside-repository":
        backup_root = tmp_path / "outside-runtime-backup"
    else:
        backup_root = fake_repo / "data" / "gateway_audio" / "backup"
        (fake_repo / "data" / "gateway_audio").mkdir(parents=True)

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                f"New-V05RuntimeBackup -BackupRoot '{backup_root}'",
                "}",
            ]
        ),
        check=False,
    )

    assert result.returncode != 0
    assert not backup_root.exists()


def test_v05_restore_validates_before_apply_and_restores_through_manifest(tmp_path: Path):
    fake_repo = copy_v05_backup_script_to_fake_repo(tmp_path)
    config_path = fake_repo / ".run" / "xiaozhi-esp32-server" / "main" / "xiaozhi-server" / "data" / ".config.yaml"
    audio_path = fake_repo / "data" / "gateway_audio" / "session-a" / "audio.wav"
    backup_root = fake_repo / "tmp" / "v05-runtime-backup"
    config_path.parent.mkdir(parents=True)
    audio_path.parent.mkdir(parents=True)
    (fake_repo / ".env").write_text("DEMO_VALUE=before\n", encoding="utf-8")
    config_path.write_text("selected_module: before\n", encoding="utf-8")
    audio_path.write_bytes(b"RIFFbeforeWAVE")

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                "$env:ASR_PROVIDER = 'fixture-asr-before'",
                f"$backup = New-V05RuntimeBackup -BackupRoot '{backup_root}'",
                f"Set-Content -LiteralPath '{fake_repo / '.env'}' -Value 'DEMO_VALUE=after'",
                f"Set-Content -LiteralPath '{config_path}' -Value 'selected_module: after'",
                f"[System.IO.File]::WriteAllBytes('{audio_path}', [byte[]](1, 2, 3))",
                "$env:ASR_PROVIDER = 'fixture-asr-after'",
                "Restore-V05RuntimeBackup -BackupDir $backup.BackupDir | Out-Null",
                f"$dryRunDotEnvUnchanged = ((Get-Content -Raw -LiteralPath '{fake_repo / '.env'}').Trim() -eq 'DEMO_VALUE=after')",
                f"$dryRunConfigUnchanged = ((Get-Content -Raw -LiteralPath '{config_path}').Trim() -eq 'selected_module: after')",
                f"$dryRunAudioUnchanged = ([System.IO.File]::ReadAllBytes('{audio_path}').Count -eq 3)",
                "$dryRunEnvironmentUnchanged = ($env:ASR_PROVIDER -eq 'fixture-asr-after')",
                "$dryRunSnapshotCount = @(Get-ChildItem -LiteralPath $backup.BackupDir -Directory -Filter 'pre-restore-*').Count",
                "Restore-V05RuntimeBackup -BackupDir $backup.BackupDir -Apply -EnvironmentTarget Process | Out-Null",
                "[pscustomobject]@{",
                "  DryRunDotEnvUnchanged = $dryRunDotEnvUnchanged",
                "  DryRunConfigUnchanged = $dryRunConfigUnchanged",
                "  DryRunAudioUnchanged = $dryRunAudioUnchanged",
                "  DryRunEnvironmentUnchanged = $dryRunEnvironmentUnchanged",
                "  DryRunSnapshotCount = $dryRunSnapshotCount",
                f"  EnvRestored = ($env:ASR_PROVIDER -eq 'fixture-asr-before')",
                f"  DotEnvRestored = ((Get-Content -Raw -LiteralPath '{fake_repo / '.env'}').Trim() -eq 'DEMO_VALUE=before')",
                f"  ConfigRestored = ((Get-Content -Raw -LiteralPath '{config_path}').Trim() -eq 'selected_module: before')",
                f"  AudioRestored = ([System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes('{audio_path}')) -eq 'RIFFbeforeWAVE')",
                "} | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )
    payload = json.loads(result.stdout.splitlines()[-1])

    assert payload == {
        "DryRunDotEnvUnchanged": True,
        "DryRunConfigUnchanged": True,
        "DryRunAudioUnchanged": True,
        "DryRunEnvironmentUnchanged": True,
        "DryRunSnapshotCount": 0,
        "EnvRestored": True,
        "DotEnvRestored": True,
        "ConfigRestored": True,
        "AudioRestored": True,
    }


def test_v05_restore_rejects_tampered_backup_before_writing(tmp_path: Path):
    fake_repo = copy_v05_backup_script_to_fake_repo(tmp_path)
    backup_dir = fake_repo / "tmp" / "v05-runtime-backup" / "fixture"
    backup_dir.mkdir(parents=True)
    (backup_dir / ".env").write_text("DEMO_VALUE=tampered\n", encoding="utf-8")
    (backup_dir / "environment.json").write_text('{"process":{},"user":{}}', encoding="utf-8")
    (backup_dir / "manifest.json").write_text(
        json.dumps(
            {
                "source_commit": "22e4712814dfb19f1ecea9bd0e6bfbd24c057ac5",
                "files": [
                    {"relative_path": ".env", "sha256": "0" * 64},
                    {"relative_path": "environment.json", "sha256": "0" * 64},
                ],
                "environment_file": "environment.json",
            }
        ),
        encoding="utf-8",
    )
    destination = fake_repo / ".env"
    destination.write_text("DEMO_VALUE=destination\n", encoding="utf-8")

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                f"Restore-V05RuntimeBackup -BackupDir '{backup_dir}' -Apply",
                "}",
            ]
        ),
        check=False,
    )

    assert result.returncode != 0
    assert "hash" in combined_output(result).lower()
    assert destination.read_text(encoding="utf-8") == "DEMO_VALUE=destination\n"


def test_v05_restore_clears_allowlisted_process_value_absent_from_snapshot(tmp_path: Path):
    fake_repo = copy_v05_backup_script_to_fake_repo(tmp_path)
    backup_root = fake_repo / "tmp" / "v05-runtime-backup"
    (fake_repo / ".env").write_text("DEMO_VALUE=fixture\n", encoding="utf-8")

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                "$env:ASR_PROVIDER = 'fixture-before'",
                "$env:TTS_API_KEY = $null",
                f"$backup = New-V05RuntimeBackup -BackupRoot '{backup_root}'",
                "$env:ASR_PROVIDER = 'fixture-after'",
                "$env:TTS_API_KEY = 'fixture-added-after-backup'",
                "Restore-V05RuntimeBackup -BackupDir $backup.BackupDir -Apply -EnvironmentTarget Process | Out-Null",
                "[pscustomobject]@{",
                "  RecordedValueRestored = ($env:ASR_PROVIDER -eq 'fixture-before')",
                "  AbsentValueCleared = ($null -eq [System.Environment]::GetEnvironmentVariable('TTS_API_KEY', 'Process'))",
                "} | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )
    payload = json.loads(result.stdout.splitlines()[-1])

    assert payload == {"RecordedValueRestored": True, "AbsentValueCleared": True}


def test_v05_restore_rejects_missing_or_mismatched_source_commit(tmp_path: Path):
    fake_repo = copy_v05_backup_script_to_fake_repo(tmp_path)
    backup_root = fake_repo / "tmp" / "v05-runtime-backup"
    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                f"New-V05RuntimeBackup -BackupRoot '{backup_root}' | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )
    original_backup = Path(json.loads(result.stdout)["BackupDir"])

    for case_name, source_commit in (("missing", None), ("mismatch", "0" * 40)):
        backup_dir = fake_repo / "tmp" / f"source-{case_name}"
        shutil.copytree(original_backup, backup_dir)
        manifest_path = backup_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if source_commit is None:
            manifest.pop("source_commit")
        else:
            manifest["source_commit"] = source_commit
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        restore = run_powershell(
            "\n".join(
                [
                    "& {",
                    f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                    f"Restore-V05RuntimeBackup -BackupDir '{backup_dir}'",
                    "}",
                ]
            ),
            check=False,
        )

        assert restore.returncode != 0, case_name
        assert "source commit" in combined_output(restore).lower()


def test_v05_restore_rejects_present_empty_environment_value_before_mutation(tmp_path: Path):
    fake_repo = copy_v05_backup_script_to_fake_repo(tmp_path)
    backup_root = fake_repo / "tmp" / "v05-runtime-backup"
    dot_env = fake_repo / ".env"
    dot_env.write_text("DEMO_VALUE=backup\n", encoding="utf-8")
    backup = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                f"New-V05RuntimeBackup -BackupRoot '{backup_root}' | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )
    backup_dir = Path(json.loads(backup.stdout)["BackupDir"])
    environment_path = backup_dir / "environment.json"
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    environment["process"]["ASR_PROVIDER"] = ""
    environment_path.write_text(json.dumps(environment), encoding="utf-8")
    environment_hash = hashlib.sha256(environment_path.read_bytes()).hexdigest()
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["relative_path"] == "environment.json":
            entry["sha256"] = environment_hash
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    dot_env.write_text("DEMO_VALUE=pre-restore\n", encoding="utf-8")

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                "$env:ASR_PROVIDER = 'fixture-pre-restore'",
                "$restoreFailed = $false",
                "$rejectedAsEmpty = $false",
                "try {",
                f"  Restore-V05RuntimeBackup -BackupDir '{backup_dir}' -Apply -EnvironmentTarget Process | Out-Null",
                "}",
                "catch {",
                "  $restoreFailed = $true",
                "  $rejectedAsEmpty = $_.Exception.Message -like '*empty environment*'",
                "}",
                "[pscustomobject]@{",
                "  RestoreFailed = $restoreFailed",
                "  RejectedAsEmpty = $rejectedAsEmpty",
                f"  DotEnvUnchanged = ((Get-Content -Raw -LiteralPath '{dot_env}').Trim() -eq 'DEMO_VALUE=pre-restore')",
                "  EnvironmentUnchanged = ($env:ASR_PROVIDER -eq 'fixture-pre-restore')",
                f"  SnapshotCount = @(Get-ChildItem -LiteralPath '{backup_dir}' -Directory -Filter 'pre-restore-*').Count",
                "} | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )
    payload = json.loads(result.stdout.splitlines()[-1])

    assert payload == {
        "RestoreFailed": True,
        "RejectedAsEmpty": True,
        "DotEnvUnchanged": True,
        "EnvironmentUnchanged": True,
        "SnapshotCount": 0,
    }


def test_v05_restore_redacts_malformed_environment_json_before_mutation(tmp_path: Path):
    fake_repo = copy_v05_backup_script_to_fake_repo(tmp_path)
    backup_root = fake_repo / "tmp" / "v05-runtime-backup"
    dot_env = fake_repo / ".env"
    dot_env.write_text("DEMO_VALUE=backup\n", encoding="utf-8")
    backup = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                "$env:ASR_PROVIDER = 'fixture-backup-provider'",
                f"New-V05RuntimeBackup -BackupRoot '{backup_root}' | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )
    backup_dir = Path(json.loads(backup.stdout)["BackupDir"])
    environment_path = backup_dir / "environment.json"
    synthetic_content = "fixture-" + "malformed-environment-content"
    environment_path.write_text(
        '{"process":{"ASR_PROVIDER":"' + synthetic_content + '"',
        encoding="utf-8",
    )
    environment_hash = hashlib.sha256(environment_path.read_bytes()).hexdigest()
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["relative_path"] == "environment.json":
            entry["sha256"] = environment_hash
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    dot_env.write_text("DEMO_VALUE=pre-restore\n", encoding="utf-8")

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                "$env:ASR_PROVIDER = 'fixture-pre-restore-provider'",
                "$restoreFailed = $false",
                "$redactedDiagnostic = $false",
                "try {",
                f"  Restore-V05RuntimeBackup -BackupDir '{backup_dir}' -Apply -EnvironmentTarget Process | Out-Null",
                "}",
                "catch {",
                "  $restoreFailed = $true",
                "  $redactedDiagnostic = $_.Exception.Message -eq 'Backup environment data is not valid JSON.'",
                "  [Console]::Error.WriteLine($_.Exception.Message)",
                "}",
                "[pscustomobject]@{",
                "  RestoreFailed = $restoreFailed",
                "  RedactedDiagnostic = $redactedDiagnostic",
                f"  DotEnvUnchanged = ((Get-Content -Raw -LiteralPath '{dot_env}').Trim() -eq 'DEMO_VALUE=pre-restore')",
                "  EnvironmentUnchanged = ($env:ASR_PROVIDER -eq 'fixture-pre-restore-provider')",
                f"  SnapshotCount = @(Get-ChildItem -LiteralPath '{backup_dir}' -Directory -Filter 'pre-restore-*').Count",
                "} | ConvertTo-Json -Compress",
                "}",
            ]
        ),
        check=False,
    )
    payload = json.loads(result.stdout.splitlines()[-1])

    assert synthetic_content not in combined_output(result)
    assert payload == {
        "RestoreFailed": True,
        "RedactedDiagnostic": True,
        "DotEnvUnchanged": True,
        "EnvironmentUnchanged": True,
        "SnapshotCount": 0,
    }


def test_v05_restore_rejects_existing_destination_reparse_point(tmp_path: Path):
    if os.name != "nt":
        pytest.skip("Windows reparse-point behavior is platform-specific")

    fake_repo = copy_v05_backup_script_to_fake_repo(tmp_path)
    config_path = fake_repo / ".run" / "xiaozhi-esp32-server" / "main" / "xiaozhi-server" / "data" / ".config.yaml"
    backup_root = fake_repo / "tmp" / "v05-runtime-backup"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("selected_module: backup\n", encoding="utf-8")
    backup = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                f"New-V05RuntimeBackup -BackupRoot '{backup_root}' | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )
    backup_dir = Path(json.loads(backup.stdout)["BackupDir"])

    shutil.rmtree(fake_repo / ".run")
    outside_root = tmp_path / "outside-runtime"
    outside_config = outside_root / "xiaozhi-esp32-server" / "main" / "xiaozhi-server" / "data" / ".config.yaml"
    outside_config.parent.mkdir(parents=True)
    outside_config.write_text("selected_module: outside-current\n", encoding="utf-8")
    link_path = fake_repo / ".run"
    try:
        os.symlink(outside_root, link_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        junction = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(outside_root)],
            capture_output=True,
            text=True,
        )
        if junction.returncode != 0:
            pytest.skip("platform cannot create a temporary symlink or junction")

    restore = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                f"Restore-V05RuntimeBackup -BackupDir '{backup_dir}' -Apply",
                "}",
            ]
        ),
        check=False,
    )

    assert restore.returncode != 0
    assert "reparse" in combined_output(restore).lower()
    assert outside_config.read_text(encoding="utf-8") == "selected_module: outside-current\n"


def test_v05_restore_revalidates_destination_after_planning_before_write(tmp_path: Path):
    if os.name != "nt":
        pytest.skip("Windows junction behavior is platform-specific")

    fake_repo = copy_v05_backup_script_to_fake_repo(tmp_path)
    backup_root = fake_repo / "tmp" / "v05-runtime-backup"
    session_root = fake_repo / "data" / "gateway_audio" / "session-a"
    audio_path = session_root / "nested" / "audio.wav"
    outside_root = tmp_path / "outside-audio"
    outside_sentinel = outside_root / "sentinel.txt"
    outside_nested = outside_root / "nested"
    audio_path.parent.mkdir(parents=True)
    outside_root.mkdir()
    audio_path.write_bytes(b"RIFFbackupWAVE")
    outside_sentinel.write_text("outside-current\n", encoding="utf-8")

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                f"$backup = New-V05RuntimeBackup -BackupRoot '{backup_root}'",
                f"[System.IO.File]::WriteAllBytes('{audio_path}', [System.Text.Encoding]::ASCII.GetBytes('RIFFpre-restoreWAVE'))",
                "function Invoke-V05BeforeRestoreWrite {",
                "  param([Parameter(Mandatory = $true)][object]$Plan)",
                f"  Remove-Item -LiteralPath '{session_root}' -Recurse -Force",
                f"  New-Item -ItemType Junction -Path '{session_root}' -Target '{outside_root}' | Out-Null",
                "}",
                "$restoreFailed = $false",
                "$recoveryReported = $false",
                "try {",
                "  Restore-V05RuntimeBackup -BackupDir $backup.BackupDir -Apply -EnvironmentTarget Process | Out-Null",
                "}",
                "catch {",
                "  $restoreFailed = $true",
                "  $recoveryReported = $_.Exception.Message -like '*pre-restore state was recovered*'",
                "}",
                "[pscustomobject]@{",
                "  RestoreFailed = $restoreFailed",
                "  RecoveryReported = $recoveryReported",
                f"  OutsideSentinelUnchanged = ((Get-Content -Raw -LiteralPath '{outside_sentinel}').Trim() -eq 'outside-current')",
                f"  OutsideFileCount = @(Get-ChildItem -LiteralPath '{outside_root}' -File -Force).Count",
                f"  OutsideDirectoryCount = @(Get-ChildItem -LiteralPath '{outside_root}' -Directory -Force).Count",
                f"  OutsideNestedMissing = (-not (Test-Path -LiteralPath '{outside_nested}'))",
                "} | ConvertTo-Json -Compress",
                "}",
            ]
        ),
        check=False,
    )
    payload = json.loads(result.stdout.splitlines()[-1])

    assert payload == {
        "RestoreFailed": True,
        "RecoveryReported": True,
        "OutsideSentinelUnchanged": True,
        "OutsideFileCount": 1,
        "OutsideDirectoryCount": 0,
        "OutsideNestedMissing": True,
    }


def test_v05_restore_rejects_directory_at_file_destination_before_mutation(tmp_path: Path):
    fake_repo = copy_v05_backup_script_to_fake_repo(tmp_path)
    backup_root = fake_repo / "tmp" / "v05-runtime-backup"
    dot_env = fake_repo / ".env"
    dot_env.write_text("DEMO_VALUE=backup\n", encoding="utf-8")

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                "$env:ASR_PROVIDER = 'fixture-backup'",
                f"$backup = New-V05RuntimeBackup -BackupRoot '{backup_root}'",
                f"Remove-Item -LiteralPath '{dot_env}' -Force",
                f"New-Item -ItemType Directory -Path '{dot_env}' | Out-Null",
                f"Set-Content -LiteralPath '{dot_env / 'existing.txt'}' -Value 'existing-child'",
                "$env:ASR_PROVIDER = 'fixture-pre-restore'",
                "$restoreFailed = $false",
                "$rejectedAsNonRegular = $false",
                "try {",
                "  Restore-V05RuntimeBackup -BackupDir $backup.BackupDir -Apply -EnvironmentTarget Process | Out-Null",
                "}",
                "catch {",
                "  $restoreFailed = $true",
                "  $rejectedAsNonRegular = $_.Exception.Message -like '*regular file*'",
                "}",
                "[pscustomobject]@{",
                "  RestoreFailed = $restoreFailed",
                "  RejectedAsNonRegular = $rejectedAsNonRegular",
                f"  DestinationIsDirectory = (Test-Path -LiteralPath '{dot_env}' -PathType Container)",
                f"  ExistingChildPreserved = ((Get-Content -Raw -LiteralPath '{dot_env / 'existing.txt'}').Trim() -eq 'existing-child')",
                f"  DestinationChildCount = @(Get-ChildItem -LiteralPath '{dot_env}' -Force).Count",
                "  SnapshotCount = @(Get-ChildItem -LiteralPath $backup.BackupDir -Directory -Filter 'pre-restore-*').Count",
                "  EnvironmentUnchanged = ($env:ASR_PROVIDER -eq 'fixture-pre-restore')",
                "} | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )
    payload = json.loads(result.stdout.splitlines()[-1])

    assert payload == {
        "RestoreFailed": True,
        "RejectedAsNonRegular": True,
        "DestinationIsDirectory": True,
        "ExistingChildPreserved": True,
        "DestinationChildCount": 1,
        "SnapshotCount": 0,
        "EnvironmentUnchanged": True,
    }


def test_v05_restore_recovers_all_destinations_after_mid_apply_failure(tmp_path: Path):
    fake_repo = copy_v05_backup_script_to_fake_repo(tmp_path)
    config_path = fake_repo / ".run" / "xiaozhi-esp32-server" / "main" / "xiaozhi-server" / "data" / ".config.yaml"
    audio_path = fake_repo / "data" / "gateway_audio" / "session-a" / "audio.wav"
    backup_root = fake_repo / "tmp" / "v05-runtime-backup"
    config_path.parent.mkdir(parents=True)
    audio_path.parent.mkdir(parents=True)
    (fake_repo / ".env").write_text("DEMO_VALUE=backup\n", encoding="utf-8")
    config_path.write_text("selected_module: backup\n", encoding="utf-8")
    audio_path.write_bytes(b"RIFFbackupWAVE")

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                "$env:TTS_PROVIDER = 'fixture-backup'",
                f"$backup = New-V05RuntimeBackup -BackupRoot '{backup_root}'",
                f"Set-Content -LiteralPath '{fake_repo / '.env'}' -Value 'DEMO_VALUE=pre-restore'",
                f"Set-Content -LiteralPath '{config_path}' -Value 'selected_module: pre-restore'",
                f"[System.IO.File]::WriteAllBytes('{audio_path}', [System.Text.Encoding]::ASCII.GetBytes('RIFFpre-restoreWAVE'))",
                "$env:TTS_PROVIDER = 'fixture-pre-restore'",
                "$script:MoveAttempts = 0",
                "function global:Move-Item {",
                "  [CmdletBinding()]",
                "  param(",
                "    [Parameter(Mandatory = $true)][string]$LiteralPath,",
                "    [Parameter(Mandatory = $true)][string]$Destination,",
                "    [switch]$Force",
                "  )",
                "  $script:MoveAttempts += 1",
                "  if ($script:MoveAttempts -eq 2) { throw 'injected replacement failure' }",
                "  Microsoft.PowerShell.Management\\Move-Item @PSBoundParameters",
                "}",
                "$restoreFailed = $false",
                "try {",
                "  Restore-V05RuntimeBackup -BackupDir $backup.BackupDir -Apply -EnvironmentTarget Process | Out-Null",
                "}",
                "catch {",
                "  $restoreFailed = $true",
                "}",
                "[pscustomobject]@{",
                "  RestoreFailed = $restoreFailed",
                f"  DotEnvRecovered = ((Get-Content -Raw -LiteralPath '{fake_repo / '.env'}').Trim() -eq 'DEMO_VALUE=pre-restore')",
                f"  ConfigRecovered = ((Get-Content -Raw -LiteralPath '{config_path}').Trim() -eq 'selected_module: pre-restore')",
                f"  AudioRecovered = ([System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes('{audio_path}')) -eq 'RIFFpre-restoreWAVE')",
                "  EnvironmentRecovered = ($env:TTS_PROVIDER -eq 'fixture-pre-restore')",
                "} | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )
    payload = json.loads(result.stdout.splitlines()[-1])

    assert payload == {
        "RestoreFailed": True,
        "DotEnvRecovered": True,
        "ConfigRecovered": True,
        "AudioRecovered": True,
        "EnvironmentRecovered": True,
    }


def test_v05_restore_recovers_files_and_process_environment_after_late_write_failure(tmp_path: Path):
    fake_repo = copy_v05_backup_script_to_fake_repo(tmp_path)
    backup_root = fake_repo / "tmp" / "v05-runtime-backup"
    dot_env = fake_repo / ".env"
    dot_env.write_text("DEMO_VALUE=backup\n", encoding="utf-8")

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                "$env:ASR_PROVIDER = 'fixture-backup-provider'",
                "$env:ASR_HTTP_URL = 'fixture-backup-url'",
                f"$backup = New-V05RuntimeBackup -BackupRoot '{backup_root}'",
                f"Set-Content -LiteralPath '{dot_env}' -Value 'DEMO_VALUE=pre-restore'",
                "$env:ASR_PROVIDER = 'fixture-pre-restore-provider'",
                "$env:ASR_HTTP_URL = 'fixture-pre-restore-url'",
                "$script:EnvironmentWriteAttempts = 0",
                "function Set-V05EnvironmentVariable {",
                "  param(",
                "    [Parameter(Mandatory = $true)][string]$Name,",
                "    [AllowNull()][string]$Value,",
                "    [Parameter(Mandatory = $true)][ValidateSet('Process', 'User')][string]$EnvironmentTarget",
                "  )",
                "  $script:EnvironmentWriteAttempts += 1",
                "  if ($script:EnvironmentWriteAttempts -eq 3) { throw 'injected environment write failure' }",
                "  [System.Environment]::SetEnvironmentVariable($Name, $Value, $EnvironmentTarget)",
                "}",
                "$restoreFailed = $false",
                "$recoveryReported = $false",
                "try {",
                "  Restore-V05RuntimeBackup -BackupDir $backup.BackupDir -Apply -EnvironmentTarget Process | Out-Null",
                "}",
                "catch {",
                "  $restoreFailed = $true",
                "  $recoveryReported = $_.Exception.Message -like '*pre-restore state was recovered*'",
                "}",
                "[pscustomobject]@{",
                "  RestoreFailed = $restoreFailed",
                "  RecoveryReported = $recoveryReported",
                f"  DotEnvRecovered = ((Get-Content -Raw -LiteralPath '{dot_env}').Trim() -eq 'DEMO_VALUE=pre-restore')",
                "  ProviderRecovered = ($env:ASR_PROVIDER -eq 'fixture-pre-restore-provider')",
                "  UrlRecovered = ($env:ASR_HTTP_URL -eq 'fixture-pre-restore-url')",
                "  RecoveryWritesOccurred = ($script:EnvironmentWriteAttempts -gt 3)",
                "} | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )
    payload = json.loads(result.stdout.splitlines()[-1])

    assert payload == {
        "RestoreFailed": True,
        "RecoveryReported": True,
        "DotEnvRecovered": True,
        "ProviderRecovered": True,
        "UrlRecovered": True,
        "RecoveryWritesOccurred": True,
    }


def test_v05_user_scope_restore_and_late_failure_recovery_preserve_machine_state(tmp_path: Path):
    if os.name != "nt":
        pytest.skip("User environment scope is Windows-specific")

    fake_repo = copy_v05_backup_script_to_fake_repo(tmp_path)
    backup_root = fake_repo / "tmp" / "v05-runtime-backup"
    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{fake_repo / 'scripts' / 'backup_v05_runtime.ps1'}'",
                "$names = @(",
                "  'ASR_PROVIDER', 'ASR_HTTP_URL', 'ASR_MODEL', 'ASR_API_KEY', 'ASR_TIMEOUT_SECONDS',",
                "  'TTS_PROVIDER', 'TTS_HTTP_URL', 'TTS_MODEL', 'TTS_API_KEY',",
                "  'TTS_VOICE', 'TTS_LANGUAGE', 'TTS_TIMEOUT_SECONDS'",
                ")",
                "$originalUser = @{}",
                "foreach ($name in $names) {",
                "  $originalUser[$name] = [System.Environment]::GetEnvironmentVariable($name, 'User')",
                "}",
                "$recordedValueRestored = $false",
                "$absentValueCleared = $false",
                "$lateRestoreFailed = $false",
                "$recoveryReported = $false",
                "$providerRecovered = $false",
                "$urlRecovered = $false",
                "$recoveryWritesOccurred = $false",
                "try {",
                "  foreach ($name in $names) {",
                "    [System.Environment]::SetEnvironmentVariable($name, $null, 'User')",
                "  }",
                "  [System.Environment]::SetEnvironmentVariable('ASR_PROVIDER', 'fixture-user-backup-provider', 'User')",
                "  [System.Environment]::SetEnvironmentVariable('ASR_HTTP_URL', 'fixture-user-backup-url', 'User')",
                f"  $backup = New-V05RuntimeBackup -BackupRoot '{backup_root}'",
                "  [System.Environment]::SetEnvironmentVariable('ASR_PROVIDER', 'fixture-user-before-restore-provider', 'User')",
                "  [System.Environment]::SetEnvironmentVariable('ASR_HTTP_URL', 'fixture-user-before-restore-url', 'User')",
                "  [System.Environment]::SetEnvironmentVariable('TTS_MODEL', 'fixture-user-value-to-clear', 'User')",
                "  Restore-V05RuntimeBackup -BackupDir $backup.BackupDir -Apply -EnvironmentTarget User | Out-Null",
                "  $recordedValueRestored = ([System.Environment]::GetEnvironmentVariable('ASR_PROVIDER', 'User') -eq 'fixture-user-backup-provider')",
                "  $absentValueCleared = ($null -eq [System.Environment]::GetEnvironmentVariable('TTS_MODEL', 'User'))",
                "  [System.Environment]::SetEnvironmentVariable('ASR_PROVIDER', 'fixture-user-pre-recovery-provider', 'User')",
                "  [System.Environment]::SetEnvironmentVariable('ASR_HTTP_URL', 'fixture-user-pre-recovery-url', 'User')",
                "  $script:EnvironmentWriteAttempts = 0",
                "  function Set-V05EnvironmentVariable {",
                "    param(",
                "      [Parameter(Mandatory = $true)][string]$Name,",
                "      [AllowNull()][string]$Value,",
                "      [Parameter(Mandatory = $true)][ValidateSet('Process', 'User')][string]$EnvironmentTarget",
                "    )",
                "    $script:EnvironmentWriteAttempts += 1",
                "    if ($script:EnvironmentWriteAttempts -eq 3) { throw 'injected user environment write failure' }",
                "    [System.Environment]::SetEnvironmentVariable($Name, $Value, $EnvironmentTarget)",
                "  }",
                "  try {",
                "    Restore-V05RuntimeBackup -BackupDir $backup.BackupDir -Apply -EnvironmentTarget User | Out-Null",
                "  }",
                "  catch {",
                "    $lateRestoreFailed = $true",
                "    $recoveryReported = $_.Exception.Message -like '*pre-restore state was recovered*'",
                "  }",
                "  $providerRecovered = ([System.Environment]::GetEnvironmentVariable('ASR_PROVIDER', 'User') -eq 'fixture-user-pre-recovery-provider')",
                "  $urlRecovered = ([System.Environment]::GetEnvironmentVariable('ASR_HTTP_URL', 'User') -eq 'fixture-user-pre-recovery-url')",
                "  $recoveryWritesOccurred = ($script:EnvironmentWriteAttempts -gt 3)",
                "}",
                "finally {",
                "  foreach ($name in $names) {",
                "    [System.Environment]::SetEnvironmentVariable($name, $originalUser[$name], 'User')",
                "  }",
                "}",
                "$originalUserStateRestored = $true",
                "foreach ($name in $names) {",
                "  if ([System.Environment]::GetEnvironmentVariable($name, 'User') -cne $originalUser[$name]) {",
                "    $originalUserStateRestored = $false",
                "  }",
                "}",
                "[pscustomobject]@{",
                "  RecordedValueRestored = $recordedValueRestored",
                "  AbsentValueCleared = $absentValueCleared",
                "  LateRestoreFailed = $lateRestoreFailed",
                "  RecoveryReported = $recoveryReported",
                "  ProviderRecovered = $providerRecovered",
                "  UrlRecovered = $urlRecovered",
                "  RecoveryWritesOccurred = $recoveryWritesOccurred",
                "  OriginalUserStateRestored = $originalUserStateRestored",
                "} | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )
    payload = json.loads(result.stdout.splitlines()[-1])

    assert payload == {
        "RecordedValueRestored": True,
        "AbsentValueCleared": True,
        "LateRestoreFailed": True,
        "RecoveryReported": True,
        "ProviderRecovered": True,
        "UrlRecovered": True,
        "RecoveryWritesOccurred": True,
        "OriginalUserStateRestored": True,
    }


def test_v05_staged_secret_scanner_allows_only_explicit_fixture_path(tmp_path: Path):
    script_path = SCRIPTS_DIR / "scan_staged_secrets.ps1"
    fixture_marker = "sk-" + "test-fixture-token"
    assignment_name = "API" + "_KEY"
    assignment_separator = "="
    safe_repo = tmp_path / "safe"
    allowed_repo = tmp_path / "allowed"
    rejected_repo = tmp_path / "rejected"
    for repository, relative_path, content in (
        (safe_repo, "readme.md", "safe change\n\n"),
        (
            allowed_repo,
            "tests/fixtures/secret-scan/allowed.fixture",
            f"{assignment_name}{assignment_separator}{fixture_marker}\n",
        ),
        (rejected_repo, "app.py", f"{assignment_name}{assignment_separator}{fixture_marker}\n"),
    ):
        path = repository / relative_path
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        subprocess.run(["git", "add", relative_path], cwd=repository, check=True)

    safe = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "Invoke-StagedSecretScan",
                "}",
            ]
        ),
        cwd=safe_repo,
    )
    allowed = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "Invoke-StagedSecretScan -AllowedTestFixturePath 'tests/fixtures/secret-scan/allowed.fixture'",
                "}",
            ]
        ),
        cwd=allowed_repo,
    )
    rejected = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "Invoke-StagedSecretScan",
                "}",
            ]
        ),
        cwd=rejected_repo,
        check=False,
    )

    assert safe.returncode == 0
    assert allowed.returncode == 0
    assert rejected.returncode != 0
    assert fixture_marker not in combined_output(rejected)


def test_v05_staged_secret_scanner_rejects_mapping_syntaxes_without_echoing_values(tmp_path: Path):
    script_path = SCRIPTS_DIR / "scan_staged_secrets.ps1"
    fixture_marker = "fixture-" + "sensitive-material"
    assignment_name = "API" + "_KEY"
    fixtures = {
        "yaml": f"{assignment_name}: {fixture_marker}\n",
        "json": json.dumps({assignment_name: fixture_marker}) + "\n",
        "toml": f'{assignment_name} = "{fixture_marker}"\n',
    }

    for syntax, content in fixtures.items():
        repository = tmp_path / syntax
        relative_path = f"config/runtime.{syntax}"
        path = repository / relative_path
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        subprocess.run(["git", "add", relative_path], cwd=repository, check=True)

        result = run_powershell(
            "\n".join(["& {", f". '{script_path}'", "Invoke-StagedSecretScan", "}"]),
            cwd=repository,
            check=False,
        )

        assert result.returncode != 0, syntax
        assert fixture_marker not in combined_output(result)


def test_v05_staged_secret_scanner_constrains_fixture_paths_and_markers(tmp_path: Path):
    script_path = SCRIPTS_DIR / "scan_staged_secrets.ps1"
    approved_marker = "sk-" + "test-approved-fixture"
    rejected_marker = "fixture-" + "sensitive-material"
    assignment_name = "API" + "_KEY"
    assignment_separator = "="
    cases = (
        (
            "approved",
            "tests/fixtures/secret-scan/allowed.fixture",
            approved_marker,
            "tests/fixtures/secret-scan/allowed.fixture",
            True,
        ),
        ("production", "config/runtime.yaml", approved_marker, "config/runtime.yaml", False),
        (
            "wrong-marker",
            "tests/fixtures/secret-scan/rejected.fixture",
            rejected_marker,
            "tests/fixtures/secret-scan/rejected.fixture",
            False,
        ),
    )

    for case_name, relative_path, marker, allowed_path, should_pass in cases:
        repository = tmp_path / case_name
        path = repository / relative_path
        path.parent.mkdir(parents=True)
        path.write_text(f"{assignment_name}{assignment_separator}{marker}\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        subprocess.run(["git", "add", relative_path], cwd=repository, check=True)

        result = run_powershell(
            "\n".join(
                [
                    "& {",
                    f". '{script_path}'",
                    f"Invoke-StagedSecretScan -AllowedTestFixturePath '{allowed_path}'",
                    "}",
                ]
            ),
            cwd=repository,
            check=False,
        )

        assert (result.returncode == 0) is should_pass, case_name
        assert marker not in combined_output(result)


def test_v05_staged_secret_scanner_rejects_later_sensitive_assignment_on_same_line(tmp_path: Path):
    script_path = SCRIPTS_DIR / "scan_staged_secrets.ps1"
    fixture_marker = "fixture-" + "later-sensitive-material"
    first_assignment_name = "ASR_API" + "_KEY"
    second_assignment_name = "TTS_API" + "_KEY"
    fixtures = {
        "json": json.dumps(
            {first_assignment_name: "placeholder", second_assignment_name: fixture_marker},
            separators=(",", ":"),
        )
        + "\n",
        "toml": (
            f'{first_assignment_name} = "placeholder", '
            f'{second_assignment_name} = "{fixture_marker}"\n'
        ),
    }

    for syntax, content in fixtures.items():
        repository = tmp_path / f"multi-{syntax}"
        relative_path = f"config/runtime.{syntax}"
        path = repository / relative_path
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        subprocess.run(["git", "add", relative_path], cwd=repository, check=True)

        result = run_powershell(
            "\n".join(["& {", f". '{script_path}'", "Invoke-StagedSecretScan", "}"]),
            cwd=repository,
            check=False,
        )

        assert result.returncode != 0, syntax
        assert fixture_marker not in combined_output(result)


def test_v05_staged_secret_scanner_requires_every_fixture_assignment_to_be_approved(tmp_path: Path):
    script_path = SCRIPTS_DIR / "scan_staged_secrets.ps1"
    first_approved_marker = "sk-" + "test-approved-first"
    second_approved_marker = "sk-" + "test-approved-second"
    rejected_marker = "fixture-" + "later-sensitive-material"
    first_assignment_name = "ASR_API" + "_KEY"
    second_assignment_name = "TTS_API" + "_KEY"
    relative_path = "tests/fixtures/secret-scan/multi.fixture"
    cases = (
        ("all-approved", second_approved_marker, True),
        ("mixed", rejected_marker, False),
    )

    for case_name, second_marker, should_pass in cases:
        repository = tmp_path / f"fixture-{case_name}"
        path = repository / relative_path
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    first_assignment_name: first_approved_marker,
                    second_assignment_name: second_marker,
                },
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        subprocess.run(["git", "add", relative_path], cwd=repository, check=True)

        result = run_powershell(
            "\n".join(
                [
                    "& {",
                    f". '{script_path}'",
                    f"Invoke-StagedSecretScan -AllowedTestFixturePath '{relative_path}'",
                    "}",
                ]
            ),
            cwd=repository,
            check=False,
        )

        assert (result.returncode == 0) is should_pass, case_name
        assert first_approved_marker not in combined_output(result)
        assert second_marker not in combined_output(result)


def test_v05_staged_secret_scanner_rejects_powershell_environment_assignments_without_echoing_values(
    tmp_path: Path,
):
    script_path = SCRIPTS_DIR / "scan_staged_secrets.ps1"
    assignment_name = "ASR_API" + "_KEY"
    synthetic_value = "fixture-" + "powershell-sensitive-material"
    repository = tmp_path / "powershell-assignment"
    relative_path = "scripts/runtime.ps1"
    path = repository / relative_path
    path.parent.mkdir(parents=True)
    path.write_text(f"$env:{assignment_name} = '{synthetic_value}'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "add", relative_path], cwd=repository, check=True)

    result = run_powershell(
        "\n".join(["& {", f". '{script_path}'", "Invoke-StagedSecretScan", "}"]),
        cwd=repository,
        check=False,
    )

    assert result.returncode != 0
    assert synthetic_value not in combined_output(result)


def test_v05_staged_secret_scanner_rejects_mixed_powershell_fixture_assignments(tmp_path: Path):
    script_path = SCRIPTS_DIR / "scan_staged_secrets.ps1"
    approved_value = "sk-" + "test-approved-powershell"
    rejected_value = "fixture-" + "powershell-sensitive-material"
    first_name = "ASR_API" + "_KEY"
    second_name = "TTS_API" + "_KEY"
    repository = tmp_path / "mixed-powershell-fixture"
    relative_path = "tests/fixtures/secret-scan/powershell.fixture"
    path = repository / relative_path
    path.parent.mkdir(parents=True)
    path.write_text(
        f"$env:{first_name} = '{approved_value}'; $env:{second_name} = '{rejected_value}'\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "add", relative_path], cwd=repository, check=True)

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                f"Invoke-StagedSecretScan -AllowedTestFixturePath '{relative_path}'",
                "}",
            ]
        ),
        cwd=repository,
        check=False,
    )

    assert result.returncode != 0
    assert approved_value not in combined_output(result)
    assert rejected_value not in combined_output(result)


def test_v05_staged_secret_scanner_rejects_indexed_python_environment_assignments_without_echoing_values(
    tmp_path: Path,
):
    script_path = SCRIPTS_DIR / "scan_staged_secrets.ps1"
    assignment_name = "ASR_API" + "_KEY"
    synthetic_value = "fixture-" + "python-sensitive-material"
    repository = tmp_path / "python-assignment"
    relative_path = "runtime/config.py"
    path = repository / relative_path
    path.parent.mkdir(parents=True)
    path.write_text(
        f'os.environ["{assignment_name}"] = "{synthetic_value}"\n', encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "add", relative_path], cwd=repository, check=True)

    result = run_powershell(
        "\n".join(["& {", f". '{script_path}'", "Invoke-StagedSecretScan", "}"]),
        cwd=repository,
        check=False,
    )

    assert result.returncode != 0
    assert synthetic_value not in combined_output(result)


def test_v05_staged_secret_scanner_rejects_mixed_indexed_python_fixture_assignments(tmp_path: Path):
    script_path = SCRIPTS_DIR / "scan_staged_secrets.ps1"
    approved_value = "sk-" + "test-approved-python"
    rejected_value = "fixture-" + "python-sensitive-material"
    first_name = "ASR_API" + "_KEY"
    second_name = "TTS_API" + "_KEY"
    repository = tmp_path / "mixed-python-fixture"
    relative_path = "tests/fixtures/secret-scan/python.fixture"
    path = repository / relative_path
    path.parent.mkdir(parents=True)
    path.write_text(
        f"os.environ['{first_name}'] = '{approved_value}'; "
        f'os.environ["{second_name}"] = "{rejected_value}"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "add", relative_path], cwd=repository, check=True)

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                f"Invoke-StagedSecretScan -AllowedTestFixturePath '{relative_path}'",
                "}",
            ]
        ),
        cwd=repository,
        check=False,
    )

    assert result.returncode != 0
    assert approved_value not in combined_output(result)
    assert rejected_value not in combined_output(result)


def test_check_local_demo_status_reports_ports_config_and_runtime_patch(tmp_path: Path):
    script_path = SCRIPTS_DIR / "check_local_demo_status.ps1"
    config_path = tmp_path / "data" / ".config.yaml"
    provider_path = tmp_path / "core" / "providers" / "llm" / "openai" / "openai.py"
    connection_path = tmp_path / "core" / "connection.py"
    config_path.parent.mkdir(parents=True)
    provider_path.parent.mkdir(parents=True)
    connection_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                "selected_module:",
                "  LLM: BuddyCoreLLM",
                "LLM:",
                "  BuddyCoreLLM:",
                "    base_url: http://192.168.0.101:8010/v1",
                "    forward_device_metadata: true",
            ]
        ),
        encoding="utf-8",
    )
    provider_path.write_text("forward_device_metadata\nmetadata[\"device_id\"] = device_id\n", encoding="utf-8")
    connection_path.write_text("llm_kwargs = {}\nself.headers.get(\"client-id\", self.device_id)\n", encoding="utf-8")

    result = run_powershell(
        "\n".join(
            [
                "& {",
                f". '{script_path}'",
                "function Get-NetTCPConnection {",
                "  @(",
                "    [pscustomobject]@{ LocalPort = 8000; OwningProcess = 10; State = 'Listen' },",
                "    [pscustomobject]@{ LocalPort = 8003; OwningProcess = 10; State = 'Listen' },",
                "    [pscustomobject]@{ LocalPort = 8010; OwningProcess = 20; State = 'Listen' }",
                "  )",
                "}",
                f"Invoke-CheckLocalDemoStatus -ConfigPath '{config_path}' -ServerDir '{tmp_path}' | ConvertTo-Json -Compress",
                "}",
            ]
        )
    )
    payload = json.loads(result.stdout)

    assert payload["Ports"]["8000"] is True
    assert payload["Ports"]["8003"] is True
    assert payload["Ports"]["8010"] is True
    assert payload["Config"]["BuddyCoreLLM"] is True
    assert payload["Config"]["ForwardDeviceMetadata"] is True
    assert payload["RuntimePatch"]["ProviderMetadata"] is True
    assert payload["RuntimePatch"]["ConnectionMetadata"] is True


def test_start_xiaozhi_script_uses_conda_environment():
    text = (SCRIPTS_DIR / "start_xiaozhi_server.ps1").read_text(encoding="utf-8")

    assert "conda run --no-capture-output" in text
    assert 'CondaEnv = "xiaozhi-env"' in text
    assert "python $appPath" in text


def test_start_xiaozhi_script_resolves_default_server_dir_from_repo_root():
    script_path = SCRIPTS_DIR / "start_xiaozhi_server.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; Get-ResolvedXiaoZhiServerDir -ServerDir 'xiaozhi_server' }}",
        cwd=REPO_ROOT.parent,
    )

    expected = REPO_ROOT / "xiaozhi_server"
    assert Path(result.stdout.strip()) == expected


def test_start_xiaozhi_script_preflight_requires_app_core_config_and_local_config(tmp_path: Path):
    script_path = SCRIPTS_DIR / "start_xiaozhi_server.ps1"
    server_dir = tmp_path / "xiaozhi-server"
    (server_dir / "data").mkdir(parents=True)
    (server_dir / "data" / ".config.yaml").write_text("demo: true\n", encoding="utf-8")

    result = run_powershell(
        f"& {{ . '{script_path}'; Assert-XiaoZhiServerPreflight -ResolvedServerDir '{server_dir}' }}",
        check=False,
    )

    assert result.returncode != 0
    assert "app.py" in combined_output(result)


def test_start_xiaozhi_script_preflight_requires_core_directory(tmp_path: Path):
    script_path = SCRIPTS_DIR / "start_xiaozhi_server.ps1"
    server_dir = tmp_path / "xiaozhi-server"
    (server_dir / "data").mkdir(parents=True)
    (server_dir / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (server_dir / "config").mkdir()
    (server_dir / "data" / ".config.yaml").write_text("demo: true\n", encoding="utf-8")

    result = run_powershell(
        f"& {{ . '{script_path}'; Assert-XiaoZhiServerPreflight -ResolvedServerDir '{server_dir}' }}",
        check=False,
    )

    assert result.returncode != 0
    assert "core" in combined_output(result).lower()


def test_start_xiaozhi_script_rejects_server_dir_outside_runtime_before_calling_conda(tmp_path: Path):
    script_path = SCRIPTS_DIR / "start_xiaozhi_server.ps1"
    server_dir = tmp_path / "xiaozhi-server"
    (server_dir / "data").mkdir(parents=True)
    (server_dir / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (server_dir / "data" / ".config.yaml").write_text("demo: true\n", encoding="utf-8")

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:conda { throw 'conda should not be called' }",
                f". '{script_path}'",
                f"Invoke-StartXiaoZhiServer -ServerDir '{server_dir}'",
                "}",
            ]
        ),
        check=False,
    )

    assert result.returncode != 0
    combined = combined_output(result).lower()
    assert "xiaozhi_server" in combined
    assert "conda should not be called" not in combined


def test_start_xiaozhi_script_invokes_conda_from_resolved_server_dir():
    script_path = SCRIPTS_DIR / "start_xiaozhi_server.ps1"
    server_dir = REPO_ROOT / "xiaozhi_server"
    config_path = server_dir / "data" / ".config.yaml"
    original = config_path.read_bytes() if config_path.exists() else None
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("server: {}\n", encoding="utf-8")

    try:
        result = run_powershell(
            "\n".join(
                [
                    "& {",
                    "function global:conda {",
                    "  param([Parameter(ValueFromRemainingArguments = $true)] $Args)",
                    "  [pscustomobject]@{",
                    "    Args = @($Args)",
                    "    Location = (Get-Location).Path",
                    "  } | ConvertTo-Json -Compress",
                    "}",
                    f". '{script_path}'",
                    f"Invoke-StartXiaoZhiServer -ServerDir '{server_dir}'",
                    "}",
                ]
            )
        )
        payload = json.loads(result.stdout.splitlines()[-1])
    finally:
        if original is None:
            config_path.unlink(missing_ok=True)
        else:
            config_path.write_bytes(original)

    assert [str(arg) for arg in payload["Args"]] == [
        "run",
        "--no-capture-output",
        "-n",
        "xiaozhi-env",
        "python",
        str(server_dir / "app.py"),
    ]
    assert Path(payload["Location"]) == server_dir
    assert "WebSocket endpoint: ws://<LAN-IP>:8000/xiaozhi/v1/" in result.stdout
    assert "OTA endpoint: http://<LAN-IP>:8003/xiaozhi/ota/" in result.stdout


def test_dependency_checker_prints_repair_command_without_installing_on_failure():
    script_path = SCRIPTS_DIR / "check_xiaozhi_dependencies.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:conda { throw 'simulated pip check failure' }",
                f". '{script_path}'",
                "Invoke-CheckXiaoZhiDependencies",
                "}",
            ]
        ),
        check=False,
    )

    combined = combined_output(result)
    assert result.returncode != 0
    assert "conda run -n xiaozhi-env python -m pip install -r .\\xiaozhi_server\\requirements.txt" in combined
    assert "pip install -r" not in combined.replace(
        "conda run -n xiaozhi-env python -m pip install -r .\\xiaozhi_server\\requirements.txt", ""
    )


def test_dependency_checker_checks_and_imports_native_selected_modules():
    text = (SCRIPTS_DIR / "check_xiaozhi_dependencies.ps1").read_text(encoding="utf-8")

    assert "python -m pip check" in text
    assert "python -B -c" in text
    assert "core.providers.asr.fun_local" in text
    assert "core.providers.llm.openai.openai" in text
    assert "core.providers.tts.edge" in text
