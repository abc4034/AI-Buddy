from __future__ import annotations

import hashlib
import importlib.resources
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
MODEL_SIZE = 2_327_524
MODEL_SHA256 = "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"
XIAOZHI_COMMIT = "8ec585102711516bf214b262f7d87bc04f9597e2"
SILERO_COMMIT = "b163605b3f44c3aadf28f97b125a2f7c461e9a7f"
LICENSE_SHA256 = {
    "licenses/xiaozhi-esp32-server-MIT.txt": "65e7d56732b4b42f2efcd0cba4d199d153b3faa9cc6def8bfad90f0d8193d273",
    "licenses/silero-vad-MIT.txt": "2e63e9a38b6e8fc0c7bc37ce174caca1862870856c6daf5697cfb785e925520b",
}


def test_silero_vad_asset_and_provenance_are_packaged() -> None:
    notice_path = ROOT / "THIRD_PARTY_NOTICES.md"
    assert notice_path.is_file()
    notice = notice_path.read_text(encoding="utf-8")
    assert XIAOZHI_COMMIT in notice
    assert SILERO_COMMIT in notice

    licenses = {
        "licenses/xiaozhi-esp32-server-MIT.txt",
        "licenses/silero-vad-MIT.txt",
    }
    for license_path in licenses:
        path = ROOT / license_path
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert text.startswith("MIT License\n\n")
        assert "Permission is hereby granted, free of charge" in text
        assert hashlib.sha256(path.read_bytes()).hexdigest() == LICENSE_SHA256[license_path]

    resource = importlib.resources.files("buddy_gateway").joinpath("assets/silero_vad.onnx")
    assert resource.is_file()
    model = resource.read_bytes()
    assert len(model) == MODEL_SIZE
    assert hashlib.sha256(model).hexdigest() == MODEL_SHA256

    wheels = list((ROOT / "tmp" / "wheels").glob("*.whl"))
    assert len(wheels) == 1
    with ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())

    assert "buddy_gateway/assets/silero_vad.onnx" in names
    for path in licenses | {"THIRD_PARTY_NOTICES.md"}:
        assert any(name.endswith(path) for name in names)
