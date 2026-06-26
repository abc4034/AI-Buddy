from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
from string import Template


TEMPLATE_PATH = Path(__file__).with_name("xiaozhi_config_template.yaml")
LAN_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
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


def render_config(host_ip: str) -> str:
    safe_ip = validate_host_ip(host_ip)
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    return template.substitute(HOST_IP=safe_ip)


def default_output_path(repo_root: Path) -> Path:
    return repo_root / ".run" / "xiaozhi-esp32-server" / "main" / "xiaozhi-server" / "data" / ".config.yaml"


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


def write_config(host_ip: str, output_path: Path, *, repo_root: Path | None = None) -> Path:
    output_path = resolve_output_path(repo_root or Path.cwd(), output_path)
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

    output = resolve_output_path(args.repo_root, args.output)
    written = write_config(args.host_ip, output, repo_root=args.repo_root)
    print(written)


if __name__ == "__main__":
    main()
