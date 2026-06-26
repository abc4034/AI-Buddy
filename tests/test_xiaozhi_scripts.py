import json
import subprocess
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
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        check=check,
    )


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
    assert "strict child" in (result.stderr or result.stdout)


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


def test_render_prefers_192_168_2_addresses():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; @('10.0.0.8', '172.20.5.4', '192.168.2.44', '192.168.1.10') | Select-PreferredLanIp }}"
    )

    assert result.stdout.strip() == "192.168.2.44"


def test_render_script_preserves_manual_host_ip_and_repo_root():
    script_path = SCRIPTS_DIR / "render_xiaozhi_config.ps1"

    result = run_powershell(
        "\n".join(
            [
                "& {",
                "function global:py { param([Parameter(ValueFromRemainingArguments = $true)] $Args) $Args | ConvertTo-Json -Compress }",
                f"& '{script_path}' -HostIp '172.200.1.1'",
                "}",
            ]
        ),
        cwd=REPO_ROOT.parent,
    )

    args = json.loads(result.stdout.splitlines()[-1])
    repo_root_arg = args[args.index("--repo-root") + 1]

    assert "172.200.1.1" in args
    assert repo_root_arg.endswith("\\AI Buddy\\.worktrees\\codex-xiaozhi-buddy-bridge")
    assert not repo_root_arg.endswith("\\AI Buddy\\.worktrees")


def test_demo_url_script_uses_precise_rfc1918_selection():
    script_path = SCRIPTS_DIR / "print_local_demo_urls.ps1"

    result = run_powershell(
        f"& {{ . '{script_path}'; @('172.200.1.1', '10.0.0.5', '192.168.2.20') | Select-PreferredLanIp }}"
    )

    assert result.stdout.strip() == "192.168.2.20"


def test_start_xiaozhi_script_uses_conda_environment():
    text = (SCRIPTS_DIR / "start_xiaozhi_server.ps1").read_text(encoding="utf-8")

    assert "conda run" in text
    assert "xiaozhi-esp32-server" in text
    assert "python app.py" in text
