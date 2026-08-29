"""Run one supplied camera-trap image through the real supplied model assets.

Usage (after installing worker dependencies):
    .\.venv\Scripts\python.exe scripts\run_model_smoke.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MODEL_ROOT", str(ROOT / "models"))
os.environ.setdefault("MODEL_MANIFEST", str(ROOT / "models" / "model-manifest.json"))
sys.path.insert(0, str(ROOT))

from worker.main import load_manifest, process_image  # noqa: E402


def main() -> int:
    image = ROOT / "tests" / "fixtures" / "test_images" / "Bos_taurus_1.JPG"
    manifest = load_manifest()
    tags: Counter[str] = process_image(image, manifest)
    print(json.dumps({"image": image.name, "model_version": manifest["active_version"], "tags": dict(tags)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
