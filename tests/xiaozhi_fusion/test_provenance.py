import hashlib
import json
import shutil
from pathlib import Path

import pytest

from integrations.xiaozhi_server.provenance import (
    build_manifest,
    scan_secrets,
    sha256_file,
    update_patch_manifest,
    verify_manifest,
)


EXPECTED = {
    "origin": "https://github.com/xinnan-tech/xiaozhi-esp32-server.git",
    "commit": "8ec585102711516bf214b262f7d87bc04f9597e2",
    "tree": "7b96e40bf6541e9b94bdf7c53de9266e3590464d",
}


def write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


@pytest.fixture
def source_and_imported(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    source = tmp_path / "source"
    imported = tmp_path / "imported"
    write(source / "LICENSE", b"MIT License\n")
    write(source / "config.yaml", b"api_key: upstream-public-value\n")
    write(source / "core" / "service.py", b"print('upstream')\n")
    write(source / "music" / "one.mp3", b"first music asset")
    write(source / "music" / "two.mp3", b"second music asset")
    write(source / "music" / "three.mp3", b"third music asset")
    write(source / "data" / "runtime.db", b"generated state")
    shutil.copytree(source, imported)
    metadata = {
        **EXPECTED,
        "archive_sha256": hashlib.sha256(b"fixture archive").hexdigest(),
        "source_subtree": "main/xiaozhi-server",
    }
    return source, imported, metadata


def test_build_manifest_records_pinned_origin_and_sorted_per_file_hashes(source_and_imported):
    source, imported, metadata = source_and_imported

    manifest = build_manifest(source, imported, metadata)

    assert manifest["upstream"] == metadata
    assert manifest["upstream"]["origin"] == EXPECTED["origin"]
    assert manifest["upstream"]["commit"] == EXPECTED["commit"]
    assert manifest["upstream"]["tree"] == EXPECTED["tree"]
    assert len(manifest["upstream"]["archive_sha256"]) == 64
    assert manifest["upstream"]["archive_sha256"].isalnum()
    assert [entry["path"] for entry in manifest["files"]] == [
        "LICENSE",
        "config.yaml",
        "core/service.py",
        "music/one.mp3",
        "music/three.mp3",
        "music/two.mp3",
    ]
    assert manifest["files"][2]["sha256"] == sha256_file(source / "core" / "service.py")
    assert all(len(entry["sha256"]) == 64 for entry in manifest["files"])


def test_nested_model_data_assets_remain_under_provenance(source_and_imported):
    source, imported, metadata = source_and_imported
    relative = Path("models") / "silero" / "data" / "model.onnx"
    write(source / relative, b"upstream model")
    write(imported / relative, b"upstream model")

    manifest = build_manifest(source, imported, metadata)

    assert relative.as_posix() in {entry["path"] for entry in manifest["files"]}
    write(imported / relative, b"changed model")
    assert verify_manifest(imported, manifest, {"patches": []}) == [
        "unrecorded-modification:" + relative.as_posix()
    ]
    with pytest.raises(ValueError, match="model.onnx"):
        update_patch_manifest(imported, manifest, {})


def test_verify_manifest_reports_missing_modified_and_unexpected_paths_deterministically(source_and_imported):
    source, imported, metadata = source_and_imported
    manifest = build_manifest(source, imported, metadata)
    (imported / "LICENSE").unlink()
    write(imported / "core" / "service.py", b"changed\n")
    write(imported / "new.py", b"added\n")

    errors = verify_manifest(imported, manifest, {"patches": []})

    assert errors == [
        "missing:LICENSE",
        "unrecorded-modification:core/service.py",
        "unexpected:new.py",
    ]


def test_verify_manifest_accepts_reviewed_added_modified_and_deleted_hashes(source_and_imported):
    source, imported, metadata = source_and_imported
    manifest = build_manifest(source, imported, metadata)
    (imported / "LICENSE").unlink()
    write(imported / "core" / "service.py", b"changed\n")
    write(imported / "new.py", b"added\n")
    patches = update_patch_manifest(
        imported,
        manifest,
        {
            "LICENSE": "fixture delete",
            "core/service.py": "fixture modification",
            "new.py": "fixture addition",
        },
    )

    assert verify_manifest(imported, manifest, patches) == []
    assert patches["patches"] == [
        {
            "path": "LICENSE",
            "status": "deleted",
            "reason": "fixture delete",
            "original_sha256": sha256_file(source / "LICENSE"),
            "current_sha256": None,
        },
        {
            "path": "core/service.py",
            "status": "modified",
            "reason": "fixture modification",
            "original_sha256": sha256_file(source / "core" / "service.py"),
            "current_sha256": sha256_file(imported / "core" / "service.py"),
        },
        {
            "path": "new.py",
            "status": "added",
            "reason": "fixture addition",
            "original_sha256": None,
            "current_sha256": sha256_file(imported / "new.py"),
        },
    ]


def test_verify_manifest_detects_reviewed_patch_hash_drift(source_and_imported):
    source, imported, metadata = source_and_imported
    manifest = build_manifest(source, imported, metadata)
    write(imported / "config.yaml", b"api_key: blank\n")
    patches = update_patch_manifest(imported, manifest, {"config.yaml": "blank unsafe default"})
    write(imported / "config.yaml", b"api_key: changed again\n")

    assert verify_manifest(imported, manifest, patches) == ["patch-hash-mismatch:config.yaml"]


def test_update_patch_manifest_is_deterministic_and_refuses_unreviewed_changes(source_and_imported):
    source, imported, metadata = source_and_imported
    manifest = build_manifest(source, imported, metadata)
    write(imported / "config.yaml", b"api_key: blank\n")

    with pytest.raises(ValueError, match="config.yaml"):
        update_patch_manifest(imported, manifest, {})

    first = update_patch_manifest(imported, manifest, {"config.yaml": "blank unsafe default"})
    second = update_patch_manifest(imported, manifest, {"config.yaml": "blank unsafe default"})
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )


