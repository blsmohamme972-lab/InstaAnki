#!/usr/bin/env python3
"""Assemble source-reviewed original-book lessons with measured visual guidance.

This command requires the registered private evidence and per-question content
review. It assembles data and does not assert production completion or QA.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
from pathlib import Path, PurePosixPath
import tempfile
from urllib.parse import urlparse

from guidance import assemble_guidance, validate_plan
from presentation import number as presentation_number, validate_presentation
from production import verify_lesson
from source_policy import SourcePolicy, SourcePolicyError, canonical_hash, content_fingerprints


ROOT = Path(__file__).resolve().parents[1]
BOOK_ID = "shahzad-raja-2015-200-practice-questions"
BOOK_TITLE = "200 Practice Questions in Cardiothoracic Surgery"
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}\Z")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".book-assembly-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def check_output_paths(outputs, inputs):
    resolved = [path.resolve() for path in outputs]
    if len(set(resolved)) != len(resolved):
        raise ValueError("Assembly outputs must use distinct paths; lesson data and validation cannot overwrite each other")
    if set(resolved).intersection(path.resolve() for path in inputs):
        raise ValueError("Assembly output must not overwrite an authoring input, source evidence, policy or ledger")


def text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def media_path(value, label: str) -> str:
    value = text(value, label)
    if value.startswith("/media/"):
        value = value[1:]
    candidate = PurePosixPath(value)
    if (not value.startswith("media/") or candidate.is_absolute()
            or "\\" in value or ":" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise ValueError(f"{label} must be a safe local media path")
    return value


def source_references(value, label: str) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} requires at least one independently checked reference")
    result = []
    for item in value:
        reference = {"url": item} if isinstance(item, str) else copy.deepcopy(item)
        if not isinstance(reference, dict):
            raise ValueError(f"{label} contains a malformed reference")
        url = reference.get("url", reference.get("sourceUrl"))
        parsed = urlparse(text(url, label + ".url"))
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"{label} reference must use an HTTPS URL")
        reference["url"] = url
        result.append(reference)
    return result


def load_draft(path: Path) -> dict:
    document = read(path)
    if not isinstance(document, dict) or document.get("schemaVersion", 1) != 1:
        raise ValueError("Book draft must be a schemaVersion-1 object")
    if document.get("bookId") != BOOK_ID:
        raise ValueError("Book authoring must preserve the locked original source identity")
    lessons = document.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        raise ValueError("Book draft must contain a nonempty lessons array")
    ids, audio_ids, numbers = set(), set(), set()
    for lesson in lessons:
        if not isinstance(lesson, dict):
            raise ValueError("Draft lessons must be objects")
        for field, seen in (("id", ids), ("audioLessonId", audio_ids)):
            value = text(lesson.get(field), field)
            if not SAFE_ID.fullmatch(value) or value in seen:
                raise ValueError(f"Unsafe or duplicate {field}: {value}")
            seen.add(value)
        number = lesson.get("questionNumber")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1 or number in numbers:
            raise ValueError("questionNumber must be a unique positive integer")
        numbers.add(number)
        text(lesson.get("title"), "lesson.title")
        media_path(lesson.get("poster"), "lesson.poster")
        normalized_real_images(lesson)
        source_references(lesson.get("references"), "lesson.references")
        scenes = lesson.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("Every lesson needs narration scenes")
        scene_ids, phrase_ids = set(), set()
        for scene in scenes:
            sid = text(scene.get("id"), "scene.id")
            if sid in scene_ids:
                raise ValueError(f"Duplicate scene id in {lesson['id']}: {sid}")
            scene_ids.add(sid)
            narration = text(scene.get("voice_text"), "scene.voice_text")
            text(scene.get("headline"), "scene.headline")
            if scene.get("image"):
                media_path(scene["image"], "scene.image")
            if "phrases" in scene:
                phrases = scene["phrases"]
                if not isinstance(phrases, list) or not phrases:
                    raise ValueError("Authored phrases must be a nonempty array")
                if " ".join(p.get("text", "") for p in phrases) != scene.get("spoken_text", narration):
                    raise ValueError(f"{lesson['id']}/{sid}: phrases must preserve the exact spoken narration")
                for phrase in phrases:
                    pid = text(phrase.get("id"), "phrase.id")
                    if pid in phrase_ids:
                        raise ValueError("Phrase IDs must be unique within a lesson")
                    phrase_ids.add(pid)
        validate_presentation_plan(lesson)
    SourcePolicy(ROOT).validate_authoring(document, lessons)
    return document


def audio_input(document: dict) -> dict:
    output = []
    for lesson in document["lessons"]:
        output.append({
            "id": lesson["audioLessonId"],
            "lessonId": lesson["id"],
            "title": lesson["title"],
            "source_question_number": lesson["source_question_number"],
            "sourceEvidence": copy.deepcopy(lesson["sourceEvidence"]),
            "locus": copy.deepcopy(lesson["locus"]),
            "mcq": copy.deepcopy(lesson["mcq"]),
            "real_image_path": media_path(lesson["realImage"].get("url", lesson["realImage"].get("publicPath")), "realImage.url"),
            "realImages": copy.deepcopy(lesson["realImages"]),
            "presentationPlan": copy.deepcopy(lesson["presentationPlan"]),
            "scenes": copy.deepcopy(lesson["scenes"]),
        })
    return {"schemaVersion": 1, "bookId": BOOK_ID, "lessons": output}


def normalized_real_image(original: dict) -> dict:
    """Validate canonical reviewed provenance without rewriting its fields."""
    if not isinstance(original, dict):
        raise ValueError("Clinical source records must be objects")
    real = copy.deepcopy(original)
    real["url"] = media_path(real.get("url", real.get("publicPath")), "realImage.url")
    if isinstance(real.get("license"), dict):
        license_record = real["license"]
        real["license"] = license_record.get("name") or license_record.get("id")
        real.setdefault("licenseUrl", license_record.get("url"))
    if real != original:
        raise ValueError(
            "Clinical image records must be canonical before source review: use "
            "url='media/...' without a leading slash, a string license, and an "
            "explicit HTTPS licenseUrl; publicPath-only and license-object aliases "
            "are not accepted"
        )
    if real.get("aiGenerated") is not False:
        raise ValueError("The clinical source record must explicitly declare aiGenerated:false")
    if (not isinstance(real.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", real["sha256"])):
        raise ValueError("The clinical source record must bind its original bytes with SHA-256")
    for field in ("title", "caption", "author", "license", "attribution"):
        text(real.get(field), f"realImage.{field}")
    for field in ("sourceUrl", "licenseUrl"):
        parsed = urlparse(text(real.get(field), f"realImage.{field}"))
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"realImage.{field} must use an HTTPS URL")
    return real


def normalized_real_images(lesson: dict) -> list[dict]:
    """Keep the audio's primary photograph and the ending gallery consistent."""
    primary = normalized_real_image(lesson.get("realImage"))
    originals = lesson.get("realImages")
    if not isinstance(originals, list) or not 3 <= len(originals) <= 6:
        raise ValueError("New book lessons require three to six licensed realImages")
    images = [normalized_real_image(image) for image in originals]
    if images[0] != primary:
        raise ValueError("realImage must exactly match the first realImages record")
    for field in ("url", "sha256"):
        if len({image[field] for image in images}) != len(images):
            raise ValueError(f"Clinical gallery images must have distinct {field} values")
    return images


