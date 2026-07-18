"""Deterministic provenance checks for the imported XiaoZhi runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


EXCLUDED_PARTS = {"data", "tmp", "__pycache__"}
REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_ROOT / "xiaozhi_server"
THIRD_PARTY_DIR = REPO_ROOT / "third_party" / "xiaozhi-esp32-server"
SOURCE_MANIFEST_PATH = THIRD_PARTY_DIR / "SOURCE_MANIFEST.json"
PATCH_MANIFEST_PATH = THIRD_PARTY_DIR / "PATCH_MANIFEST.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(root: Path):
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or (
            relative.parts and relative.parts[0] in {"data", "tmp"}
        ):
            continue
        yield relative.as_posix(), path


def build_manifest(source_dir: Path, imported_dir: Path, metadata: dict) -> dict:
    """Build the upstream file inventory; imported_dir keeps the public API explicit."""
    del imported_dir
    return {
        "schema_version": 1,
        "upstream": dict(metadata),
        "files": [
            {"path": relative, "sha256": sha256_file(path)}
            for relative, path in _iter_files(source_dir)
        ],
    }


def _file_hashes(root: Path) -> dict[str, str]:
    return {relative: sha256_file(path) for relative, path in _iter_files(root)}


def _patches_by_path(patch_manifest: dict) -> dict[str, dict]:
    return {patch["path"]: patch for patch in patch_manifest.get("patches", [])}


def verify_manifest(imported_dir: Path, source_manifest: dict, patch_manifest: dict) -> list[str]:
    source_hashes = {entry["path"]: entry["sha256"] for entry in source_manifest["files"]}
    imported_hashes = _file_hashes(imported_dir)
    patches = _patches_by_path(patch_manifest)
    errors: list[str] = []

    for path in sorted(source_hashes):
        original = source_hashes[path]
        current = imported_hashes.pop(path, None)
        patch = patches.get(path)
        if current is None:
            if patch and patch == {
                "path": path,
                "status": "deleted",
                "reason": patch["reason"],
                "original_sha256": original,
                "current_sha256": None,
            }:
                continue
            errors.append("missing:" + path)
        elif current != original:
            if patch and patch == {
                "path": path,
                "status": "modified",
                "reason": patch["reason"],
                "original_sha256": original,
                "current_sha256": current,
            }:
                continue
            errors.append(("patch-hash-mismatch:" if patch else "unrecorded-modification:") + path)

    for path in sorted(imported_hashes):
        current = imported_hashes[path]
        patch = patches.get(path)
        if patch and patch == {
            "path": path,
            "status": "added",
            "reason": patch["reason"],
            "original_sha256": None,
            "current_sha256": current,
        }:
            continue
        errors.append(("patch-hash-mismatch:" if patch else "unexpected:") + path)

    return errors


def _reason_map(reasons: dict) -> dict[str, str]:
    if "reasons" in reasons:
        entries = reasons["reasons"]
        return {entry["path"]: entry["reason"] for entry in entries}
    return {
        path: value["reason"] if isinstance(value, dict) else value
        for path, value in reasons.items()
    }


def update_patch_manifest(imported_dir: Path, source_manifest: dict, reasons: dict) -> dict:
    source_hashes = {entry["path"]: entry["sha256"] for entry in source_manifest["files"]}
    imported_hashes = _file_hashes(imported_dir)
    reviewed = _reason_map(reasons)
    changes: list[tuple[str, str, str | None, str | None]] = []

    for path in sorted(source_hashes):
        original = source_hashes[path]
        current = imported_hashes.pop(path, None)
        if current is None:
            changes.append((path, "deleted", original, None))
        elif current != original:
            changes.append((path, "modified", original, current))
    for path in sorted(imported_hashes):
        changes.append((path, "added", None, imported_hashes[path]))

    unreviewed = [path for path, _, _, _ in changes if path not in reviewed]
    if unreviewed:
        raise ValueError("unreviewed patch path(s): " + ", ".join(unreviewed))

    return {
        "schema_version": 1,
        "patches": [
            {
                "path": path,
                "status": status,
                "reason": reviewed[path],
                "original_sha256": original,
                "current_sha256": current,
            }
            for path, status, original, current in changes
        ],
    }


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    return (
        not normalized
        or normalized in {"none", "null", "local", "lm-studio"}
        or "placeholder" in normalized
        or "your" in normalized
        or "xxx" in normalized
        or "你的" in value
    )


def _is_bearer_placeholder(token: str) -> bool:
    return re.fullmatch(r"[A-Z][A-Z0-9_]*", token) is not None


def scan_secrets(root: Path = RUNTIME_DIR) -> list[str]:
    findings: list[str] = []
    api_key = re.compile(r"(?im)^\s*api_key\s*:\s*(?P<value>[^#\r\n]+)")
    bearer = re.compile(r"(?i)\bbearer\s+(?P<token>[a-z0-9._-]{8,})")
    openai_key = re.compile(r"\bsk-[a-z0-9_-]{8,}")
    for relative, path in _iter_files(root):
        if path.suffix.lower() in {".mp3", ".onnx", ".bin", ".pt", ".pth"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if openai_key.search(text) or any(
            not _is_bearer_placeholder(match.group("token")) for match in bearer.finditer(text)
        ):
            findings.append("secret-pattern:" + relative)
        for match in api_key.finditer(text):
            if not _is_placeholder(match.group("value")):
                findings.append("non-placeholder-api-key:" + relative)
                break
    return sorted(findings)


def _command_build_manifest(args: argparse.Namespace) -> int:
    upstream = _read_json(Path(args.metadata_file))
    metadata = {key: upstream[key] for key in ("origin", "commit", "tree", "archive_sha256", "source_subtree")}
    _write_json(Path(args.upstream_file), upstream)
    _write_json(Path(args.source_manifest), build_manifest(Path(args.source_dir), Path(args.imported_dir), metadata))
    return 0


def _command_update_patches(args: argparse.Namespace) -> int:
    manifest = _read_json(SOURCE_MANIFEST_PATH)
    reasons = _read_json(Path(args.reason_file))
    _write_json(PATCH_MANIFEST_PATH, update_patch_manifest(RUNTIME_DIR, manifest, reasons))
    return 0


def _command_verify(_: argparse.Namespace) -> int:
    errors = verify_manifest(RUNTIME_DIR, _read_json(SOURCE_MANIFEST_PATH), _read_json(PATCH_MANIFEST_PATH))
    if errors:
        print("\n".join(errors))
        return 1
    print("provenance verification passed")
    return 0


def _command_scan_secrets(_: argparse.Namespace) -> int:
    findings = scan_secrets()
    if findings:
        print("\n".join(findings))
        return 1
    print("secret scan passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build-manifest")
    build.add_argument("--source-dir", required=True)
    build.add_argument("--imported-dir", required=True)
    build.add_argument("--metadata-file", required=True)
    build.add_argument("--upstream-file", required=True)
    build.add_argument("--source-manifest", required=True)
    build.set_defaults(handler=_command_build_manifest)
    update = commands.add_parser("update-patches")
    update.add_argument("--reason-file", required=True)
    update.set_defaults(handler=_command_update_patches)
    commands.add_parser("verify").set_defaults(handler=_command_verify)
    commands.add_parser("scan-secrets").set_defaults(handler=_command_scan_secrets)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
