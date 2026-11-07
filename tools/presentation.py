"""Validate display-only endings against existing narrated phrase boundaries."""
import math


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite numeric seconds")
    return float(value)


def validate_presentation(lesson):
    presentation = lesson.get("presentation")
    if presentation is None:
        return  # Released legacy lessons remain readable.
    if not isinstance(presentation, dict) or presentation.get("schemaVersion") != 1:
        raise ValueError("Unsupported lesson presentation schema")
    duration = number(lesson.get("durationSeconds"), "durationSeconds")
    end = number(presentation.get("effectiveEndSeconds"), "effectiveEndSeconds")
    narration_end = number(presentation.get("narrationEndSeconds"), "narrationEndSeconds")
    cues = lesson.get("visualGuidance", {}).get("cues", [])
    phrases = {cue.get("id"): cue for cue in cues}
    if not phrases or len(phrases) != len(cues):
        raise ValueError("Presentation requires unique existing narration phrases")
    spoken_end = max(number(cue.get("voiceEnd"), "voiceEnd") for cue in cues)
    if not 0 < end <= duration or abs(end - narration_end) > .001 or abs(end - spoken_end) > .001:
        raise ValueError("Presentation must end at the last existing narrated phrase, without a silent hold")
    gallery, recap = presentation.get("clinicalGallery"), presentation.get("recap")
    if not isinstance(gallery, dict) or not isinstance(recap, dict):
        raise ValueError("Presentation requires a clinical gallery and narrated recap")
    for section in (gallery, recap):
        start = number(section.get("startSeconds"), "ending startSeconds")
        stop = number(section.get("endSeconds"), "ending endSeconds")
        if not 0 <= start < stop or abs(stop - end) > .001:
            raise ValueError("Gallery and recap must finish with the narration")
    if abs(gallery["startSeconds"] - recap["startSeconds"]) > .001:
        raise ValueError("Gallery and recap must share the narrated ending")
    images = gallery.get("images")
    if not isinstance(images, list) or not 3 <= len(images) <= 6:
        raise ValueError("Clinical gallery requires three to six images")
    registered = {image["url"]: image for image in lesson.get("realImages", [])}
    paths = [image.get("url") for image in images]
    if len(set(paths)) != len(paths):
        raise ValueError("Clinical gallery images must be distinct")
    for image in images:
        if image.get("url") not in registered or image != registered[image["url"]]:
            raise ValueError("Gallery image must match its packaged realImages provenance")
        if not all(isinstance(image.get(key), str) and image[key].strip()
                   for key in ("title", "caption", "sourceUrl", "license", "attribution", "sha256")):
            raise ValueError("Clinical image requires source, license, caption and exact asset hash")
    nodes = recap.get("nodes", [])
    ids = {node.get("id") for node in nodes}
    if not 2 <= len(nodes) <= 6 or len(ids) != len(nodes) or not all(
            isinstance(node.get("id"), str) and node["id"] and isinstance(node.get("label"), str) and node["label"] for node in nodes):
        raise ValueError("Recap requires two to six uniquely named nodes")
    for edge in recap.get("edges", []):
        if edge.get("from") not in ids or edge.get("to") not in ids or edge["from"] == edge["to"]:
            raise ValueError("Recap edge refers to an invalid node")
    bound_nodes = set()
    previous_end = recap["startSeconds"]
    for binding in recap.get("cueBindings", []):
        phrase = phrases.get(binding.get("phraseId"))
        if phrase is None or binding.get("nodeId") not in ids:
            raise ValueError("Recap cue must reference an existing phrase and node")
        start = number(binding.get("startSeconds"), "recap cue start")
        stop = number(binding.get("endSeconds"), "recap cue end")
        if (start < previous_end - .001 or stop <= start or stop > end + .001
                or abs(start - phrase["voiceStart"]) > .001 or abs(stop - phrase["voiceEnd"]) > .001):
            raise ValueError("Recap animation must use exact existing narrated phrase boundaries")
        previous_end = stop
        bound_nodes.add(binding["nodeId"])
    if bound_nodes != ids:
        raise ValueError("Every recap node requires a narration cue")
