import json
import shutil
import subprocess
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

SCRIPTS = [
    "render_xiaozhi_config.ps1",
    "setup_xiaozhi_server.ps1",
    "start_buddy_brain.ps1",
    "start_xiaozhi_server.ps1",
    "print_local_demo_urls.ps1",
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
                    "  New-Item -ItemType Directory -Force -Path (Join-Path $DestinationPath 'xiaozhi-esp32-server-main') | Out-Null",
                    "  New-Item -ItemType Directory -Force -Path (Join-Path $DestinationPath 'xiaozhi-esp32-server-main\\main\\xiaozhi-server') | Out-Null",
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


def test_render_auto_detection_prefers_exact_demo_host():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; @('10.0.0.8', '172.20.5.4', '192.168.2.44', '192.168.2.9', '192.168.1.10') | Select-PreferredLanIp }}"
    )

    assert result.stdout.strip() == "192.168.2.9"


def test_render_auto_detection_requires_explicit_host_without_exact_demo_host():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; @('10.0.0.8', '172.20.5.4', '192.168.2.44', '192.168.1.10') | Select-PreferredLanIp }}",
        check=False,
    )

    assert result.returncode != 0
    output = combined_output(result)
    assert "192.168.2.9" in output
    assert "HostIp" in output


def test_render_script_preserves_manual_host_ip_and_repo_root():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:py { param([Parameter(ValueFromRemainingArguments = $true)] $Args) $Args | ConvertTo-Json -Compress }",
                f"& '{script_path}' -HostIp '192.168.2.9'",
                "}",
            ]
        ),
        cwd=REPO_ROOT.parent,
    )

    args = json.loads(result.stdout.splitlines()[-1])
    repo_root_arg = args[args.index("--repo-root") + 1]

    assert "192.168.2.9" in args
    assert Path(repo_root_arg) == REPO_ROOT
    assert not repo_root_arg.endswith("\\AI Buddy\\.worktrees")


def test_render_script_rejects_invalid_manual_host_ip_before_calling_py():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"

    for host_ip in ("127.0.0.1", "8.8.8.8", "192.168.2.44", "10.0.0.5"):
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
        assert "192.168.2.9" in combined
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


def test_demo_url_script_auto_detection_prefers_exact_demo_host():
    script_path = SCRIPTS_DIR / "print_local_demo_urls.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; @('172.200.1.1', '10.0.0.5', '192.168.2.20', '192.168.2.9') | Select-PreferredLanIp }}"
    )

    assert result.stdout.strip() == "192.168.2.9"


def test_demo_url_script_auto_detection_requires_explicit_host_without_exact_demo_host():
    script_path = SCRIPTS_DIR / "print_local_demo_urls.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; @('172.200.1.1', '10.0.0.5', '192.168.2.20') | Select-PreferredLanIp }}",
        check=False,
    )

    assert result.returncode != 0
    output = combined_output(result)
    assert "192.168.2.9" in output
    assert "HostIp" in output


def test_demo_url_script_rejects_invalid_manual_host_ip_values():
    script_path = SCRIPTS_DIR / "print_local_demo_urls.ps1"

    for host_ip in ("127.0.0.1", "8.8.8.8", "192.168.2.44", "10.0.0.5"):
        result = run_powershell(
            f"& {{ . '{script_path}'; Invoke-PrintLocalDemoUrls -HostIp '{host_ip}' }}",
            check=False,
        )

        assert result.returncode != 0, host_ip
        assert "192.168.2.9" in combined_output(result)


def test_demo_url_script_prints_expected_urls_for_valid_manual_host_ip():
    script_path = SCRIPTS_DIR / "print_local_demo_urls.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; Invoke-PrintLocalDemoUrls -HostIp '192.168.2.9' }}"
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    assert lines == [
        "Buddy Brain health: http://192.168.2.9:8010/health",
        "Buddy Brain OpenAI base_url: http://192.168.2.9:8010/v1",
        "XiaoZhi OTA URL: http://192.168.2.9:8003/xiaozhi/ota/",
        "XiaoZhi WebSocket URL: ws://192.168.2.9:8000/xiaozhi/v1/",
        "Firmware OTA value, if flashing is needed: CONFIG_OTA_URL=http://192.168.2.9:8003/xiaozhi/ota/",
    ]


def test_start_buddy_brain_script_uses_fixed_host_and_port_by_default():
    script_path = SCRIPTS_DIR / "start_buddy_brain.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:py { param([Parameter(ValueFromRemainingArguments = $true)] $Args) $Args | ConvertTo-Json -Compress }",
                f"& '{script_path}'",
                "}",
            ]
        )
    )
    args = json.loads(result.stdout.splitlines()[-1])

    assert [str(arg) for arg in args] == [
        "-3.10",
        "-m",
        "uvicorn",
        "buddy_brain.app:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8010",
    ]


def test_start_buddy_brain_script_rejects_non_contract_port_before_calling_py():
    script_path = SCRIPTS_DIR / "start_buddy_brain.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:py { throw 'py should not be called' }",
                f"& '{script_path}' -Port 8011",
                "}",
            ]
        ),
        check=False,
    )

    assert result.returncode != 0
    combined = combined_output(result).lower()
    assert "8010" in combined
    assert "py should not be called" not in combined


def test_start_xiaozhi_script_uses_conda_environment():
    text = (SCRIPTS_DIR / "start_xiaozhi_server.ps1").read_text(encoding="utf-8")

    assert "conda run" in text
    assert "xiaozhi-esp32-server" in text
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

    assert [str(arg) for arg in payload["Args"]] == ["run", "-n", "xiaozhi-esp32-server", "python", "app.py"]
    assert payload["Location"].endswith("\\.run\\" + runtime_root.name + "\\main\\xiaozhi-server")
