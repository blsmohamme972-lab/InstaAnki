#!/usr/bin/env python3
"""Check the active app catalog against the reviewed original-book policy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

from source_policy import SourcePolicy, SourcePolicyError, validate_publications


ROOT = Path(__file__).resolve().parents[1]
FRESH_RUNTIME_FILES = (
    "index.html", "app.js", "learning.js", "guidance.js", "topic-selection.js",
    "styles.css", "third-party-notices.txt", "data/taxonomy.json",
)
FRESH_DATA_FILES = ("data/books.json", "data/lessons.json", "data/distribution.json")


def check_fresh_file_set(web_root):
    """Reject incomplete or indirect runtimes before reading bundle contents."""
    expected = set(FRESH_RUNTIME_FILES + FRESH_DATA_FILES)
    entries = list(web_root.rglob("*"))
    unsafe = sorted(path.relative_to(web_root).as_posix() for path in entries
                    if path.is_symlink() or (not path.is_file() and not path.is_dir()))
    if unsafe:
        raise SourcePolicyError("Fresh distribution cannot contain symlinks or special files: " + ", ".join(unsafe[:5]))
    actual = {path.relative_to(web_root).as_posix() for path in entries if path.is_file()}
    missing = sorted(expected - actual)
    if missing:
        raise SourcePolicyError("Fresh distribution is missing required regular files: " + ", ".join(missing))
    unexpected = sorted(actual - expected)
    if unexpected:
        raise SourcePolicyError("Fresh distribution contains non-runtime or old media files: " + ", ".join(unexpected[:5]))


def fresh_distribution(repo, policy):
    document = json.loads((Path(repo) / "production/distribution-profiles.json").read_text(encoding="utf-8"))
    marker = document.get("profiles", {}).get("fresh")
    if (document.get("schemaVersion") != 1 or not isinstance(marker, dict)
            or marker.get("schemaVersion") != 1 or marker.get("profile") != "fresh"
            or marker.get("app") != {"packageName": "com.instaanki.fresh", "version": "0.3.0", "versionCode": 4}
            or marker.get("approvedBookId") != policy.book_id
            or type(marker.get("bundledLessonCount")) is not int or marker["bundledLessonCount"] != 0
            or marker.get("preserveProductionHistory") is not True
            or marker.get("newProductionEnabled") is not False
            or policy.policy.get("newProductionEnabled") is not False):
        raise SourcePolicyError("The reviewed empty fresh-distribution profile is missing or invalid")
    return marker


def check_catalog(repo=ROOT, web_root=None, *, profile="standard"):
    repo = Path(repo).resolve()
    web_root = Path(web_root).resolve() if web_root is not None else repo / "web"
    if profile == "fresh":
        check_fresh_file_set(web_root)
    policy = SourcePolicy(repo)
    ledger = policy.ledger()
    books = json.loads((web_root / "data/books.json").read_text(encoding="utf-8"))
    lessons = json.loads((web_root / "data/lessons.json").read_text(encoding="utf-8"))
    validate_publications(books, ledger)
    produced = sorted(q["number"] for q in ledger["questions"] if q.get("status") == "produced")
    if not isinstance(lessons, list) or any(not isinstance(item, dict) for item in lessons):
        raise SourcePolicyError("Active lessons must be a list of lesson records")
    ids = [lesson.get("id") for lesson in lessons]
    if any(not isinstance(identity, str) or not identity for identity in ids) or len(ids) != len(set(ids)):
        raise SourcePolicyError("Active lesson IDs must be present and unique")
    if profile == "fresh":
        expected = fresh_distribution(repo, policy)
        marker = json.loads((web_root / "data/distribution.json").read_text(encoding="utf-8"))
        if marker != expected:
            raise SourcePolicyError("Fresh bundle must carry the exact reviewed distribution marker")
        if '<meta name="instaanki-distribution" content="fresh">' not in (web_root / "index.html").read_text(encoding="utf-8"):
            raise SourcePolicyError("Fresh runtime must load the reviewed distribution identity")
        if lessons:
            raise SourcePolicyError("The fresh initial distribution must contain zero bundled lessons")
        if any(book.get("productionPaused") is not True or book.get("coverUrl") for book in books):
            raise SourcePolicyError("Fresh publication metadata must keep production paused and omit cover media")
    elif profile == "standard":
        if (web_root / "data/distribution.json").exists():
            raise SourcePolicyError("An explicit fresh distribution requires the fresh build profile")
        policy.validate_pack(lessons, web_root)
    else:
        raise SourcePolicyError("Unknown distribution profile; use standard or the reviewed fresh distribution")
    return {"bookId": policy.book_id, "activePublications": len(books),
            "activeLessons": len(lessons), "producedQuestions": len(produced),
            "totalQuestions": ledger["totalQuestions"], "distributionProfile": profile}


def prepare_fresh_web(repo, source_web, destination):
    """Prepare only the explicitly authorized empty app, without reading media.

    Canonical lessons and their production ledger stay unchanged. This helper is
    not a content-pack validator and cannot approve an empty normal lesson ZIP.
    """
    repo, source_web, destination = map(lambda path: Path(path).resolve(), (repo, source_web, destination))
    if (destination == repo or repo.is_relative_to(destination)
            or destination == source_web or source_web.is_relative_to(destination)
            or destination.is_relative_to(source_web)):
        raise SourcePolicyError("Fresh staging must be separate from the repository and canonical web inputs")
    policy = SourcePolicy(repo)
    marker = fresh_distribution(repo, policy)
    books = json.loads((source_web / "data/books.json").read_text(encoding="utf-8"))
    validate_publications(books, policy.ledger())
    for book in books:
        book.pop("coverUrl", None)
        book["productionPaused"] = True
    if destination.exists() and any(destination.iterdir()):
        # Never erase an unrelated directory or a user's additions to a stage.
        check_catalog(repo, destination, profile="fresh")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fresh-web-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "web"
        stage.mkdir()
        for name in FRESH_RUNTIME_FILES:
            source = source_web / name
            if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(source_web):
                raise SourcePolicyError(f"Fresh runtime input is missing or unsafe: {name}")
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        index = stage / "index.html"
        html = index.read_text(encoding="utf-8")
        if '<meta name="instaanki-distribution" content="standard">' not in html:
            raise SourcePolicyError("Canonical runtime is missing its distribution selector")
        index.write_text(html.replace('<meta name="instaanki-distribution" content="standard">',
                                      '<meta name="instaanki-distribution" content="fresh">'), encoding="utf-8")
        (stage / "data/books.json").write_text(json.dumps(books, indent=2) + "\n", encoding="utf-8")
        (stage / "data/lessons.json").write_text("[]\n", encoding="utf-8")
        (stage / "data/distribution.json").write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
        result = check_catalog(repo, stage, profile="fresh")
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(stage), str(destination))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-root", type=Path, default=ROOT / "web",
                        help="Actual web bundle to validate against this repository's source policy")
    parser.add_argument("--profile", choices=("standard", "fresh"), default="standard")
    parser.add_argument("--prepare-fresh", type=Path, metavar="DESTINATION",
                        help="Stage the reviewed empty initial distribution from runtime inputs")
    args = parser.parse_args()
    try:
        if args.prepare_fresh:
            if args.profile != "fresh":
                raise SourcePolicyError("Fresh preparation requires the explicit fresh profile")
            result = prepare_fresh_web(ROOT, args.web_root, args.prepare_fresh)
        else:
            result = check_catalog(web_root=args.web_root, profile=args.profile)
    except (SourcePolicyError, OSError, ValueError, TypeError, KeyError) as error:
        print(f"Source scope check failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
