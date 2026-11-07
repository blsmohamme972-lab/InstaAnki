#!/usr/bin/env python3
"""Validate a private mnemonic-prompt review before emitting a generator input.

This command does not browse, approve a review, generate an image, or intercept
external image tools. The authoring agent must inspect the actual public
references and perform the recorded review before using --emit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import unquote, urlsplit

from source_policy import SourcePolicy, SourcePolicyError, canonical_hash, content_fingerprints


ROOT = Path(__file__).resolve().parents[1]
STYLE_VERSION = "2.0.0"
SPEC_FILES = ("docs/visual-production-rules.md", "docs/mnemonic-image-prompt.md")
PROVIDERS = {"Pixorize": "pixorize.com", "Picmonic": "picmonic.com", "Sketchy": "sketchy.com"}
CHECKS = (
    "sourceAligned", "allThreeReferencesVisuallyInspected", "symbolMeaningsExplicit",
    "storyAndInteractionsClear", "originalComposition", "twoDimensionalCartoon",
    "phoneReadable", "noDecorativeFiller", "locusSupportsStory", "exactOverlaysSeparated",
)
EXAMPLE_KINDS = {"image", "video", "page-artwork"}
INSPECTION_SCOPES = {"complete-scene", "video-scene", "character-example"}


class PromptReviewError(ValueError):
    pass


def required_text(value, label, *, words=1):
    if (not isinstance(value, str) or len(value.strip().split()) < words
            or re.search(r"\b(?:TODO|TBD|CHANGEME|PLACEHOLDER)\b|\{\{[^}]+\}\}", value, re.I)):
        raise PromptReviewError(f"{label} needs meaningful completed text, not a placeholder")
    return value


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def byte_hash(value):
    return hashlib.sha256(value).hexdigest()


def timestamp(value, label):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("timezone missing")
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise PromptReviewError(f"{label} requires an actual timezone-aware ISO timestamp") from None


def url(value, label):
    required_text(value, label)
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        raise PromptReviewError(f"{label} is not a valid public HTTPS URL") from None
    if (parsed.scheme != "https" or not host or parsed.username or parsed.password
            or port not in (None, 443) or "\\" in value or any(c.isspace() for c in value)):
        raise PromptReviewError(f"{label} must be a public HTTPS URL without credentials")
    for domain in PROVIDERS.values():
        if domain in host and host != domain and not host.endswith("." + domain):
            raise PromptReviewError(f"{label} uses a misleading provider hostname")
    return parsed, host


def validate_art(lesson):
    required_text(lesson.get("imagePrompt"), "imagePrompt", words=8)
    symbols = lesson.get("mnemonicSymbols")
    if not isinstance(symbols, list) or not symbols or any(not isinstance(x, dict) for x in symbols):
        raise PromptReviewError("mnemonicSymbols must explicitly map each visible symbol to its meaning")
    meanings = {}
    for symbol in symbols:
        name = required_text(symbol.get("symbol"), "mnemonicSymbols.symbol")
        meaning = required_text(symbol.get("meaning"), "mnemonicSymbols.meaning")
        if name in meanings:
            raise PromptReviewError("mnemonicSymbols must use unique symbol names")
        meanings[name] = meaning
    brief = lesson.get("artBrief")
    if (not isinstance(brief, dict) or type(brief.get("schemaVersion")) is not int
            or brief["schemaVersion"] != 1 or brief.get("rendering") != "2d-mnemonic-cartoon"):
        raise PromptReviewError("artBrief requires schemaVersion 1 and rendering='2d-mnemonic-cartoon'")
    for field in ("objective", "story", "styleNotes", "composition", "locusUse", "overlayPlan"):
        required_text(brief.get(field), "artBrief." + field)
    actions = brief.get("symbolActions")
    if not isinstance(actions, list) or len(actions) != len(symbols):
        raise PromptReviewError("artBrief.symbolActions must cover every mnemonic symbol exactly once")
    covered = set()
    for action in actions:
        if not isinstance(action, dict):
            raise PromptReviewError("artBrief.symbolActions entries must be objects")
        for field in ("symbol", "meaning", "action", "recallCue", "position", "narrationCue"):
            required_text(action.get(field), "artBrief.symbolActions." + field)
        if (action["symbol"] in covered or meanings.get(action["symbol"]) != action["meaning"]):
            raise PromptReviewError("artBrief symbol names/meanings must exactly match mnemonicSymbols")
        covered.add(action["symbol"])
    if covered != set(meanings):
        raise PromptReviewError("artBrief.symbolActions omitted a mnemonic symbol")


def prepare_request(repo, input_path, lesson_id):
    """Calculate the current request binding; never create a review assertion."""
    repo = Path(repo)
    document = read_json(input_path)
    if not isinstance(document, dict) or not isinstance(document.get("lessons"), list):
        raise PromptReviewError("Input must be a source-bound draft with a lessons array")
    lessons = document["lessons"]
    ids = [lesson.get("id") for lesson in lessons if isinstance(lesson, dict)]
    if len(ids) != len(lessons) or any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
        raise PromptReviewError("Draft lessons require unique, nonempty identities")
    matches = [lesson for lesson in lessons if lesson["id"] == lesson_id]
    if len(matches) != 1:
        raise PromptReviewError("Select exactly one existing lesson ID from this draft")
    lesson = matches[0]
    policy = SourcePolicy(repo)
    evidence = policy.validate_authoring(document, [lesson])[lesson_id]
    ledger = policy.ledger()
    question = next(q for q in ledger["questions"] if q["number"] == evidence["questionNumber"])
    validate_art(lesson)
    documents = {}
    for relative in SPEC_FILES:
        path = repo / relative
        if not path.is_file() or path.is_symlink():
            raise PromptReviewError(f"Required style specification is missing or indirect: {relative}")
        content = path.read_bytes()
        if STYLE_VERSION not in content.decode("utf-8"):
            raise PromptReviewError(f"{relative} must declare style specification {STYLE_VERSION}")
        documents[relative] = byte_hash(content)
    binding = {
        "schemaVersion": 1, "lessonId": lesson_id, "bookId": policy.book_id,
        "questionNumber": evidence["questionNumber"], "imagePrompt": lesson["imagePrompt"],
        "artBrief": lesson["artBrief"], "mnemonicSymbols": lesson["mnemonicSymbols"],
        "locus": lesson["locus"], "sourceEvidence": evidence,
        "sourceContentFingerprints": content_fingerprints(lesson, authoring=True),
        "sourceReview": question["sourceReview"],
        "styleSpec": {"version": STYLE_VERSION, "documents": documents},
    }
    return {"binding": binding, "requestSha256": canonical_hash(binding),
            "promptSha256": byte_hash(lesson["imagePrompt"].encode("utf-8"))}


def fingerprint_report(request):
    binding = request["binding"]
    return {"schemaVersion": 1, "lessonId": binding["lessonId"],
            "requestSha256": request["requestSha256"], "promptSha256": request["promptSha256"],
            "styleSpec": binding["styleSpec"], "reviewStatus": "not-evaluated",
            "approved": False, "imageGenerated": False}


def validate_review(request, review, *, now=None):
    """Check recorded evidence and exact bindings, not the truth of visual judgment."""
    binding = request["binding"]
    if (not isinstance(review, dict) or type(review.get("schemaVersion")) is not int
            or review["schemaVersion"] != 1 or review.get("decision") != "approved"):
        raise PromptReviewError("A separately performed, explicitly approved prompt review is required")
    if review.get("lessonId") != binding["lessonId"] or review.get("requestSha256") != request["requestSha256"]:
        raise PromptReviewError("Prompt review is stale or belongs to another request; review the changed prompt and its bindings")
    required_text(review.get("reviewer"), "reviewer")
    required_text(review.get("notes"), "review notes", words=8)
    reviewed = timestamp(review.get("reviewedAt"), "reviewedAt")
    now = now or datetime.now(timezone.utc)
    if reviewed > now:
        raise PromptReviewError("reviewedAt cannot claim a future review")
    if reviewed < timestamp(binding["sourceReview"]["reviewedAt"], "sourceReview.reviewedAt"):
        raise PromptReviewError("Prompt review cannot predate its bound source-content review")
    checks = review.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(CHECKS) or any(checks[name] is not True for name in CHECKS):
        raise PromptReviewError("Every required prompt-review checkpoint must be explicitly true after actual review")
    references = review.get("references")
    if not isinstance(references, list) or len(references) != len(PROVIDERS):
        raise PromptReviewError("Inspect one specific public visual example from each of the three required providers")
    seen = set()
    for ref in references:
        if not isinstance(ref, dict) or ref.get("provider") not in PROVIDERS or ref["provider"] in seen:
            raise PromptReviewError("Reference inspections must name Pixorize, Picmonic and Sketchy exactly once")
        provider = ref["provider"]
        seen.add(provider)
        page, host = url(ref.get("pageUrl"), provider + ".pageUrl")
        domain = PROVIDERS[provider]
        if host != domain and not host.endswith("." + domain):
            raise PromptReviewError(f"{provider}.pageUrl must belong to that provider's official website")
        example, example_host = url(ref.get("exampleUrl"), provider + ".exampleUrl")
        # CDN/video hosts can differ from the provider only with an explicit
        # record of the link/embedded artwork on that provider's official page.
        if ref.get("linkedFromPage") != ref["pageUrl"]:
            raise PromptReviewError(f"{provider} example requires exact official-page grounding")
        required_text(ref.get("linkEvidence"), provider + ".linkEvidence", words=8)
        if any(example_host == other or example_host.endswith("." + other)
               for other in PROVIDERS.values() if other != domain):
            raise PromptReviewError(f"{provider} example belongs to a different required provider")
        if not unquote(example.path).strip("/"):
            raise PromptReviewError(f"{provider} homepage-only evidence is insufficient; inspect an actual visual example")
        if (ref.get("exampleKind") not in EXAMPLE_KINDS
                or ref.get("inspectionScope") not in INSPECTION_SCOPES):
            raise PromptReviewError(f"{provider} needs inspected scene/character evidence; thumbnails alone do not qualify")
        if ref.get("access") != "public" or ref.get("inspectionStatus") != "inspected":
            raise PromptReviewError(f"{provider} reference inspection is missing, blocked or not public")
        inspected = timestamp(ref.get("inspectedAt"), provider + ".inspectedAt")
        if inspected > reviewed:
            raise PromptReviewError(f"{provider} inspection must precede or coincide with the recorded review")
        required_text(ref.get("observations"), provider + ".observations", words=8)
        required_text(ref.get("appliedMethod"), provider + ".appliedMethod", words=8)
    return {"schemaVersion": 1, "kind": "reviewed-image-prompt", "lessonId": binding["lessonId"],
            "bookId": binding["bookId"], "questionNumber": binding["questionNumber"],
            "requestSha256": request["requestSha256"], "promptSha256": request["promptSha256"],
            "styleSpec": binding["styleSpec"], "reviewSha256": canonical_hash(review),
            "sourceReviewSha256": canonical_hash(binding["sourceReview"]),
            "reviewer": review["reviewer"], "reviewedAt": review["reviewedAt"],
            "referenceProviders": list(PROVIDERS), "validatedAt": now.isoformat(),
            "imageGenerated": False,
            "scope": "Recorded source/prompt review and exact bindings validated. Site inspection and visual judgment remain the reviewer's assertions; no image was generated."}


def write_new_output(path, bundle):
    """Publish a complete new file atomically, without overwriting prior work."""
    data = (json.dumps(bundle, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise PromptReviewError("Output already exists; preserve it and choose a new private output path")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".image-prompt-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # Atomic and exclusive: an existing path is never replaced.
    finally:
        temporary.unlink(missing_ok=True)


def emit(repo, input_path, lesson_id, review_path, output_path):
    request = prepare_request(repo, input_path, lesson_id)
    review = read_json(review_path)
    receipt = validate_review(request, review)
    if (prepare_request(repo, input_path, lesson_id)["requestSha256"] != request["requestSha256"]
            or canonical_hash(read_json(review_path)) != receipt["reviewSha256"]):
        raise PromptReviewError("Inputs changed during preflight; no prompt was emitted")
    bundle = {"prompt": request["binding"]["imagePrompt"], "receipt": receipt}
    write_new_output(output_path, bundle)
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Private source-reviewed lesson draft")
    parser.add_argument("--lesson", required=True, help="One exact draft lesson ID")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--fingerprint", action="store_true", help="Calculate bindings only; no review approval or output file")
    modes.add_argument("--emit", action="store_true", help="Emit after validation (the default mode)")
    parser.add_argument("--review", type=Path, help="Private record of actual prompt and reference review")
    parser.add_argument("--output", type=Path, help="New private JSON file containing only prompt and receipt")
    args = parser.parse_args()
    if args.fingerprint:
        if args.review or args.output:
            parser.error("--fingerprint cannot emit a file or claim validation of --review")
        print(json.dumps(fingerprint_report(prepare_request(ROOT, args.input, args.lesson)), indent=2))
        return
    if not args.review or not args.output:
        parser.error("Emission requires both --review and --output; use --fingerprint to calculate an unapproved binding")
    bundle = emit(ROOT, args.input, args.lesson, args.review, args.output)
    print(json.dumps({"output": str(args.output), "lessonId": args.lesson,
                      "requestSha256": bundle["receipt"]["requestSha256"], "imageGenerated": False}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, KeyError, SourcePolicyError) as error:
        raise SystemExit(f"Image-prompt checkpoint: {error}")
