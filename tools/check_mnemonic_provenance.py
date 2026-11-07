#!/usr/bin/env python3
"""Fail-closed checks for new or replaced mnemonic image outputs.

GitHub cannot observe a private image-tool call. This guard therefore checks
the part that belongs in the repository: when a mnemonic raster changes, the
changed file must have a separate, hash-bound receipt for the built-in image
generator and a post-generation visual inspection. Existing unchanged media
does not need a retrospective receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

try:
    from PIL import Image
except ImportError:  # pragma: no cover - CI installs Pillow
    Image = None


ROOT = Path(__file__).resolve().parents[1]
RECEIPT_DIR = Path("production/qa/mnemonic-generation")
SHA256 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
FITS = {"contain", "cover", "fill"}
FRAMING = {"edge-to-edge", "intentional-frame", "reviewed-crop"}
REQUIRED_VISUAL_CHECKS = {"sourceAlignment", "symbolMeaning", "phoneCrop", "noBakedText"}


class ProvenanceError(ValueError):
    pass


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProvenanceError(f"Cannot read {path}: {exc}") from exc


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def timestamp(value, label: str) -> None:
    if not isinstance(value, str):
        raise ProvenanceError(f"{label} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ProvenanceError(f"{label} must be a timezone-aware ISO timestamp") from None
    if parsed.utcoffset() is None:
        raise ProvenanceError(f"{label} must include a timezone")


def text(value, label: str, minimum_words: int = 1) -> None:
    if not isinstance(value, str) or len(value.strip().split()) < minimum_words:
        raise ProvenanceError(f"{label} needs meaningful completed text")
    if re.search(r"\b(?:TODO|TBD|CHANGEME)\b|\{\{[^}]*\}\}", value, re.IGNORECASE):
        raise ProvenanceError(f"{label} still contains a placeholder")


def image_dimensions(path: Path) -> tuple[int, int]:
    if Image is None:
        raise ProvenanceError("Pillow is required to verify generated image dimensions")
    try:
        with Image.open(path) as image:
            image.load()
            width, height = image.size
    except Exception as exc:
        raise ProvenanceError(f"Cannot decode image {path}: {exc}") from exc
    if min(width, height) < 512:
        raise ProvenanceError(f"{path} is too small for a mnemonic poster ({width}x{height})")
    return width, height


def changed_paths(repo: Path, base_ref: str | None) -> list[str]:
    if not base_ref:
        return []
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=repo, check=True, capture_output=True, text=True,
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def validate_focus_region(item: dict, label: str) -> None:
    focus = item.get("focusRegion")
    if not isinstance(focus, dict) or not isinstance(focus.get("coordinates"), str):
        raise ProvenanceError(f"{label} needs a normalized focusRegion record")
    values = [focus.get(key) for key in ("x", "y", "width", "height")]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise ProvenanceError(f"{label}.focusRegion coordinates must be numeric")
    if any(value < 0 or value > 1 for value in values) or focus["width"] <= 0 or focus["height"] <= 0:
        raise ProvenanceError(f"{label}.focusRegion must stay within normalized image bounds")


def validate_gallery_layout(lesson: dict) -> None:
    gallery = (lesson.get("presentation") or {}).get("clinicalGallery")
    if not isinstance(gallery, dict):
        return
    fit = gallery.get("displayMode")
    review = gallery.get("layoutReview")
    if fit not in FITS or not isinstance(review, dict) or review.get("reviewed") is not True:
        raise ProvenanceError(f"{lesson['id']} clinicalGallery needs an explicit fit and completed layoutReview")
    if review.get("fit") != fit or review.get("framing") not in FRAMING:
        raise ProvenanceError(f"{lesson['id']} clinicalGallery layoutReview does not match its display mode")
    timestamp(review.get("reviewedAt"), f"{lesson['id']} clinicalGallery.layoutReview.reviewedAt")
    text(review.get("notes"), f"{lesson['id']} clinicalGallery.layoutReview.notes", minimum_words=8)
    images = gallery.get("images")
    if not isinstance(images, list) or not images:
        raise ProvenanceError(f"{lesson['id']} clinicalGallery must contain images")
    for index, item in enumerate(images, 1):
        if not isinstance(item, dict):
            raise ProvenanceError(f"{lesson['id']} clinicalGallery image {index} is not an object")
        validate_focus_region(item, f"{lesson['id']} clinicalGallery image {index}")


def validate_receipt(repo: Path, lesson: dict, poster: str, asset: Path, digest: str) -> None:
    receipt_path = repo / RECEIPT_DIR / f"{lesson['id']}.json"
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ProvenanceError(f"{lesson['id']} changed poster has no image-generation receipt: {receipt_path}")
    receipt = read_json(receipt_path)
    if receipt.get("schemaVersion") != 1 or receipt.get("artifactKind") != "image-generation":
        raise ProvenanceError(f"{receipt_path} must be a schema-1 image-generation receipt")
    if receipt.get("lessonId") != lesson["id"] or receipt.get("poster") != poster:
        raise ProvenanceError(f"{receipt_path} is bound to a different lesson or poster")
    if receipt.get("generator") != "openai-imagegen" or receipt.get("actualCall") is not True:
        raise ProvenanceError(f"{receipt_path} must record the built-in image generator and actualCall=true")
    if receipt.get("imageGenerated") is not True:
        raise ProvenanceError(f"{receipt_path} cannot use a prompt-gate receipt as proof of generation")
    prompt_gate = receipt.get("promptGate")
    if not isinstance(prompt_gate, dict) or not SHA256.fullmatch(str(prompt_gate.get("requestSha256", ""))):
        raise ProvenanceError(f"{receipt_path} needs the requestSha256 from the validated prompt gate")
    if receipt.get("outputPath") != poster or receipt.get("outputSha256", "").lower() != digest.lower():
        raise ProvenanceError(f"{receipt_path} output path/hash does not match the checked poster bytes")
    width, height = image_dimensions(asset)
    if receipt.get("outputWidth") != width or receipt.get("outputHeight") != height:
        raise ProvenanceError(f"{receipt_path} output dimensions do not match the checked poster")
    timestamp(receipt.get("recordedAt"), f"{receipt_path}.recordedAt")
    inspection = receipt.get("visualInspection")
    if not isinstance(inspection, dict) or inspection.get("reviewed") is not True:
        raise ProvenanceError(f"{receipt_path} needs an honest post-generation visual inspection")
    timestamp(inspection.get("reviewedAt"), f"{receipt_path}.visualInspection.reviewedAt")
    checks = inspection.get("checks")
    if not isinstance(checks, dict) or any(checks.get(name) is not True for name in REQUIRED_VISUAL_CHECKS):
        raise ProvenanceError(f"{receipt_path} must pass source, symbol, phone-crop and no-baked-text checks")
    if receipt.get("embeddedTextDetected") is not False:
        raise ProvenanceError(f"{receipt_path} must confirm that factual labels remain controlled overlays")
    text(inspection.get("notes"), f"{receipt_path}.visualInspection.notes", minimum_words=8)
    validate_gallery_layout(lesson)


def validate(repo: Path = ROOT, *, changed: list[str] | None = None) -> dict:
    repo = Path(repo).resolve()
    lessons = read_json(repo / "web/data/lessons.json")
    if not isinstance(lessons, list):
        raise ProvenanceError("web/data/lessons.json must contain a lesson list")
    changed = changed or []
    changed_posters = {path.removeprefix("web/") for path in changed if path.startswith("web/media/mnemonic/")}
    changed_posters |= {path for path in changed if path.startswith("media/mnemonic/")}
    if not changed_posters:
        return {"lessons": len(lessons), "changedPosters": 0, "verifiedGenerated": 0}
    by_poster = {}
    for lesson in lessons:
        if not isinstance(lesson, dict) or not isinstance(lesson.get("id"), str):
            raise ProvenanceError("Every lesson needs a string id")
        poster = lesson.get("poster")
        if not isinstance(poster, str) or poster.startswith("/") or ".." in Path(poster).parts:
            raise ProvenanceError(f"{lesson['id']} has an unsafe poster path")
        by_poster.setdefault(poster, []).append(lesson)
    checked = 0
    for poster in sorted(changed_posters):
        lessons_for_poster = by_poster.get(poster, [])
        if not lessons_for_poster:
            raise ProvenanceError(f"Changed mnemonic asset is not referenced by a lesson: {poster}")
        asset = repo / "web" / poster
        if not asset.is_file() or asset.is_symlink():
            raise ProvenanceError(f"Changed mnemonic asset is missing or indirect: {poster}")
        digest = file_sha256(asset)
        for lesson in lessons_for_poster:
            validate_receipt(repo, lesson, poster, asset, digest)
            checked += 1
    return {"lessons": len(lessons), "changedPosters": len(changed_posters), "verifiedGenerated": checked}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--base-ref", help="Git ref/SHA to compare with HEAD; unchanged legacy assets are skipped")
    parser.add_argument("--changed-poster", action="append", default=[], help="Direct poster path for local checks")
    args = parser.parse_args()
    try:
        paths = args.changed_poster + changed_paths(args.repo.resolve(), args.base_ref)
        result = validate(args.repo, changed=paths)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Mnemonic provenance check failed: {exc}") from exc
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