def validate_presentation_plan(lesson: dict) -> dict:
    """Validate source-reviewed ending text without inventing audio timestamps.

    Drafts provide final-scene phrase IDs, node labels and graph edges. Actual
    display times are attached only after those exact phrases are synthesized.
    This requirement applies to newly assembled lessons; immutable older packs
    do not pass through the authoring assembler.
    """
    plan = lesson.get("presentationPlan")
    if (not isinstance(plan, dict) or type(plan.get("schemaVersion")) is not int
            or plan["schemaVersion"] != 1):
        raise ValueError("New book lessons require presentationPlan schemaVersion 1")
    scenes = lesson.get("scenes")
    if not isinstance(scenes, list) or not scenes or not isinstance(scenes[-1], dict):
        raise ValueError("A narrated ending requires the final authored scene")
    ending = scenes[-1]
    if plan.get("endingSceneId") != ending.get("id"):
        raise ValueError("presentationPlan must reference the final narrated scene")
    phrases = ending.get("phrases")
    if (not isinstance(phrases, list) or not phrases
            or any(not isinstance(phrase, dict) for phrase in phrases)):
        raise ValueError("The final narrated scene requires explicit phrases")
    phrase_ids = [text(phrase.get("id"), "ending phrase.id") for phrase in phrases]
    if len(set(phrase_ids)) != len(phrase_ids):
        raise ValueError("Ending phrase IDs must be unique")
    recap = plan.get("recap")
    if not isinstance(recap, dict):
        raise ValueError("presentationPlan requires a narrated recap")
    nodes = recap.get("nodes")
    if (not isinstance(nodes, list) or not 2 <= len(nodes) <= 6
            or any(not isinstance(node, dict) for node in nodes)):
        raise ValueError("The narrated recap requires two to six nodes")
    node_ids = [text(node.get("id"), "recap node.id") for node in nodes]
    for node in nodes:
        text(node.get("label"), "recap node.label")
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("Recap node IDs must be unique")
    edges = recap.get("edges", [])
    if not isinstance(edges, list) or any(
            not isinstance(edge, dict) or edge.get("from") not in node_ids
            or edge.get("to") not in node_ids or edge["from"] == edge["to"]
            for edge in edges):
        raise ValueError("Recap edges must connect distinct existing nodes")
    bindings = recap.get("cueBindings")
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("Every recap node requires an authored phrase binding")
    bound_nodes, bound_phrases = set(), set()
    previous_index = -1
    for binding in bindings:
        if (not isinstance(binding, dict) or set(binding) != {"phraseId", "nodeId"}
                or binding.get("phraseId") not in phrase_ids or binding.get("nodeId") not in node_ids):
            raise ValueError("Recap bindings must name only a final-scene phraseId and existing nodeId")
        index = phrase_ids.index(binding["phraseId"])
        if index <= previous_index or binding["phraseId"] in bound_phrases:
            raise ValueError("Recap phrase bindings must follow the final narration order without duplicates")
        previous_index = index
        bound_nodes.add(binding["nodeId"])
        bound_phrases.add(binding["phraseId"])
    if bound_nodes != set(node_ids):
        raise ValueError("Every recap node requires an authored phrase binding")
    return plan


