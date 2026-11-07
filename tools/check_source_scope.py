#!/usr/bin/env python3
"""Check the active app catalog against the reviewed original-book policy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from source_policy import SourcePolicy, SourcePolicyError, validate_publications


ROOT = Path(__file__).resolve().parents[1]


def check_catalog(repo=ROOT, web_root=None):
    repo = Path(repo).resolve()
    web_root = Path(web_root).resolve() if web_root is not None else repo / "web"
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
    policy.validate_pack(lessons, web_root)
    return {"bookId": policy.book_id, "activePublications": len(books),
            "activeLessons": len(lessons), "producedQuestions": len(produced),
            "totalQuestions": ledger["totalQuestions"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-root", type=Path, default=ROOT / "web",
                        help="Actual web bundle to validate against this repository's source policy")
    args = parser.parse_args()
    try:
        result = check_catalog(web_root=args.web_root)
    except (SourcePolicyError, OSError, ValueError, TypeError, KeyError) as error:
        print(f"Source scope check failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
