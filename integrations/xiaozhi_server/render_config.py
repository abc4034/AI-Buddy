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