def assemble_presentation(original: dict, timing: dict, images: list[dict]) -> dict:
    """Bind the gallery and mind map to the measured final narrated scene."""
    plan = validate_presentation_plan(original)
    ending_id = plan["endingSceneId"]
    measured_scenes = timing.get("scenes")
    if (not isinstance(measured_scenes, list) or not measured_scenes
            or not isinstance(measured_scenes[-1], dict)
            or measured_scenes[-1].get("id") != ending_id):
        raise ValueError("Measured audio must end with the reviewed ending scene")
    ending = measured_scenes[-1]
    start = presentation_number(ending.get("voiceStart"), "ending voiceStart")
    end = presentation_number(ending.get("voiceEnd"), "ending voiceEnd")
    measured_cues = timing.get("cues")
    if (not isinstance(measured_cues, list) or not measured_cues
            or any(not isinstance(cue, dict) for cue in measured_cues)):
        raise ValueError("The narrated ending requires measured phrase cues")
    cue_ids = [text(cue.get("id"), "measured phrase.id") for cue in measured_cues]
    if len(set(cue_ids)) != len(cue_ids):
        raise ValueError("Measured phrase IDs must be unique")
    for cue in measured_cues:
        voice_start = presentation_number(cue.get("voiceStart"), "phrase voiceStart")
        voice_end = presentation_number(cue.get("voiceEnd"), "phrase voiceEnd")
        if not 0 <= voice_start < voice_end:
            raise ValueError("Measured phrases require positive spoken intervals")
    ending_cues = [cue for cue in measured_cues if cue.get("sceneId") == ending_id]
    authored_ids = [phrase["id"] for phrase in original["scenes"][-1]["phrases"]]
    if [cue["id"] for cue in ending_cues] != authored_ids:
        raise ValueError("Measured ending phrases differ from the reviewed narration")
    if (not 0 <= start < end or abs(start - ending_cues[0]["voiceStart"]) > .001
            or abs(end - ending_cues[-1]["voiceEnd"]) > .001
            or abs(end - max(cue["voiceEnd"] for cue in measured_cues)) > .001
            or measured_cues[-1]["sceneId"] != ending_id):
        raise ValueError("Ending boundaries must match the actual final narrated phrases")
    by_id = {cue["id"]: cue for cue in ending_cues}
    recap = plan["recap"]
    bindings = []
    for binding in recap["cueBindings"]:
        cue = by_id[binding["phraseId"]]
        bindings.append({**copy.deepcopy(binding), "startSeconds": cue["voiceStart"],
                         "endSeconds": cue["voiceEnd"]})
    presentation = {
        "schemaVersion": 1,
        "effectiveEndSeconds": end,
        "narrationEndSeconds": end,
        "clinicalGallery": {"startSeconds": start, "endSeconds": end,
                            "images": copy.deepcopy(images)},
        "recap": {"startSeconds": start, "endSeconds": end,
                  "nodes": copy.deepcopy(recap["nodes"]),
                  "edges": copy.deepcopy(recap.get("edges", [])),
                  "cueBindings": bindings},
    }
    validate_presentation({"durationSeconds": timing.get("duration"),
                           "visualGuidance": {"cues": measured_cues},
                           "realImages": images, "presentation": presentation})
    return presentation


