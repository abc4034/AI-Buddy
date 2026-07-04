import json
import shutil
import subprocess
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

SCRIPTS = [
    "backup_local_demo_data.ps1",
    "check_local_demo_status.ps1",
    "render_xiaozhi_config.ps1",
    "setup_xiaozhi_server.ps1",
    "start_buddy_core.ps1",
    "start_buddy_gateway.ps1",
    "start_buddy_brain.ps1",
    "start_xiaozhi_server.ps1",
    "stop_local_demo.ps1",
    "print_local_demo_urls.ps1",
    "smoke_chat.ps1",
    "smoke_gateway_audio_capture.ps1",
    "smoke_gateway_text_loop.ps1",
    "smoke_two_devices.ps1",
]


def run_powershell(command: str, *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    ps_command = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "$OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        + command
    )
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


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
    assert ".run" in combined
    assert "py should not be called" not in combined


def test_render_script_allows_custom_output_under_runtime_data():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"
    output = REPO_ROOT / ".run" / "xiaozhi-esp32-server" / "main" / "xiaozhi-server" / "data" / "custom.config.yaml"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:py { param([Parameter(ValueFromRemainingArguments = $true)] $Args) $Args | ConvertTo-Json -Compress }",
                f"& '{script_path}' -HostIp '192.168.2.9' -Output '{output}'",
                "}",
            ]
        )
    )
    args = json.loads(result.stdout.splitlines()[-1])

    output_arg = args[args.index("--output") + 1]
    assert output_arg.endswith("\\.run\\xiaozhi-esp32-server\\main\\xiaozhi-server\\data\\custom.config.yaml")


def test_render_script_rejects_nested_output_under_runtime_data_before_calling_py():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"
    output = REPO_ROOT / ".run" / "xiaozhi-esp32-server" / "main" / "xiaozhi-server" / "data" / "nested" / "custom.config.yaml"

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
    assert ".run" in combined
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
                "Invoke-StartBuddyGateway -BindHost '127.0.0.1' -HttpPort 18003 -WebSocketPort 18000 -AdvertiseHost '192.168.0.101' -BuddyCoreBaseUrl 'http://127.0.0.1:18010' -AudioArtifactDir 'tmp\\gateway-audio' -AudioSessionLimit 3",
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
    ]


def test_start_buddy_gateway_script_uses_xiaozhi_compatible_ports_by_default():
    text = (SCRIPTS_DIR / "start_buddy_gateway.ps1").read_text(encoding="utf-8")

    assert "[int]$HttpPort = 8003" in text
    assert "[int]$WebSocketPort = 8000" in text
    assert '[string]$BuddyCoreBaseUrl = "http://127.0.0.1:8010"' in text
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

    assert "conda run" in text
    assert 'CondaEnv = "xiaozhi-env"' in text
    assert "python app.py" in text


def test_start_xiaozhi_script_resolves_default_server_dir_from_repo_root():
    script_path = SCRIPTS_DIR / "start_xiaozhi_server.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; Get-ResolvedXiaoZhiServerDir -ServerDir '.run\\xiaozhi-esp32-server\\main\\xiaozhi-server' }}",
        cwd=REPO_ROOT.parent,
    )

    expected = REPO_ROOT / ".run" / "xiaozhi-esp32-server" / "main" / "xiaozhi-server"
    assert Path(result.stdout.strip()) == expected


def test_start_xiaozhi_script_preflight_fails_when_app_py_missing():
    script_path = SCRIPTS_DIR / "start_xiaozhi_server.ps1"
    runtime_root = REPO_ROOT / ".run" / f"pytest-missing-app-{uuid.uuid4().hex}"
    server_dir = runtime_root / "main" / "xiaozhi-server"
    (server_dir / "data").mkdir(parents=True)
    (server_dir / "data" / ".config.yaml").write_text("demo: true\n", encoding="utf-8")

    try:
        result = run_powershell(
            f"& {{ . '{script_path}'; Invoke-StartXiaoZhiServer -ServerDir '{server_dir}' }}",
            check=False,
        )
    finally:
        if runtime_root.exists():
            shutil.rmtree(runtime_root)

    assert result.returncode != 0
    assert "app.py" in combined_output(result)


def test_start_xiaozhi_script_preflight_fails_when_config_missing():
    script_path = SCRIPTS_DIR / "start_xiaozhi_server.ps1"
    runtime_root = REPO_ROOT / ".run" / f"pytest-missing-config-{uuid.uuid4().hex}"
    server_dir = runtime_root / "main" / "xiaozhi-server"
    (server_dir / "data").mkdir(parents=True)
    (server_dir / "app.py").write_text("print('ok')\n", encoding="utf-8")

    try:
        result = run_powershell(
            f"& {{ . '{script_path}'; Invoke-StartXiaoZhiServer -ServerDir '{server_dir}' }}",
            check=False,
        )
    finally:
        if runtime_root.exists():
            shutil.rmtree(runtime_root)

    assert result.returncode != 0
    assert ".config.yaml" in combined_output(result)


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
    assert ".run" in combined
    assert "conda should not be called" not in combined


def test_start_xiaozhi_script_invokes_conda_from_resolved_server_dir():
    script_path = SCRIPTS_DIR / "start_xiaozhi_server.ps1"
    runtime_root = REPO_ROOT / ".run" / f"pytest-start-{uuid.uuid4().hex}"
    server_dir = runtime_root / "main" / "xiaozhi-server"
    (server_dir / "data").mkdir(parents=True)
    (server_dir / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (server_dir / "data" / ".config.yaml").write_text("demo: true\n", encoding="utf-8")

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
        if runtime_root.exists():
            shutil.rmtree(runtime_root)

    assert [str(arg) for arg in payload["Args"]] == [
        "run",
        "--no-capture-output",
        "-n",
        "xiaozhi-env",
        "python",
        "app.py",
    ]
    assert payload["Location"].endswith("\\.run\\" + runtime_root.name + "\\main\\xiaozhi-server")
