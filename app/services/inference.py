import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app.config import Settings


@dataclass(frozen=True)
class InferenceResult:
    tags: dict[str, dict]
    model_version: str


class InferenceService:
    """Inference boundary.

    `demo_filename` is deliberately restricted to development so the UI can be
    tested with the supplied labelled fixture photos. Deployed workloads use
    the Alibaba Function Compute worker (implemented as the same contract) and never infer
    tags from filenames.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.manifest = self._load_manifest(settings.model_manifest)
        self.species = self._load_species(settings.model_manifest.parent / "labels.txt")

    @staticmethod
    def _load_manifest(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"active_version": "unconfigured"}

    @staticmethod
    def _load_species(path: Path) -> set[str]:
        if not path.exists():
            return set()
        values: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            columns = [part.strip().lower() for part in line.split(";")]
            if len(columns) >= 6 and columns[4] and columns[5]:
                values.add(f"{columns[4]}_{columns[5]}")
        return values

    @property
    def model_version(self) -> str:
        return str(self.manifest.get("active_version", "unconfigured"))

    def infer_image(self, image_path: Path, original_name: str) -> InferenceResult:
        if self.settings.environment != "development" and self.settings.inference_mode == "demo_filename":
            raise RuntimeError("demo filename inference is disabled outside development")
        if self.settings.inference_mode != "demo_filename":
            raise RuntimeError("Local runtime is configured for remote Alibaba Function Compute inference")
        # Fixture naming convention: Genus_species_1.JPG. This supports local
        # workflow testing only and leaves an explicit provenance in the DB.
        stem = Path(original_name).stem.lower()
        match = re.match(r"^([a-z]+_[a-z]+)_\d+$", stem)
        label = match.group(1) if match and (not self.species or match.group(1) in self.species) else "unclassified"
        confidence = 0.99 if label != "unclassified" else 0.0
        return InferenceResult({label: {"count": 1, "source": "demo", "confidence": confidence}}, self.model_version)

    def infer_video_frames(self, video_path: Path, frames_directory: Path) -> InferenceResult:
        frames_directory.mkdir(parents=True, exist_ok=True)
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video_path), "-vf", "fps=1", str(frames_directory / "frame-%05d.jpg")]
        try:
            subprocess.run(command, check=True, timeout=300)
        except FileNotFoundError as exc:
            raise RuntimeError("ffmpeg is required for one-frame-per-second video processing") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("Unable to decode video into one frame per second") from exc
        counts: dict[str, dict] = {}
        for frame in sorted(frames_directory.glob("frame-*.jpg")):
            result = self.infer_image(frame, video_path.name)
            for tag, detail in result.tags.items():
                current = counts.setdefault(tag, {**detail, "count": 0})
                current["count"] += detail["count"]
                current["confidence"] = max(current["confidence"], detail["confidence"])
        return InferenceResult(counts or {"unclassified": {"count": 1, "source": "demo", "confidence": 0.0}}, self.model_version)


def create_thumbnail(source: Path, destination: Path, max_side: int = 480) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image = image.convert("RGB")
        image.thumbnail((max_side, max_side))
        image.save(destination, format="JPEG", quality=82, optimize=True)
