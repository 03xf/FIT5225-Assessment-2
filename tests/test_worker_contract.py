"""Source-level release guards for worker requirements that need Docker/Function Compute."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_worker_extracts_exactly_one_video_frame_per_second():
    source = (ROOT / "worker" / "main.py").read_text(encoding="utf-8")
    assert '"-vf", "fps=1"' in source
    assert "for frame in frames:" in source


def test_worker_image_excludes_model_weights_and_keeps_manifest():
    dockerfile = (ROOT / "Dockerfile.worker").read_text(encoding="utf-8")
    assert "COPY models/model-manifest.json models/labels.txt /models/" in dockerfile
    assert "COPY models /models" not in dockerfile
