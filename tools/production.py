#!/usr/bin/env python3
"""Checkpoint lesson production without reading or changing learner progress."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit
from guidance import verify_guidance
from presentation import validate_presentation
from source_policy import SourcePolicy, validate_content_review


REPO = Path(__file__).resolve().parents[1]
STATUSES = {"ready", "needs_review", "claimed", "produced"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".avif"}
AUDIO_SUFFIXES = {".m4a", ".aac", ".mp3", ".ogg", ".opus", ".wav", ".flac"}
TIMELINE_TOLERANCE = 0.02
AUDIO_TOLERANCE = 0.25


class ProductionError(Exception):
    pass


def fail(message):
    raise ProductionError(message)


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"Cannot read JSON {path}: {exc}")


def canonical_hash(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        fail(f"{label} must be a finite number")
    return float(value)


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        fail(f"{label} must be a nonempty string")
    return value.strip()


def require_close(left, right, label, tolerance=TIMELINE_TOLERANCE):
    if abs(left - right) > tolerance:
        fail(f"{label}: {left:.6f} does not match {right:.6f}")


def public_url(value, label):
    parsed = urlsplit(nonempty(value, label))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        fail(f"{label} must be an HTTP(S) attribution URL")


def media_file(web_root, value, suffixes, label):
    raw = nonempty(value, label)
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        fail(f"{label} must reference a local file without a query or fragment")
    decoded = unquote(parsed.path)
    if "\\" in decoded or "\x00" in decoded:
        fail(f"Unsafe media path in {label}")
    relative = PurePosixPath(decoded.lstrip("/"))
    if not relative.parts or ".." in relative.parts:
        fail(f"Unsafe media path in {label}")
    try:
        path = (web_root / str(relative)).resolve(strict=True)
        path.relative_to(web_root)
    except (OSError, ValueError):
        fail(f"{label} is missing or escapes the web root: {raw}")
    if not path.is_file() or path.suffix.lower() not in suffixes or path.stat().st_size == 0:
        fail(f"{label} is not a supported, nonempty local media file: {raw}")
    return path


def load_manifest(path):
    document = read_json(path)
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        fail("Production manifest must be an object with schemaVersion 1")
    nonempty(document.get("bookId"), "manifest.bookId")
    questions = document.get("questions")
    if not isinstance(questions, list) or not questions:
        fail("Manifest must contain source question records")
    ids, numbers = set(), set()
    for question in questions:
        if not isinstance(question, dict):
            fail("Each source question record must be an object")
        n = question.get("number")
        if isinstance(n, bool) or not isinstance(n, int) or n < 1 or n in numbers:
            fail("Source question numbers must be unique positive integers")
        identity = nonempty(question.get("id"), "question.id")
        if identity in ids or question.get("status") not in STATUSES:
            fail(f"Invalid identity or production status for question {n}")
        if question["status"] == "claimed" and not question.get("batchId"):
            fail(f"Claimed question {n} has no batchId")
        ids.add(identity)
        numbers.add(n)
    if document.get("totalQuestions") != len(questions):
        fail("totalQuestions does not match the source record count")
    if "batches" in document and not isinstance(document["batches"], dict):
        fail("manifest.batches must be an object keyed by batch ID")
    return document


def summaries(questions):
    return [
        {key: question.get(key) for key in ("number", "id", "status", "batchId", "lessonId", "sourceEvidence")}
        for question in sorted(questions, key=lambda item: item["number"])
    ]


def status(document):
    counts = Counter(question["status"] for question in document["questions"])
    completed = sorted(question["number"] for question in document["questions"] if question["status"] == "produced")
    return {
        "bookId": document["bookId"],
        "totalQuestions": len(document["questions"]),
        "completedVideos": len(completed),
        "completedQuestionNumbers": completed,
        "counts": {key: counts[key] for key in sorted(STATUSES)},
        "manifestCountersConsistent": document.get("completedVideos") == len(completed)
        and document.get("completedQuestionNumbers") == completed,
        "batches": document.get("batches", {}),
    }


def update_counters(document):
    completed = sorted(question["number"] for question in document["questions"] if question["status"] == "produced")
    document["completedVideos"] = len(completed)
    document["completedQuestionNumbers"] = completed
    document["updatedAt"] = now()


def atomic_save(path, document):
    path = Path(path)
    update_counters(document)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
        temporary = None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def locked_manifest(path):
    try:
        import fcntl
    except ImportError:
        fail("Mutating production commands require a POSIX environment with fcntl (for example Linux or macOS)")
    lock_dir = Path(tempfile.gettempdir()) / "instaanki-production-locks"
    lock_dir.mkdir(mode=0o700, exist_ok=True)
    lock_name = hashlib.sha256(str(path.resolve()).encode()).hexdigest() + ".lock"
    with (lock_dir / lock_name).open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield load_manifest(path)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def validate_batch_id(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
        fail("batch-id must contain 1-64 letters, digits, dots, underscores or hyphens")


def claim(path, count, batch_id):
    validate_batch_id(batch_id)
    policy = SourcePolicy(REPO)
    with locked_manifest(path) as document:
        policy.check_ledger(document)
        policy.require_new_production(batch_id=batch_id)
        trial = policy.production_trial(document)
        if trial is not None and count != trial["maxNewLessons"]:
            fail(f"The limited trial must claim its exact {trial['maxNewLessons']}-question selection; use --count {trial['maxNewLessons']}")
        batches = document.setdefault("batches", {})
        by_number = {q["number"]: q for q in document["questions"]}
        batch = batches.get(batch_id)
        resumed = batch is not None
        changed = False
        if batch is None:
            if trial is not None:
                # Claim the reviewed identities exactly. A held question must
                # fail source review, not be replaced by another ready one.
                chosen = [by_number[n] for n in sorted(trial["questionNumbers"])]
            else:
                legacy = [q for q in document["questions"] if q.get("batchId") == batch_id and q["status"] in {"claimed", "produced"}]
                chosen = sorted(legacy or [q for q in document["questions"] if q["status"] == "ready"], key=lambda q: q["number"])
                if not legacy:
                    chosen = chosen[:count]
            if not chosen:
                return {"bookId": document["bookId"], "batchId": batch_id, "resumed": False, "questions": [], "message": "No ready questions are available"}
            batch = {"batchId": batch_id, "createdAt": now(), "questionNumbers": [q["number"] for q in chosen], "requestedCount": count, "status": "active"}
            batches[batch_id] = batch
            changed = True
        else:
            try:
                chosen = [by_number[n] for n in batch["questionNumbers"]]
            except (KeyError, TypeError):
                fail("Batch checkpoint contains unknown source question numbers")
        if trial is not None and (len(chosen) != trial["maxNewLessons"]
                                  or {q["number"] for q in chosen} != set(trial["questionNumbers"])):
            fail("The batch checkpoint differs from the exact limited-trial selection")
        for question in chosen:
            if question["status"] != "produced":
                policy.require_new_production(question["number"], batch_id=batch_id)
        conflicts = [q["number"] for q in chosen if q["status"] == "claimed" and q.get("batchId") != batch_id]
        if conflicts:
            fail(f"Cannot resume batch; questions are claimed by another batch: {conflicts}")
        # Validate the entire selection before saving any claim or checkpoint.
        evidence = {q["number"]: policy.evidence_for(document, q)
                    for q in chosen if q["status"] != "produced"}
        for question in chosen:
            if question["number"] not in evidence:
                continue
            binding = evidence[question["number"]]
            if question.get("sourceEvidence", binding) != binding:
                fail(f"Q{question['number']} source evidence changed after its previous claim")
            if question.get("sourceEvidence") != binding:
                question["sourceEvidence"] = binding
                changed = True
        for question in chosen:
            if question["status"] == "ready":
                question.update(status="claimed", batchId=batch_id, claimedAt=now())
                changed = True
        batch_status = "completed" if all(q["status"] == "produced" for q in chosen) else "active"
        if batch.get("status") != batch_status:
            batch["status"] = batch_status
            changed = True
        if changed:
            batch["updatedAt"] = now()
            atomic_save(path, document)
        return {
            "bookId": document["bookId"], "batchId": batch_id, "resumed": resumed,
            "questions": summaries(q for q in chosen if q["status"] == "claimed" and q.get("batchId") == batch_id),
            "alreadyProduced": sorted(q["number"] for q in chosen if q["status"] == "produced"),
            "blockedForReview": sorted(q["number"] for q in chosen if q["status"] == "needs_review"),
        }


def release(path, batch_id):
    validate_batch_id(batch_id)
    with locked_manifest(path) as document:
        SourcePolicy(REPO).check_ledger(document)
        batch = document.get("batches", {}).get(batch_id)
        claimed = [q for q in document["questions"] if q["status"] == "claimed" and q.get("batchId") == batch_id]
        if batch is None and not claimed:
            fail(f"Unknown batch: {batch_id}")
        released = [q["number"] for q in claimed]
        for question in claimed:
            question.update(status="ready", batchId=None)
            question.pop("claimedAt", None)
        changed = bool(claimed)
        if batch is not None and batch.get("status") not in {"released", "completed"}:
            batch.update(status="released", releasedAt=now(), updatedAt=now())
            changed = True
        if changed:
            atomic_save(path, document)
        return {"bookId": document["bookId"], "batchId": batch_id, "releasedQuestionNumbers": sorted(released), "producedRecordsChanged": False}


def registry_for(version, explicit_path=None):
    if explicit_path:
        documents = [read_json(explicit_path)]
    else:
        documents = [read_json(path) for path in sorted((REPO / "taxonomy").glob("registry*.json"))]
    matches = [doc for doc in documents if isinstance(doc, dict) and doc.get("version") == version]
    if not matches:
        fail(f"No local canonical taxonomy registry found for version {version}")
    registry = matches[0]
    if any(doc.get("tags") != registry.get("tags") for doc in matches[1:]):
        fail(f"Conflicting registry snapshots declare version {version}")
    tags = registry.get("tags", [])
    if len({tag.get("id") for tag in tags}) != len(tags):
        fail("Canonical registry has duplicate tag IDs")
    return {tag["id"]: tag for tag in tags}


def select_lesson(path, book_id, question_number):
    value = read_json(path)
    candidates = value if isinstance(value, list) else value.get("lessons", [value]) if isinstance(value, dict) else []
    matches = [item for item in candidates if isinstance(item, dict) and isinstance(item.get("source"), dict)
               and item["source"].get("bookId") == book_id and item["source"].get("questionNumber") == question_number]
    if len(matches) != 1:
        fail(f"Expected exactly one lesson for book {book_id}, question {question_number}; found {len(matches)}")
    return matches[0]


def expected_content(question, lesson, tag_ids):
    # Legacy published starters retain their frozen source review. Every new
    # source-bound claim must approve this exact teaching script and keyed quiz.
    if question.get("status") != "produced" or "sourceEvidence" in question:
        validate_content_review(question, lesson, question.get("sourceEvidence"))
    if "expectedTagIds" in question and set(question["expectedTagIds"]) != set(tag_ids):
        fail("Lesson tags do not match this question's reviewed expectedTagIds")
    if "expectedCorrectIndex" in question and question["expectedCorrectIndex"] != lesson["quiz"]["correctIndex"]:
        fail("Lesson quiz key does not match this question's expectedCorrectIndex")
    if "expectedQuizSha256" in question and question["expectedQuizSha256"] != canonical_hash(lesson["quiz"]):
        fail("Lesson quiz does not match this question's reviewed quiz hash")


def verify_lesson(lesson, document, question, web_root, registry_path=None, timing_path=None):
    web_root = Path(web_root).resolve(strict=True)
    lesson_id = nonempty(lesson.get("id"), "lesson.id")
    version = lesson.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        fail("lesson.version must be a positive integer")
    source = lesson["source"]
    if isinstance(source.get("questionNumber"), bool) or not isinstance(source.get("questionNumber"), int):
        fail("Lesson source.questionNumber must be an integer")
    if source.get("bookId") != document["bookId"] or source.get("questionNumber") != question["number"]:
        fail("Lesson source does not match the production record")
    if "questionId" in source and source["questionId"] != question["id"]:
        fail("Lesson source.questionId does not match the stable source ID")
    nonempty(lesson.get("title"), "lesson.title")
    duration = number(lesson.get("durationSeconds"), "lesson.durationSeconds")
    if not 60 <= duration <= 90:
        fail("Full teaching lessons must last 60-90 seconds")

    quiz = lesson.get("quiz")
    if not isinstance(quiz, dict):
        fail("Lesson requires a quiz")
    nonempty(quiz.get("prompt"), "quiz.prompt")
    nonempty(quiz.get("explanation"), "quiz.explanation")
    options = quiz.get("options")
    if not isinstance(options, list) or not 2 <= len(options) <= 8:
        fail("Quiz must contain 2-8 answer options")
    normalized_options = [nonempty(option, "quiz option").casefold() for option in options]
    if len(set(normalized_options)) != len(options):
        fail("Quiz contains duplicate options")
    correct = quiz.get("correctIndex")
    if isinstance(correct, bool) or not isinstance(correct, int) or not 0 <= correct < len(options):
        fail("Quiz correctIndex is invalid")

    taxonomy_version = nonempty(lesson.get("taxonomyVersion"), "lesson.taxonomyVersion")
    registry = registry_for(taxonomy_version, registry_path)
    tags = lesson.get("tags")
    if not isinstance(tags, list) or not tags:
        fail("Lesson requires canonical tags")
    tag_ids = []
    for tag in tags:
        if not isinstance(tag, dict) or tag.get("id") not in registry:
            fail(f"Unknown or malformed canonical tag: {tag}")
        canonical = registry[tag["id"]]
        if canonical.get("status") != "active" or tag.get("label") != canonical.get("label"):
            fail(f"Inactive tag or noncanonical English label: {tag['id']}")
        tag_ids.append(tag["id"])
    if len(set(tag_ids)) != len(tag_ids):
        fail("Lesson contains duplicate canonical tags")
    primary = nonempty(lesson.get("primarySpecialtyId"), "lesson.primarySpecialtyId")
    specialties = {tid for tid in tag_ids if registry[tid]["facet"] == "specialty"}
    if primary not in specialties:
        fail("The primary specialty must be present in the canonical tags")
    secondaries = set(lesson.get("secondarySpecialtyIds", []))
    if secondaries != specialties - {primary}:
        fail("Additional specialty tags must be declared in secondarySpecialtyIds")
    domains = [tid for tid in tag_ids if registry[tid]["facet"] == "domain"]
    primary_domain = lesson.get("primaryDomainId") or (domains[0] if len(domains) == 1 else None)
    if primary_domain not in domains or primary not in registry[primary_domain]["specialty_ids"]:
        fail("A primary domain compatible with the primary specialty is required")
    if len([tid for tid in tag_ids if registry[tid]["facet"] == "focus"]) != 1:
        fail("Exactly one tested learning-focus tag is required")
    for tid in tag_ids:
        if not specialties.intersection(registry[tid].get("specialty_ids", [])):
            fail(f"Tag scope does not match the selected specialties: {tid}")
    expected_content(question, lesson, tag_ids)

    assets = set()
    audio = media_file(web_root, lesson.get("audioUrl"), AUDIO_SUFFIXES, "lesson.audioUrl")
    assets.add(audio)
    assets.add(media_file(web_root, lesson.get("poster"), IMAGE_SUFFIXES, "lesson.poster"))
    locus = lesson.get("locus")
    if not isinstance(locus, dict):
        fail("A fixed memory-palace locus is required")
    nonempty(locus.get("id"), "locus.id")
    scenes = lesson.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        fail("Lesson requires a scene timeline")
    previous_end = 0.0
    scene_ids = set()
    for scene in scenes:
        if not isinstance(scene, dict):
            fail("Every scene must be an object")
        scene_id = nonempty(scene.get("id"), "scene.id")
        if scene_id in scene_ids:
            fail("Scene IDs must be unique within the lesson")
        scene_ids.add(scene_id)
        start = number(scene.get("start"), "scene.start")
        end = number(scene.get("end"), "scene.end")
        require_close(start, previous_end, "Scene continuity")
        if start < 0 or end <= start:
            fail("Each scene must have a positive duration")
        previous_end = end
        nonempty(scene.get("transcript"), "scene.transcript")
        assets.add(media_file(web_root, scene.get("image"), IMAGE_SUFFIXES, "scene.image"))
    outro = lesson.get("realImageOutro")
    if not isinstance(outro, dict):
        fail("Lesson requires a real-image outro")
    outro_start = number(outro.get("start"), "realImageOutro.start")
    outro_end = number(outro.get("end"), "realImageOutro.end")
    require_close(outro_start, previous_end, "Outro continuity")
    require_close(outro_end, duration, "Timeline end")
    if outro_end <= outro_start:
        fail("Real-image outro must have a positive duration")

    # The measured companion records the final TTS samples; metadata estimates
    # alone are insufficient to establish scene/audio synchronization.
    timing_file = Path(timing_path).resolve() if timing_path else audio.with_suffix(".timing.json")
    timing = read_json(timing_file)
    if not isinstance(timing, dict):
        fail("Measured audio timing must be a JSON object")
    measured_scenes = timing.get("scenes")
    if not isinstance(measured_scenes, list) or len(measured_scenes) != len(scenes):
        fail("Measured audio timing must contain the same scenes as the lesson")
    require_close(number(timing.get("duration"), "timing.duration"), duration, "Measured timeline duration")
    for scene, measured in zip(scenes, measured_scenes):
        if scene["id"] != measured.get("id"):
            fail("Scene order differs from measured audio timing")
        require_close(number(measured.get("start"), "timing scene.start"), scene["start"], "Measured scene start")
        require_close(number(measured.get("end"), "timing scene.end"), scene["end"], "Measured scene end")
        text = measured.get("text")
        if not isinstance(text, str) or " ".join(text.split()) != " ".join(scene["transcript"].split()):
            fail("Scene transcript differs from the final audio timing transcript")
    if "narrationDuration" in timing:
        require_close(number(timing["narrationDuration"], "timing.narrationDuration"), outro_start, "Narration/outro boundary")

    try:
        guidance_validation = verify_guidance(lesson, timing, web_root)
        validate_presentation(lesson)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        fail(f"Visual/audio guidance or presentation validation failed: {exc}")

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        fail("ffprobe is required to validate the actual audio before completion")
    try:
        probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,duration", "-of", "json", str(audio)], capture_output=True, text=True, timeout=30, check=True)
        audio_metadata = json.loads(probe.stdout)
        audio_duration = float(audio_metadata["format"]["duration"])
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError) as exc:
        fail(f"Cannot verify audio duration with ffprobe: {exc}")
    if not math.isfinite(audio_duration) or not any(stream.get("codec_type") == "audio" for stream in audio_metadata.get("streams", [])):
        fail("The media file has no valid audio stream")
    require_close(audio_duration, duration, "Actual audio duration", AUDIO_TOLERANCE)

    provenance_path = web_root / "media" / "real" / "attributions.json"
    provenance_document = read_json(provenance_path) if provenance_path.is_file() else {"assets": []}
    if not isinstance(provenance_document, dict) or not isinstance(provenance_document.get("assets"), list):
        fail("Real-image attribution manifest must contain an assets array")
    provenance_entries = provenance_document["assets"]
    real_images = lesson.get("realImages")
    if not isinstance(real_images, list) or not real_images:
        fail("At least one attributed real medical image is required")
    for real in real_images:
        if not isinstance(real, dict):
            fail("Real-image provenance must be an object")
        image_path = media_file(web_root, real.get("url"), IMAGE_SUFFIXES, "realImages.url")
        assets.add(image_path)
        for key in ("title", "caption", "author", "license", "attribution"):
            nonempty(real.get(key), f"realImages.{key}")
        public_url(real.get("sourceUrl"), "realImages.sourceUrl")
        public_url(real.get("licenseUrl"), "realImages.licenseUrl")
        related = [entry for entry in provenance_entries if isinstance(entry, dict)
                   and str(entry.get("publicPath", "")).lstrip("/") == str(real["url"]).lstrip("/")]
        provenance = related[0] if len(related) == 1 else real
        if provenance.get("aiGenerated") is not False:
            fail("Real medical imagery needs explicit aiGenerated:false provenance")
        expected_hash = provenance.get("sha256")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
            fail("Real-image provenance requires a SHA-256 of the verified source file")
        if file_hash(image_path) != expected_hash.lower():
            fail(f"Real-image bytes no longer match their verified provenance: {real['url']}")
    return {
        "lessonId": lesson_id,
        "lessonVersion": version,
        "lessonSha256": canonical_hash(lesson),
        "quizSha256": canonical_hash(quiz),
        "sourceQuestionId": question["id"],
        "taxonomyVersion": taxonomy_version,
        "tagIds": tag_ids,
        "durationSeconds": duration,
        "actualAudioDurationSeconds": audio_duration,
        "sceneCount": len(scenes),
        "visualGuidance": guidance_validation,
        "realImageCount": len(real_images),
        "audioTimingSha256": file_hash(timing_file),
        "mediaSha256": {str(path.relative_to(web_root)): file_hash(path) for path in sorted(assets)},
        "checkedAt": now(),
    }


def verify_qa_report(path, document, question, lesson, validation):
    if path is None:
        fail("Completion requires --qa-report with the checks actually performed; no manifest was changed")
    report = read_json(path)
    if not isinstance(report, dict) or report.get("schemaVersion") != 1:
        fail("QA report must be an object with schemaVersion 1")
    if report.get("bookId") != document["bookId"]:
        fail("QA report bookId does not match the production manifest")
    reviewed_at = nonempty(report.get("reviewedAt"), "QA report.reviewedAt")
    try:
        reviewed_time = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        if reviewed_time.tzinfo is None:
            fail("QA report.reviewedAt must include a timezone")
    except ValueError:
        fail("QA report.reviewedAt must be an ISO-8601 timestamp")
    required_checks = ("sourceChecked", "visualInspected", "audioDecoded", "timelineBrowserTested")
    explicit_checks = required_checks + ("physicalAndroidTested", "humanListeningReviewed")
    for key in explicit_checks:
        if not isinstance(report.get(key), bool):
            fail(f"QA report.{key} must explicitly be true or false")
    for key in required_checks:
        if report[key] is not True:
            fail(f"The lesson asset review is incomplete: QA report.{key} is false")
    candidates = report.get("lessons", [report])
    if not isinstance(candidates, list):
        fail("QA report.lessons must be an array")
    matches = [entry for entry in candidates if isinstance(entry, dict)
               and entry.get("questionNumber") == question["number"] and entry.get("lessonId") == lesson["id"]]
    if len(matches) != 1:
        fail("QA report must identify this exact source question and lesson once")
    selected = matches[0]
    if "lessonSha256" in selected and selected["lessonSha256"] != validation["lessonSha256"]:
        fail("The final lesson metadata changed after the recorded QA review")
    notes = report.get("notes", [])
    if not isinstance(notes, list) or any(not isinstance(note, str) or not note.strip() for note in notes):
        fail("QA report.notes must be an array of nonempty strings")
    return {
        "schemaVersion": 1,
        "bookId": document["bookId"],
        "questionNumber": question["number"],
        "lessonId": lesson["id"],
        "reviewedAt": reviewed_at,
        **{key: report[key] for key in explicit_checks},
        "notes": notes,
        "lessonEvidence": {key: value for key, value in selected.items()
                           if key not in {"questionNumber", "lessonId"}} if "lessons" in report else {},
        "reportSha256": canonical_hash(report),
        "scope": "verified_lesson_assets_and_browser_timeline",
    }


def complete(path, args):
    if args.qa_report is None:
        fail("Completion requires --qa-report with the checks actually performed; no manifest was changed")
    initial = load_manifest(path)
    policy = SourcePolicy(REPO)
    policy.check_ledger(initial)
    record = next((q for q in initial["questions"] if q["number"] == args.question), None)
    if record is None:
        fail(f"Source question {args.question} is not in this book")
    lesson = select_lesson(args.lesson, initial["bookId"], args.question)
    source_evidence = None
    if record.get("status") == "produced":
        published = policy.published_validation(lesson, initial, record)
        if published is not None:
            policy.verify_frozen_assets(lesson, published, args.root)
        else:
            source_evidence = policy.validate_lesson_source(lesson, initial, record)
    else:
        source_evidence = policy.validate_lesson_source(lesson, initial, record)
        if policy.production_trial(initial) is not None and lesson.get("presentation") is None:
            fail("New trial lessons require the three-image gallery and measured narrated recap presentation")
    validation = verify_lesson(lesson, initial, record, args.root, args.registry, args.timing)
    if source_evidence is not None:
        validation["sourceEvidenceSha256"] = canonical_hash(source_evidence)
        validation["sourceReviewSha256"] = canonical_hash(record["sourceReview"])
    qa_report = verify_qa_report(args.qa_report, initial, record, lesson, validation)
    with locked_manifest(path) as document:
        question = next(q for q in document["questions"] if q["number"] == args.question)
        if question["id"] != validation["sourceQuestionId"]:
            fail("Source identity changed during validation; retry against the updated manifest")
        if source_evidence is not None:
            # Reopen the private evidence after asset checks, before any write.
            current = SourcePolicy(REPO).validate_lesson_source(lesson, document, question)
            if current != source_evidence:
                fail("Source evidence changed during validation; no completion was saved")
            if canonical_hash(question["sourceReview"]) != validation["sourceReviewSha256"]:
                fail("Authored-content source review changed during validation; no completion was saved")
        expected_content(question, lesson, validation["tagIds"])
        if question["status"] == "needs_review":
            fail("This source question is still needs_review; resolve its recorded issue before completion")
        if question["status"] == "claimed" and question.get("batchId") != args.batch_id:
            fail("Question is claimed; complete it with the owning --batch-id")
        if question["status"] == "produced":
            old = question.get("productionValidation", {})
            if (question.get("lessonId") == lesson["id"]
                    and old.get("lessonSha256") == validation["lessonSha256"]
                    and old.get("mediaSha256") == validation["mediaSha256"]
                    and old.get("audioTimingSha256") == validation["audioTimingSha256"]
                    and question.get("qaReport", {}).get("reportSha256") == qa_report["reportSha256"]):
                return {"bookId": document["bookId"], "question": args.question, "status": "produced", "idempotent": True, "completedVideos": status(document)["completedVideos"], "pendingDeviceQA": question.get("pendingDeviceQA"), "pendingHumanListeningQA": question.get("pendingHumanListeningQA")}
            fail("Question is already produced with different or unverified content; review a lesson revision explicitly rather than overwriting its completion record")
        if args.batch_id:
            batch = document.get("batches", {}).get(args.batch_id)
            if batch is None or args.question not in batch.get("questionNumbers", []):
                fail("Question is not assigned to the supplied batch checkpoint")
        question.update(status="produced", lessonId=lesson["id"], producedAt=now(), productionValidation=validation,
                        qaReport=qa_report, assetQaRecordedAt=now(),
                        pendingDeviceQA=not qa_report["physicalAndroidTested"],
                        pendingHumanListeningQA=not qa_report["humanListeningReviewed"])
        if args.batch_id:
            question["batchId"] = args.batch_id
            batch = document["batches"][args.batch_id]
            produced_numbers = {q["number"] for q in document["questions"] if q["status"] == "produced"}
            if set(batch["questionNumbers"]).issubset(produced_numbers):
                batch["status"] = "completed"
            batch["updatedAt"] = now()
        atomic_save(path, document)
        return {"bookId": document["bookId"], "question": args.question, "sourceQuestionId": question["id"], "lessonId": lesson["id"], "status": "produced", "completedVideos": document["completedVideos"], "validation": validation, "qaReport": qa_report, "pendingDeviceQA": question["pendingDeviceQA"], "pendingHumanListeningQA": question["pendingHumanListeningQA"]}


def positive_int(value):
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer")
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def manifest_path(args):
    if args.manifest:
        return Path(args.manifest).resolve()
    directory = REPO / "production" / "books"
    if args.book:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.book):
            fail("Unsafe book ID")
        return directory / f"{args.book}.json"
    return directory / f"{SourcePolicy(REPO).book_id}.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--book", help="Book ID under production/books/")
    target.add_argument("--manifest", help="Explicit production manifest path")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Read production counts and batch checkpoints")
    next_parser = commands.add_parser("next", help="Read the earliest ready, unclaimed source IDs")
    next_parser.add_argument("--count", type=positive_int, default=10)
    claim_parser = commands.add_parser("claim", help="Atomically claim a stable batch, or resume the same batch")
    claim_parser.add_argument("--count", type=positive_int, default=10)
    claim_parser.add_argument("--batch-id", required=True)
    release_parser = commands.add_parser("release", help="Release only the unfinished claims in a batch")
    release_parser.add_argument("--batch-id", required=True)
    done = commands.add_parser("complete", help="Verify final media and mark one source question produced")
    done.add_argument("--question", type=positive_int, required=True)
    done.add_argument("--lesson", type=Path, required=True, help="Single lesson, lesson array, or object containing lessons")
    done.add_argument("--root", type=Path, required=True, help="Root containing local lesson media")
    done.add_argument("--batch-id", help="Required when completing a claimed source question")
    done.add_argument("--registry", type=Path, help="Explicit canonical registry snapshot")
    done.add_argument("--timing", type=Path, help="Measured audio timing companion; defaults beside the audio file")
    done.add_argument("--qa-report", type=Path, required=True, help="Explicit asset/browser review report, including unperformed Android-device and human-listening checks")
    args = parser.parse_args()
    try:
        path = manifest_path(args)
        if args.command == "status":
            result = status(load_manifest(path))
        elif args.command == "next":
            document = load_manifest(path)
            trial = SourcePolicy(REPO).production_trial(document)
            ready = sorted((q for q in document["questions"] if q["status"] == "ready"
                            and (trial is None or (trial["status"] == "active"
                                                  and q["number"] in trial["questionNumbers"]))),
                           key=lambda q: q["number"])[:args.count]
            result = {"bookId": document["bookId"], "readOnly": True, "questions": summaries(ready)}
        elif args.command == "claim":
            result = claim(path, args.count, args.batch_id)
        elif args.command == "release":
            result = release(path, args.batch_id)
        else:
            result = complete(path, args)
        if args.command in {"status", "next"}:
            policy = SourcePolicy(REPO)
            try:
                policy.source_records(load_manifest(path))
                trial = policy.production_trial()
                enabled = trial["status"] == "active" if trial else policy.policy.get("newProductionEnabled") is True
                result["sourcePolicy"] = {"activeBookId": policy.book_id, "sourceAvailable": True,
                                          "newProductionBlocked": not enabled}
                if trial is not None:
                    result["sourcePolicy"].update(
                        scope="limited-trial", trialStatus=trial["status"], batchId=trial["batchId"],
                        authorizedQuestionNumbers=sorted(trial["questionNumbers"]), maxNewLessons=trial["maxNewLessons"],
                        generalNewProductionEnabled=False,
                        reason="Only the recorded trial questions are authorized while the trial is active; all other new production remains paused.")
                elif not enabled:
                    result["sourcePolicy"]["reason"] = "New lesson production is paused by the current explicit user instruction; existing app repairs remain allowed."
            except ValueError as exc:
                result["sourcePolicy"] = {"activeBookId": policy.book_id, "sourceAvailable": False,
                                          "newProductionBlocked": True, "reason": str(exc)}
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ProductionError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
