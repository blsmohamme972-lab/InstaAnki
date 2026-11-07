#!/usr/bin/env python3
"""Build and verify a data-only InstaAnki content ZIP from assembled lessons.

Usage:
    python tools/build_pack.py
    python tools/build_pack.py --pack-id batch-002 --output dist/batch-002.zip
    python tools/build_pack.py --verify dist/batch-002.zip

Only referenced local media under web/media/ are included. Source PDFs, raw
book extraction, HTML, JavaScript, SVG and native code never enter the pack.
The manifest hashes every payload file; the companion checksum covers the
complete ZIP, including its manifest. Checksums detect changes, not authorship.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import tempfile
import zipfile
from source_policy import SourcePolicy, SourcePolicyError, validate_pack, validate_publications, canonical_hash


PROJECT = Path(__file__).resolve().parents[1]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav"}
VIDEO_EXTENSIONS = {".mp4", ".webm"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | AUDIO_EXTENSIONS | VIDEO_EXTENSIONS | {".json", ".vtt", ".txt"}
MAX_ENTRIES = 3000
MAX_FILE_BYTES = 192 * 1024 * 1024
MAX_JSON_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
PACK_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
PATH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_path(value: str) -> str:
    if not isinstance(value, str) or not PATH_RE.fullmatch(value):
        raise ValueError(f"Unsafe or unsupported relative pack path: {value!r}")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"Unsafe path segment: {value!r}")
    if PurePosixPath(value).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported pack file type: {value!r}")
    return value


def checked_size(name: str, size: int) -> None:
    if size < 0 or size > MAX_FILE_BYTES:
        raise ValueError(f"File exceeds the Android import limit: {name}")
    if name.lower().endswith(".json") and size > MAX_JSON_BYTES:
        raise ValueError(f"JSON exceeds the Android import limit: {name}")


def finite_number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite numeric data")
    return float(value)


def collect_media(lessons: list, web_root: Path) -> dict[str, Path]:
    """Validate lesson essentials and make all playback media paths relative."""
    media: dict[str, Path] = {}
    seen_ids = set()
    path_case = {}

    def add(owner: dict, key: str, allowed: set[str]) -> None:
        value = owner.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Missing media reference: {key}")
        # The leading-slash form is a web-root path, not an archive path.
        if value.startswith("/media/"):
            value = value[1:]
        name = checked_path(value)
        if not name.startswith("media/") or PurePosixPath(name).suffix.lower() not in allowed:
            raise ValueError(f"Media must use a supported local web/media path: {name}")
        existing = path_case.setdefault(name.casefold(), name)
        if existing != name:
            raise ValueError(f"Case-insensitive media path collision: {existing} / {name}")
        source = (web_root / name).resolve()
        if not source.is_relative_to(web_root) or not source.is_file():
            raise ValueError(f"Media is missing or escapes the web root: {name}")
        checked_size(name, source.stat().st_size)
        owner[key] = name
        media[name] = source

    for lesson in lessons:
        if not isinstance(lesson, dict):
            raise ValueError("Each lesson must be an object")
        lesson_id = lesson.get("id")
        if not isinstance(lesson_id, str) or not lesson_id.strip() or lesson_id.casefold() in seen_ids:
            raise ValueError(f"Missing or duplicate lesson ID: {lesson_id!r}")
        seen_ids.add(lesson_id.casefold())
        duration = finite_number(lesson.get("durationSeconds"), f"{lesson_id}.durationSeconds")
        if duration <= 0:
            raise ValueError(f"Lesson has no positive duration: {lesson_id}")
        add(lesson, "audioUrl", AUDIO_EXTENSIONS)
        add(lesson, "poster", IMAGE_EXTENSIONS)
        if lesson.get("videoUrl"):
            add(lesson, "videoUrl", VIDEO_EXTENSIONS)
        scenes = lesson.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            raise ValueError(f"Lesson has no scenes: {lesson_id}")
        previous_end = 0.0
        for scene in scenes:
            if not isinstance(scene, dict):
                raise ValueError(f"Malformed scene in {lesson_id}")
            start = finite_number(scene.get("start"), "scene.start")
            end = finite_number(scene.get("end"), "scene.end")
            if start < 0 or end <= start or end > duration + 0.001 or start < previous_end - 0.001:
                raise ValueError(f"Invalid or overlapping scene timing in {lesson_id}")
            previous_end = end
            add(scene, "image", IMAGE_EXTENSIONS)
        images = lesson.get("realImages")
        if not isinstance(images, list) or not images:
            raise ValueError(f"Lesson has no final real image: {lesson_id}")
        for real_image in images:
            if not isinstance(real_image, dict):
                raise ValueError(f"Malformed real image in {lesson_id}")
            add(real_image, "url", IMAGE_EXTENSIONS)
        outro = lesson.get("realImageOutro", {})
        start = finite_number(outro.get("start"), "realImageOutro.start")
        end = finite_number(outro.get("end"), "realImageOutro.end")
        if start < previous_end - 0.001 or end <= start or abs(end - duration) > 0.001:
            raise ValueError(f"Invalid final real-image timing in {lesson_id}")
        quiz = lesson.get("quiz", {})
        choices = quiz.get("options")
        correct = quiz.get("correctIndex")
        if (not isinstance(choices, list) or len(choices) < 2
                or not all(isinstance(choice, str) and choice for choice in choices)
                or isinstance(correct, bool) or not isinstance(correct, int)
                or not 0 <= correct < len(choices)):
            raise ValueError(f"Invalid quiz in {lesson_id}")
    return media


def verify_archive(path: Path) -> dict:
    """Reopen the artifact and check the same structural limits as Android."""
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if not 1 <= len(entries) <= MAX_ENTRIES:
            raise ValueError("Archive has an invalid number of entries")
        names = set()
        by_name = {}
        total = 0
        for entry in entries:
            name = checked_path(entry.filename)
            if entry.is_dir() or name.casefold() in names:
                raise ValueError(f"Duplicate or unexpected directory entry: {name}")
            names.add(name.casefold())
            checked_size(name, entry.file_size)
            total += entry.file_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("Archive exceeds Android's expanded-size limit")
            by_name[name] = entry
        manifest = json.loads(archive.read("manifest.json"))
        pack_id = manifest.get("id", manifest.get("packId", ""))
        if manifest.get("schemaVersion") != 1 or not PACK_ID_RE.fullmatch(pack_id):
            raise ValueError("Manifest has unsupported schema or invalid ID")
        lessons_file = checked_path(manifest.get("lessonsFile", "lessons.json"))
        payload = set(by_name) - {"manifest.json"}
        hashes = manifest.get("sha256")
        if not isinstance(hashes, dict) or set(hashes) != payload:
            raise ValueError("Manifest must hash every payload file exactly once")
        files = []
        for name in sorted(payload):
            data = archive.read(name)
            actual_hash = digest(data)
            if not isinstance(hashes[name], str) or actual_hash != hashes[name]:
                raise ValueError(f"Payload checksum mismatch: {name}")
            if name.endswith(".json"):
                json.loads(data)
            files.append({"path": name, "bytes": len(data), "sha256": actual_hash})
        lessons_data = json.loads(archive.read(lessons_file))
        lessons = lessons_data.get("lessons") if isinstance(lessons_data, dict) else lessons_data
        if not isinstance(lessons, list) or not lessons:
            raise ValueError("Pack has no lessons")
        references = set()
        for lesson in lessons:
            references.update([lesson["audioUrl"], lesson["poster"]])
            references.update(scene["image"] for scene in lesson["scenes"])
            references.update(item["url"] for item in lesson["realImages"])
            if lesson.get("videoUrl"):
                references.add(lesson["videoUrl"])
        if not references <= payload:
            raise ValueError(f"Missing packaged media: {sorted(references - payload)}")
        return {"schemaVersion": 1, "packId": pack_id,
                "lessonCount": len(lessons), "lessonIds": [lesson["id"] for lesson in lessons],
                "entryCount": len(entries), "expandedBytes": total,
                "zipBytes": path.stat().st_size, "zipSha256": digest(path.read_bytes()),
                "allPayloadHashesVerified": True, "allMediaReferencesResolved": True,
                "dataOnly": True, "rawBookIncluded": False,
                "androidDeviceImportTested": False, "files": files}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=PROJECT / "web/data/lessons.json")
    parser.add_argument("--web-root", type=Path, default=PROJECT / "web")
    parser.add_argument("--output", type=Path, default=PROJECT / "dist/InstaAnki-Starter-Pack-v1.zip")
    parser.add_argument("--pack-id", default="instaanki-starter-shahzad2015-v1")
    parser.add_argument("--title", default="InstaAnki Starter Lessons")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--books", type=Path, default=PROJECT / "web/data/books.json", help="Public production metadata; source covers and raw book text are excluded")
    parser.add_argument("--lesson", action="append", help="Include this lesson ID only; repeatable")
    parser.add_argument("--verify", type=Path, help="Verify an existing ZIP without rebuilding")
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_archive(args.verify), indent=2))
        return
    if not PACK_ID_RE.fullmatch(args.pack_id):
        parser.error("Pack ID must match [A-Za-z0-9][A-Za-z0-9._-]{0,79}")
    source_data = json.loads(args.input.read_text())
    lessons = source_data.get("lessons") if isinstance(source_data, dict) else source_data
    if not isinstance(lessons, list) or not lessons:
        parser.error("Input must be a nonempty lesson array or an object containing lessons")
    lessons = copy.deepcopy([lesson for lesson in lessons
                             if not args.lesson or lesson.get("id") in args.lesson])
    if not lessons:
        parser.error("No matching lessons")
    validate_pack(lessons, args.web_root.resolve())
    checked_lesson_hashes = [canonical_hash(lesson) for lesson in lessons]
    media = collect_media(lessons, args.web_root.resolve())
    if checked_lesson_hashes != [canonical_hash(lesson) for lesson in lessons]:
        raise ValueError("Pack path normalization changed reviewed lesson content; review the assembled paths first")
    payload = {"lessons.json": json_bytes(lessons)}
    payload.update({name: source.read_bytes() for name, source in sorted(media.items())})
    for name, data in payload.items():
        checked_path(name)
        checked_size(name, len(data))
    manifest = {"schemaVersion": 1, "id": args.pack_id,
                "title": args.title, "version": args.version,
                "lessonsFile": "lessons.json", "lessonCount": len(lessons),
                "sha256": {name: digest(data) for name, data in sorted(payload.items())}}
    if args.books.is_file():
        # Preserve source-linked production counts without publishing source scans.
        books = json.loads(args.books.read_text())
        validate_publications(books, SourcePolicy(PROJECT).ledger())
        related = {lesson.get("source", {}).get("bookId") for lesson in lessons}
        manifest["books"] = [{key: value for key, value in book.items() if key != "coverUrl"}
                             for book in books if book.get("id") in related]
    entries = {"manifest.json": json_bytes(manifest), **payload}
    if len(entries) > MAX_ENTRIES or sum(map(len, entries.values())) > MAX_TOTAL_BYTES:
        raise ValueError("Pack exceeds Android import limits")
    checked_size("manifest.json", len(entries["manifest.json"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pack-build-", dir=args.output.parent) as temporary:
        temporary_zip = Path(temporary) / "content.zip"
        with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as archive:
            for name, data in sorted(entries.items()):
                # Fixed timestamps/order make unchanged inputs byte-reproducible.
                entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, data)
        report = verify_archive(temporary_zip)
        temporary_zip.replace(args.output)
    report["sourceLessonsSha256"] = digest(args.input.read_bytes())
    report["output"] = str(args.output.resolve())
    args.output.with_suffix(".report.json").write_bytes(json_bytes(report))
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(
        f"{report['zipSha256']}  {args.output.name}\n")
    print(json.dumps({key: value for key, value in report.items() if key != "files"}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except SourcePolicyError as exc:
        raise SystemExit(f"Source policy: {exc}")