def assemble(document: dict, guidance_document: dict, web_root: Path, registry_path: Path) -> tuple[list, list]:
    if guidance_document.get("schemaVersion") != 1:
        raise ValueError("Visual guidance must declare schemaVersion 1")
    plans = {plan["audioLessonId"]: plan for plan in guidance_document["lessons"]}
    if len(plans) != len(guidance_document["lessons"]):
        raise ValueError("Guidance audio lesson identities must be unique")
    registry = read(registry_path)
    tags = {tag["id"]: tag for tag in registry["tags"]}
    output, validations = [], []
    policy = SourcePolicy(ROOT)
    book = policy.ledger()
    source_bindings = policy.validate_authoring(document, document["lessons"])
    source_records = {q["number"]: q for q in book["questions"]}
    for original in document["lessons"]:
        identifier = original["id"]
        audio_identifier = original["audioLessonId"]
        plan = plans.get(audio_identifier)
        if plan is None or plan.get("id", identifier) != identifier:
            raise ValueError(f"Missing or mismatched guidance for {identifier}")
        validate_plan(plan, original["scenes"], web_root)
        for scene, planned in zip(original["scenes"], plan["scenes"]):
            if "phrases" in scene and scene["phrases"] != planned["phrases"]:
                raise ValueError(f"{identifier}/{scene['id']}: draft and guidance phrases differ")
        audio_url = f"media/audio/{audio_identifier}.mp3"
        timing = read((web_root / audio_url).with_suffix(".timing.json"))
        if timing.get("lessonId") != audio_identifier or str(timing.get("audioPath", "")).lstrip("/") != audio_url:
            raise ValueError(f"Measured audio identity does not match {identifier}")
        if len(timing.get("scenes", [])) != len(original["scenes"]):
            raise ValueError(f"Measured scene count does not match {identifier}")
        real_images = normalized_real_images(original)
        real = real_images[0]
        real_urls = {image["url"] for image in real_images}
        if str(timing["realImageOutro"].get("imagePath", "")).lstrip("/") != real["url"]:
            raise ValueError(f"Measured clinical outro does not match {identifier}")
        if not 8 <= timing["realImageOutro"]["end"] - timing["realImageOutro"]["start"] <= 10:
            raise ValueError(f"{identifier}: clinical outro must last 8–10 seconds")
        tag_ids = original.get("tagIds")
        if not isinstance(tag_ids, list) or len(set(tag_ids)) != len(tag_ids) or any(tid not in tags for tid in tag_ids):
            raise ValueError(f"{identifier}: tagIds must be unique canonical registry IDs")
        specialties = [tid for tid in tag_ids if tags[tid]["facet"] == "specialty"]
        primary = original.get("primarySpecialtyId") or (specialties[0] if len(specialties) == 1 else None)
        if primary not in specialties:
            raise ValueError(f"{identifier}: declare the primary specialty")
        scenes = []
        for scene, measured in zip(original["scenes"], timing["scenes"]):
            if scene["id"] != measured.get("id") or scene["voice_text"] != measured.get("text"):
                raise ValueError(f"{identifier}: final audio scenes/transcripts differ from the approved draft")
            scene_image = media_path(scene.get("image", original["poster"]), "scene.image")
            kind = scene.get("kind", "clinical" if scene_image in real_urls else "mnemonic")
            if kind == "clinical" and scene_image not in real_urls:
                raise ValueError(f"{identifier}: a clinical scene needs matching provenance")
            scenes.append({"id": scene["id"], "start": measured["start"], "end": measured["end"],
                           "image": scene_image, "kind": kind, "caption": scene["headline"],
                           "transcript": scene["voice_text"],
                           "camera": {"from": {"x": .5, "y": .5, "scale": 1},
                                      "to": {"x": .5, "y": .5, "scale": 1}}})
        number = original["questionNumber"]
        source_id = f"{BOOK_ID}-q{number:03d}"
        mcq = original["mcq"]
        quiz = {"prompt": mcq["stem"], "options": [item["text"] for item in mcq["options"]],
                "correctIndex": next(i for i,item in enumerate(mcq["options"]) if item["label"] == mcq["correct_answer_letter"]),
                "explanation": mcq["explanation"]}
        source = copy.deepcopy(original["source"])
        source.update(bookId=BOOK_ID, bookTitle=BOOK_TITLE, questionNumber=number,
                      questionId=source_id, evidenceSha256=canonical_hash(source_bindings[identifier]),
                      sourceKind="source-aligned-original-teaching",
                      corroboratingSources=source_references(original["references"], "references"))
        lesson = {
            "id": identifier, "version": original.get("version", 1), "title": original["title"],
            "specialty": tags[primary]["label"], "primarySpecialtyId": primary,
            "taxonomyVersion": registry["version"],
            "tags": [{"id": tid, "label": tags[tid]["label"]} for tid in tag_ids],
            "durationSeconds": timing["duration"], "audioUrl": audio_url,
            "poster": media_path(original["poster"], "poster"), "locus": copy.deepcopy(original["locus"]),
            "mnemonicSymbols": copy.deepcopy(original.get("mnemonicSymbols", [])),
            "scenes": scenes,
            "realImageOutro": {"start": timing["realImageOutro"]["start"], "end": timing["realImageOutro"]["end"]},
            "realImages": real_images, "quiz": quiz, "source": source,
        }
        if len(specialties) > 1:
            lesson["secondarySpecialtyIds"] = original.get("secondarySpecialtyIds", [tid for tid in specialties if tid != primary])
        if "primaryDomainId" in original:
            lesson["primaryDomainId"] = original["primaryDomainId"]
        lesson["visualGuidance"] = assemble_guidance(plan, timing, scenes, audio_url, web_root)
        lesson["presentation"] = assemble_presentation(original, timing, real_images)
        record = source_records[number]
        if content_fingerprints(original, authoring=True) != content_fingerprints(lesson):
            raise ValueError(f"{identifier}: assembly changed the reviewed teaching content")
        policy.validate_lesson_source(lesson, book, record)
        validations.append(verify_lesson(lesson, book, record, web_root, registry_path=registry_path))
        output.append(lesson)
    return output, validations


