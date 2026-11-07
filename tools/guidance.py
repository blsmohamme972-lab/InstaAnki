"""Validate image-space guidance against the final audio and exact asset bytes.

Phrase boundaries are synthesized sample boundaries, never proportional text
estimates. Changing a recording or image invalidates the reviewed annotation.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def asset_file(root, value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Guidance asset must be a local relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in (".", "..") for part in path.parts) or ":" in value:
        raise ValueError(f"Unsafe guidance asset path: {value}")
    root = Path(root).resolve()
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"Guidance asset is missing: {value}")
    return resolved


def finite(value, label, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f"{label} is out of range")
    return value


def validate_targets(plan, web_root):
    if plan.get("schemaVersion", 1) != 1:
        raise ValueError("Unsupported visual guidance schema")
    images = plan.get("images")
    targets = plan.get("targets")
    if not isinstance(images, dict) or not images or not isinstance(targets, dict) or not targets:
        raise ValueError("Guidance requires image metadata and named targets")
    for name, image in images.items():
        path = asset_file(web_root, name)
        if not isinstance(image, dict) or not re.fullmatch(r"[0-9a-f]{64}", image.get("sha256", "")):
            raise ValueError(f"Guidance image requires a SHA-256: {name}")
        if file_hash(path) != image["sha256"]:
            raise ValueError(f"Guidance image changed; review its targets again: {name}")
        for dim in ("width", "height"):
            size = image.get(dim)
            if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
                raise ValueError(f"Guidance image {dim} must be a positive integer: {name}")
        # PIL is an optional authoring dependency. The pinned file hash is always
        # checked; dimensions are checked too when the decoder is installed.
        try:
            from PIL import Image
        except ImportError:
            pass
        else:
            with Image.open(path) as decoded:
                if decoded.size != (image["width"], image["height"]):
                    raise ValueError(f"Guidance image dimensions differ: {name}")
    for name, target in targets.items():
        if not isinstance(name, str) or not name or not isinstance(target, dict):
            raise ValueError("Guidance target IDs must be nonempty strings")
        if target.get("image") not in images:
            raise ValueError(f"Target references an unreviewed image: {name}")
        if not isinstance(target.get("label"), str) or not target["label"].strip():
            raise ValueError(f"Target needs a meaningful label: {name}")
        for field in ("x", "y"):
            finite(target.get(field), f"{name}.{field}", 0, 1)
        for field in ("rx", "ry"):
            finite(target.get(field), f"{name}.{field}", 0.001, 0.5)
        spot_x = finite(target.get("spotX", target["x"]), f"{name}.spotX", 0, 1)
        spot_y = finite(target.get("spotY", target["y"]), f"{name}.spotY", 0, 1)
        if not (target["rx"] <= spot_x <= 1-target["rx"] and
                target["ry"] <= spot_y <= 1-target["ry"]):
            raise ValueError(f"Target region lies outside its image: {name}")
        if ((target["x"]-spot_x)/target["rx"])**2 + ((target["y"]-spot_y)/target["ry"])**2 > 1 + 1e-8:
            raise ValueError(f"Pointer tip lies outside the spotlight region: {name}")
        finite(target.get("zoom", 1), f"{name}.zoom", 1, 1.25)
    outro_target = plan.get("outroTargetId")
    if outro_target is not None and outro_target not in targets:
        raise ValueError("Outro references an unknown target")
    return plan


def validate_plan(plan, source_scenes, web_root):
    validate_targets(plan, web_root)
    planned = plan.get("scenes")
    if not isinstance(planned, list) or len(planned) != len(source_scenes):
        raise ValueError("Guidance plan and source must have the same scene count")
    scene_ids, phrase_ids = set(), set()
    for scene, original in zip(planned, source_scenes):
        scene_id = scene.get("id")
        if scene_id != original.get("id") or scene_id in scene_ids:
            raise ValueError("Guidance plan scene IDs/order differ from source")
        scene_ids.add(scene_id)
        phrases = scene.get("phrases")
        if not isinstance(phrases, list) or not phrases:
            raise ValueError(f"Scene has no measured narration phrases: {scene_id}")
        expected = original.get("spoken_text", original.get("voice_text", original.get("transcript")))
        if " ".join(phrase.get("text", "") for phrase in phrases) != expected:
            raise ValueError(f"Guidance phrases must preserve complete source narration: {scene_id}")
        for phrase in phrases:
            phrase_id = phrase.get("id")
            if not isinstance(phrase_id, str) or not phrase_id or phrase_id in phrase_ids:
                raise ValueError("Guidance phrase IDs must be unique")
            phrase_ids.add(phrase_id)
            if not phrase.get("text", "").strip():
                raise ValueError("Guidance phrase text cannot be empty")
            if phrase.get("targetId") is not None and phrase["targetId"] not in plan["targets"]:
                raise ValueError(f"Phrase references an unknown target: {phrase_id}")
    return plan


def assemble_guidance(plan, timing, scenes, audio_url, web_root):
    if timing.get("visualGuidancePlanSha256") != canonical_hash(plan):
        raise ValueError("Guidance plan changed after audio was rendered; regenerate timing")
    guidance = {"schemaVersion": 1, "audioSha256": timing["audioSha256"],
                "images": plan["images"], "targets": plan["targets"],
                "cues": timing["cues"]}
    if plan.get("outroTargetId") is not None:
        guidance["outroTargetId"] = plan["outroTargetId"]
    lesson = {"audioUrl": audio_url, "scenes": scenes, "visualGuidance": guidance,
              "realImageOutro": timing["realImageOutro"]}
    verify_guidance(lesson, timing, web_root)
    return guidance


def verify_guidance(lesson, timing, web_root):
    """Reject stale media, disconnected cues, or non-measured cue timestamps."""
    audio_hash = file_hash(asset_file(web_root, lesson["audioUrl"]))
    if timing.get("audioSha256") != audio_hash:
        raise ValueError("Audio bytes changed after timing was recorded; regenerate alignment")
    guidance = lesson.get("visualGuidance")
    if not isinstance(guidance, dict) or guidance.get("schemaVersion") != 1:
        raise ValueError("Lesson requires visualGuidance schemaVersion 1")
    if guidance.get("audioSha256") != audio_hash:
        raise ValueError("Guidance was authored for different audio bytes")
    validate_targets(guidance, web_root)
    outro_target = guidance.get("outroTargetId")
    if outro_target is not None:
        outro_image = timing.get("realImageOutro", {}).get("imagePath", "").lstrip("/")
        if guidance["targets"][outro_target]["image"] != outro_image:
            raise ValueError("Outro target is not on the displayed real image")
    cues = guidance.get("cues")
    if not isinstance(cues, list) or not cues or cues != timing.get("cues"):
        raise ValueError("Lesson guidance cues must match the measured timing companion")
    sample_rate = finite(timing.get("sampleRate"), "sampleRate", 1)
    by_scene = {scene["id"]: scene for scene in lesson["scenes"]}
    ordered_ids = [scene["id"] for scene in lesson["scenes"]]
    previous_end = 0
    ids, transcripts, encountered = set(), {}, []
    for cue in cues:
        cue_id = cue.get("id")
        if not isinstance(cue_id, str) or not cue_id or cue_id in ids:
            raise ValueError("Measured cue IDs must be unique")
        ids.add(cue_id)
        scene_id = cue.get("sceneId")
        if scene_id not in by_scene:
            raise ValueError("Measured cue points to a missing scene")
        if not encountered or encountered[-1] != scene_id:
            encountered.append(scene_id)
        scene = by_scene[scene_id]
        for field in ("start", "end", "voiceStart", "voiceEnd"):
            finite(cue.get(field), f"{cue_id}.{field}", 0)
            sample = cue.get(field + "Sample")
            if isinstance(sample, bool) or not isinstance(sample, int) or sample < 0:
                raise ValueError(f"{cue_id}.{field} must have an exact sample boundary")
            if abs(cue[field] - sample / sample_rate) > 1e-8:
                raise ValueError(f"{cue_id}.{field} is not its measured sample boundary")
        if abs(cue["start"] - previous_end) > 1e-8:
            raise ValueError("Measured guidance cues have a gap or overlap")
        if not (cue["start"] <= cue["voiceStart"] < cue["voiceEnd"] <= cue["end"]):
            raise ValueError("Measured guidance voice interval is invalid")
        if cue["start"] < scene["start"] - 1e-8 or cue["end"] > scene["end"] + 1e-8:
            raise ValueError("Measured cue lies outside its scene")
        previous_end = cue["end"]
        target_id = cue.get("targetId")
        if target_id is not None:
            target = guidance["targets"].get(target_id)
            if not target or target["image"] != scene["image"]:
                raise ValueError(f"Cue target is not on the displayed image: {cue_id}")
            if scene.get("kind") == "clinical" and target.get("zoom", 1) != 1:
                raise ValueError("Clinical images must remain uncropped")
        if not isinstance(cue.get("text"), str) or not cue["text"].strip():
            raise ValueError("Measured cue needs narration text")
        transcripts.setdefault(scene_id, []).append(cue["text"])
    if encountered != ordered_ids:
        raise ValueError("Measured cue scene order differs from lesson order")
    for scene in lesson["scenes"]:
        measured = next((item for item in timing["scenes"] if item["id"] == scene["id"]), {})
        if " ".join(transcripts.get(scene["id"], [])) != measured.get("spokenText", scene["transcript"]):
            raise ValueError("Measured cues do not cover the exact narration script")
    if abs(previous_end - lesson["realImageOutro"]["start"]) > 1e-8:
        raise ValueError("Measured cues do not cover the whole narration")
    return {"cueCount": len(cues), "targetCount": len(guidance["targets"]),
            "audioSha256": audio_hash, "alignment": "independently-synthesized-phrase-samples"}
