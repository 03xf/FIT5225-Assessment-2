"""Integrity checks for the provided assessment media and model artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_supplied_fixture_set_has_expected_coverage():
    images = sorted((ROOT / "tests" / "fixtures" / "test_images").glob("*.JPG"))
    assert len(images) == 30
    species = {"_".join(image.stem.split("_")[:2]).lower() for image in images}
    assert len(species) == 13


def test_supplied_model_files_match_versioned_manifest():
    manifest = json.loads((ROOT / "models" / "model-manifest.json").read_text(encoding="utf-8"))
    assert manifest["active_version"] == "supplied-2026-08"
    for kind in ("detector", "classifier"):
        entry = manifest[kind]
        model = ROOT / entry["uri"]
        assert model.is_file(), f"Missing supplied {kind} asset: {model}"
        assert sha256(model) == entry["sha256"]