def test_secret_scan_allows_documented_bearer_placeholder(source_and_imported):
    _, imported, _ = source_and_imported
    write(imported / "config.yaml", b"api_key: \"\"\n")
    write(imported / "example.py", b"headers = {'Authorization': 'Bearer API_ACCESS_TOKEN'}\n")

    assert scan_secrets(imported) == []


def test_import_preserves_upstream_root_mit_license():
    repo_root = Path(__file__).resolve().parents[2]
    source_license = repo_root / "tmp" / "xiaozhi-reference" / "LICENSE"
    copied_license = repo_root / "third_party" / "xiaozhi-esp32-server" / "LICENSE"

    assert source_license.read_bytes().startswith(b"MIT License")
    assert copied_license.read_bytes() == source_license.read_bytes()


def test_imported_config_has_only_the_reviewed_weather_key_redaction():
    repo_root = Path(__file__).resolve().parents[2]
    source_lines = (repo_root / "tmp" / "xiaozhi-reference" / "main" / "xiaozhi-server" / "config.yaml").read_text(
        encoding="utf-8"
    ).splitlines()
    imported_lines = (repo_root / "xiaozhi_server" / "config.yaml").read_text(encoding="utf-8").splitlines()
    differences = [
        index for index, (source, imported) in enumerate(zip(source_lines, imported_lines), start=1) if source != imported
    ]

    assert len(source_lines) == len(imported_lines)
    assert differences == [140]
    assert imported_lines[139] == '    api_key: ""'


def test_import_preserves_every_pinned_relative_path():
    repo_root = Path(__file__).resolve().parents[2]
    source_root = repo_root / "tmp" / "xiaozhi-reference" / "main" / "xiaozhi-server"
    imported_root = repo_root / "xiaozhi_server"

    source_paths = sorted(
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*")
        if path.is_file() and not {"data", "tmp", "__pycache__"}.intersection(path.relative_to(source_root).parts)
    )
    imported_paths = sorted(
        path.relative_to(imported_root).as_posix()
        for path in imported_root.rglob("*")
        if path.is_file() and not {"data", "tmp", "__pycache__"}.intersection(path.relative_to(imported_root).parts)
    )
    patch_manifest = json.loads((repo_root / "third_party" / "xiaozhi-esp32-server" / "PATCH_MANIFEST.json").read_text())
    added_paths = sorted(patch["path"] for patch in patch_manifest["patches"] if patch["status"] == "added")

    assert imported_paths == sorted([*source_paths, *added_paths])


def test_upstream_record_keeps_the_literal_source_subtree():
    repo_root = Path(__file__).resolve().parents[2]
    upstream = json.loads(
        (repo_root / "third_party" / "xiaozhi-esp32-server" / "UPSTREAM.json").read_text(encoding="utf-8")
    )

    assert upstream["origin"] == EXPECTED["origin"]
    assert upstream["commit"] == EXPECTED["commit"]
    assert upstream["tree"] == EXPECTED["tree"]
    assert upstream["source_subtree"] == "main/xiaozhi-server"
    assert len(upstream["archive_sha256"]) == 64
    assert upstream["archive_sha256"].isalnum()
    assert upstream["imported_at"].endswith("Z")