def merge_lessons(current: list, additions: list) -> list:
    for label, lessons in (("Existing", current), ("Incoming", additions)):
        if not isinstance(lessons, list):
            raise ValueError(f"{label} lessons must be an array")
        ids, numbers = set(), set()
        for lesson in lessons:
            if not isinstance(lesson, dict) or not isinstance(lesson.get("source"), dict):
                raise ValueError(f"{label} lesson source identity is missing")
            identity = text(lesson.get("id"), f"{label} lesson.id")
            source = lesson["source"]
            if source.get("bookId") != BOOK_ID:
                raise ValueError("Merge requires the original book only; incompatible existing collections are left unchanged")
            number = source.get("questionNumber")
            if type(number) is not int or number < 1 or identity in ids or number in numbers:
                raise ValueError(f"{label} lessons require unique lesson IDs and source question numbers")
            version = lesson.get("version", 1)
            if type(version) is not int or version < 1:
                raise ValueError(f"{label} lesson version must be a positive integer")
            ids.add(identity)
            numbers.add(number)
    current_ids = {lesson["id"]: lesson for lesson in current}
    current_questions = {lesson["source"]["questionNumber"]: lesson["id"] for lesson in current}
    for lesson in additions:
        previous = current_ids.get(lesson["id"])
        number = lesson["source"]["questionNumber"]
        if previous is not None and previous["source"]["questionNumber"] != number:
            raise ValueError("A lesson ID cannot be reassigned to another source question")
        if number in current_questions and current_questions[number] != lesson["id"]:
            raise ValueError("Preserve the existing lesson ID for this source question; a repair must not create a duplicate")
    incoming = {lesson["id"]: lesson for lesson in additions}
    merged = []
    for lesson in current:
        replacement = incoming.pop(lesson["id"], None)
        if replacement is not None:
            if replacement.get("version", 1) < lesson.get("version", 1):
                raise ValueError(f"Refusing a revision downgrade: {lesson['id']}")
            if replacement != lesson and replacement.get("version", 1) == lesson.get("version", 1):
                raise ValueError(f"Changed assembled lesson requires an explicit revision increment: {lesson['id']}")
            merged.append(replacement)
        else:
            merged.append(lesson)
    merged.extend(incoming.values())
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True,
                        help="Reviewed batch draft; other batch paths default to its directory")
    parser.add_argument("--guidance", type=Path,
                        help="Defaults to visual-guidance.json beside --input")
    parser.add_argument("--web-root", type=Path, default=ROOT / "web")
    parser.add_argument("--registry", type=Path, default=ROOT / "taxonomy/registry.latest.json")
    parser.add_argument("--output", type=Path,
                        help="Defaults to lessons-assembled.json beside --input")
    parser.add_argument("--validation-output", type=Path,
                        help="Defaults to technical-validation.json beside --input")
    parser.add_argument("--prepare-audio", type=Path, help="Only write a compatible narration input at this path; do not assemble")
    parser.add_argument("--merge", action="store_true", help="Merge original-book lessons while preserving existing stable source identities")
    parser.add_argument("--app-lessons", type=Path, default=ROOT / "web/data/lessons.json")
    args = parser.parse_args()
    batch_directory = args.input.parent
    args.guidance = args.guidance or batch_directory / "visual-guidance.json"
    args.output = args.output or batch_directory / "lessons-assembled.json"
    args.validation_output = args.validation_output or batch_directory / "technical-validation.json"
    policy = SourcePolicy(ROOT)
    policy.require_book(BOOK_ID)
    protected = [args.input, args.registry, ROOT / "production/source-policy.json",
                 ROOT / "production/books" / f"{BOOK_ID}.json",
                 policy._private_path("questionsFile"), policy._private_path("metadataFile")]
    if args.prepare_audio:
        check_output_paths([args.prepare_audio], protected)
    else:
        check_output_paths([args.output, args.validation_output] + ([args.app_lessons] if args.merge else []),
                           [*protected, args.guidance])
    draft = load_draft(args.input)
    if args.prepare_audio:
        if args.merge:
            parser.error("--prepare-audio does not assemble or merge")
        write(args.prepare_audio, audio_input(draft))
        print(f"Prepared {len(draft['lessons'])} narration inputs: {args.prepare_audio}")
        return
    lessons, validations = assemble(draft, read(args.guidance), args.web_root.resolve(), args.registry.resolve())
    merged = merge_lessons(read(args.app_lessons), lessons) if args.merge else None
    write(args.output, lessons)
    write(args.validation_output, {
        "schemaVersion": 1, "bookId": BOOK_ID, "lessonCount": len(lessons),
        "scope": "Source-bound reviewed content plus technical media, timing, provenance and taxonomy validation; final visual/audio/browser QA and completion remain separate.",
        "lessons": validations, "productionLedgerChanged": False,
        "physicalAndroidTested": False, "humanListeningReviewed": False,
    })
    if merged is not None:
        write(args.app_lessons, merged)
    print(f"Assembled and technically validated {len(lessons)} original-book lessons: {args.output}")
    if merged is not None:
        print(f"Merged original-book collection now contains {len(merged)} lessons with stable source identities.")
    print("No production completion or final visual/browser/device/listening review was asserted by assembly.")


if __name__ == "__main__":
    try:
        main()
    except SourcePolicyError as error:
        raise SystemExit(f"Source policy: {error}")
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise SystemExit(f"Assembly checkpoint: {error}")
