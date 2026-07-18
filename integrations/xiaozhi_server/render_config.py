from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
from pathlib import Path
from string import Template


TEMPLATE_PATH = Path(__file__).with_name("xiaozhi_config_template.yaml")
LAN_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
ASR_ENVIRONMENT_NAMES = (
    "ASR_PROVIDER",
    "ASR_HTTP_URL",
    "ASR_MODEL",
    "ASR_API_KEY",
    "ASR_TIMEOUT_SECONDS",
)
TTS_ENVIRONMENT_NAMES = (
    "TTS_PROVIDER",
    "TTS_HTTP_URL",
    "TTS_MODEL",
    "TTS_API_KEY",
    "TTS_VOICE",
    "TTS_LANGUAGE",
    "TTS_TIMEOUT_SECONDS",
)


def validate_host_ip(host_ip: str) -> str:
    try:
        ip = ipaddress.ip_address(host_ip)
    except ValueError as exc:
        raise ValueError(f"host_ip must be an IPv4 LAN address, got {host_ip!r}") from exc

    if (
        ip.version != 4
        or ip.is_loopback
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_link_local
        or not any(ip in network for network in LAN_NETWORKS)
    ):
        raise ValueError(f"host_ip must be reachable by the ESP32 on the LAN, got {host_ip!r}")

    return str(ip)


def get_asr_environment(
    *, process_environment: dict[str, str] | None = None, user_environment: dict[str, str] | None = None
) -> dict[str, str]:
    process_environment = process_environment if process_environment is not None else os.environ
    if user_environment is None:
        user_environment = {
            name: os.environ.get(name, "")
            for name in ASR_ENVIRONMENT_NAMES
        }
        if os.name == "nt":
            import winreg

            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                    for name in ASR_ENVIRONMENT_NAMES:
                        try:
                            user_environment[name] = winreg.QueryValueEx(key, name)[0]
                        except FileNotFoundError:
                            continue
            except OSError:
                pass

    return {
        name: str(process_environment.get(name) or user_environment.get(name) or "").strip()
        for name in ASR_ENVIRONMENT_NAMES
    }


def validate_asr_environment(environment: dict[str, str]) -> dict[str, str]:
    required = ("ASR_PROVIDER", "ASR_HTTP_URL", "ASR_MODEL", "ASR_API_KEY")
    missing = [name for name in required if not environment.get(name)]
    try:
        timeout = float(environment.get("ASR_TIMEOUT_SECONDS", ""))
    except ValueError:
        timeout = 0
    if missing or not math.isfinite(timeout) or timeout <= 0:
        requirements = ", ".join((*required, "a positive ASR_TIMEOUT_SECONDS"))
        raise ValueError(f"ASR live mode requires {requirements}.")

    validated = dict(environment)
    validated["ASR_TIMEOUT_SECONDS"] = format(timeout, "g")
    return validated


def get_tts_environment(
    *, process_environment: dict[str, str] | None = None, user_environment: dict[str, str] | None = None
) -> dict[str, str]:
    process_environment = process_environment if process_environment is not None else os.environ
    if user_environment is None:
        user_environment = {
            name: os.environ.get(name, "")
            for name in TTS_ENVIRONMENT_NAMES
        }
        if os.name == "nt":
            import winreg

            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                    for name in TTS_ENVIRONMENT_NAMES:
                        try:
                            user_environment[name] = winreg.QueryValueEx(key, name)[0]
                        except FileNotFoundError:
                            continue
            except OSError:
                pass

    return {
        name: str(process_environment.get(name) or user_environment.get(name) or "").strip()
        for name in TTS_ENVIRONMENT_NAMES
    }


def validate_tts_environment(environment: dict[str, str]) -> dict[str, str]:
    required = ("TTS_PROVIDER", "TTS_HTTP_URL", "TTS_MODEL", "TTS_API_KEY", "TTS_VOICE")
    missing = [name for name in required if not environment.get(name)]
    try:
        timeout = float(environment.get("TTS_TIMEOUT_SECONDS", ""))
    except ValueError:
        timeout = 0
    if missing or not math.isfinite(timeout) or timeout <= 0:
        requirements = ", ".join((*required, "a positive TTS_TIMEOUT_SECONDS"))
        raise ValueError(f"TTS live mode requires {requirements}.")

    validated = dict(environment)
    validated["TTS_TIMEOUT_SECONDS"] = format(timeout, "g")
    return validated


def render_config(
    host_ip: str,
    *,
    process_environment: dict[str, str] | None = None,
    user_environment: dict[str, str] | None = None,
) -> str:
    safe_ip = validate_host_ip(host_ip)
    asr_environment = validate_asr_environment(
        get_asr_environment(
            process_environment=process_environment,
            user_environment=user_environment,
        )
    )
    tts_environment = validate_tts_environment(
        get_tts_environment(
            process_environment=process_environment,
            user_environment=user_environment,
        )
    )
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    substitutions = {
        "HOST_IP": safe_ip,
        **{name: json.dumps(value) for name, value in asr_environment.items()},
        **{name: json.dumps(value) for name, value in tts_environment.items()},
    }
    return template.substitute(substitutions)


def default_output_path(repo_root: Path) -> Path:
    return repo_root / "xiaozhi_server" / "data" / ".config.yaml"


def allowed_output_dir(repo_root: Path) -> Path:
    return default_output_path(repo_root).parent


def resolve_output_path(repo_root: Path, output_path: Path | None) -> Path:
    repo_root = repo_root.resolve(strict=False)
    default_output = default_output_path(repo_root).resolve(strict=False)
    allowed_dir = allowed_output_dir(repo_root).resolve(strict=False)
    if output_path is None:
        candidate = default_output
    elif output_path.is_absolute():
        candidate = output_path.resolve(strict=False)
    else:
        candidate = (repo_root / output_path).resolve(strict=False)

    if candidate == default_output:
        return candidate

    if candidate.parent != allowed_dir:
        raise ValueError(f"output must stay under {allowed_dir}, got {candidate}")

    return candidate


def write_config(
    host_ip: str,
    output_path: Path,
    *,
    repo_root: Path | None = None,
    process_environment: dict[str, str] | None = None,
    user_environment: dict[str, str] | None = None,
) -> Path:
    output_path = resolve_output_path(repo_root or Path.cwd(), output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_config(
            host_ip,
            process_environment=process_environment,
            user_environment=user_environment,
        ),
        encoding="utf-8",
    )
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
        help="Output .config.yaml path. Defaults to xiaozhi_server/data/.config.yaml.",
    )
    args = parser.parse_args()

    output = resolve_output_path(args.repo_root, args.output)
    written = write_config(args.host_ip, output, repo_root=args.repo_root)
    print(written)


if __name__ == "__main__":
    main()
