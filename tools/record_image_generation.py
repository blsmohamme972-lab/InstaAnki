#!/usr/bin/env python3
"""Record a real built-in image-generation result after human inspection.

This command does not generate an image.  The authoring agent must first call
the built-in image generator, save its returned raster at the lesson poster
path, inspect that exact file, and then run this command.  The resulting public
receipt contains no prompt or source-derived content; it binds the private
prompt-gate request fingerprint to the final output bytes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - CI installs Pillow
    raise SystemExit("record_image_generation.py requires Pillow") from exc


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CHECKS = {"sourceAlignment", "symbolMeaning", "phoneCrop", "noBakedText"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_gate(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    receipt = data.get("receipt", data)
    if not isinstance(receipt, dict):
        raise ValueError("prompt-gate JSON must be an explicit pre-generation checkpoint")
    is_prompt_gate = (
        receipt.get("artifactKind") == "prompt-gate"
        or receipt.get("kind") == "reviewed-image-prompt"
    )
    if not is_prompt_gate or receipt.get("imageGenerated") is not False:
        raise ValueError("prompt-gate JSON must be an explicit pre-generation checkpoint")
    request_hash = receipt.get("requestSha256")
    if not isinstance(request_hash, str) or len(request_hash) != 64:
        raise ValueError("prompt-gate JSON does not contain a requestSha256")
    int(request_hash, 16)
    return {"requestSha256": request_hash.lower(), "artifactPath": str(path)}


def atomic_write(path: Path, value: dict) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"Refusing to overwrite an existing receipt: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".image-generation-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lesson", required=True)
    parser.add_argument("--poster", required=True, help="Path relative to web/, for example media/mnemonic/q014.png")
    parser.add_argument("--prompt-gate", type=Path, required=True, help="Private ready-image-request JSON")
    parser.add_argument("--output", type=Path, required=True, help="Generated raster path relative to web/")
    parser.add_argument("--receipt", type=Path, help="Public receipt path; defaults to the checked-in QA directory")
    parser.add_argument("--actual-call-confirmed", action="store_true",
                        help="Confirm that the built-in OpenAI image generator returned this output")
    parser.add_argument("--check", action="append", default=[], choices=sorted(REQUIRED_CHECKS),
                        help="One completed post-generation visual check; repeat four times")
    parser.add_argument("--notes", required=True, help="At least eight words describing inspection of the exact output")
    args = parser.parse_args()
    if not args.actual_call_confirmed:
        raise SystemExit("Refusing to write a receipt without --actual-call-confirmed")
    if set(args.check) != REQUIRED_CHECKS:
        raise SystemExit("Repeat --check for sourceAlignment, symbolMeaning, phoneCrop and noBakedText")
    if len(args.notes.split()) < 8 or any(token in args.notes.upper().split() for token in ("TODO", "TBD", "CHANGEME")):
        raise SystemExit("--notes needs at least eight completed words and no placeholder")
    repo = ROOT.resolve()
    poster = args.poster.replace("\\", "/")
    output_rel = args.output.as_posix()
    if poster != output_rel or poster.startswith("/") or ".." in Path(poster).parts:
        raise SystemExit("--poster and --output must be the same safe path relative to web/")
    asset = repo / "web" / poster
    if not asset.is_file() or asset.is_symlink():
        raise SystemExit(f"Generated poster is missing or indirect: {poster}")
    gate = read_gate(args.prompt_gate)
    with Image.open(asset) as image:
        image.load()
        width, height = image.size
    if min(width, height) < 512:
        raise SystemExit(f"Generated poster is too small: {width}x{height}")
    digest = sha256(asset)
    now = datetime.now(timezone.utc).isoformat()
    receipt = {
        "schemaVersion": 1,
        "artifactKind": "image-generation",
        "lessonId": args.lesson,
        "poster": poster,
        "generator": "openai-imagegen",
        "actualCall": True,
        "imageGenerated": True,
        "promptGate": gate,
        "outputPath": poster,
        "outputSha256": digest,
        "outputWidth": width,
        "outputHeight": height,
        "embeddedTextDetected": False,
        "visualInspection": {
            "reviewed": True,
            "reviewedAt": now,
            "checks": {name: True for name in sorted(REQUIRED_CHECKS)},
            "notes": args.notes.strip(),
        },
        "recordedAt": now,
    }
    destination = args.receipt or (repo / "production/qa/mnemonic-generation" / f"{args.lesson}.json")
    atomic_write(destination.resolve(), receipt)
    print(json.dumps({"receipt": str(destination), "lessonId": args.lesson, "outputSha256": digest}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Image-generation receipt failed: {exc}") from exc
