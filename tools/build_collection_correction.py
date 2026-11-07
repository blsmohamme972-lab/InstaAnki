#!/usr/bin/env python3
"""Build the one supported, reversible correction for the unintended 20-lesson pack.

This is deliberately separate from lesson production. It adds no lessons, books,
source claims, or learning-state files. InstaAnki 0.1.1 replaces a content folder
by pack ID; after a full app restart, its bundled Raja collection remains.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


TARGET_PACK_ID = "instaanki-medical-foundations-2026-v1"
ALLOWED_TARGET_PACK_IDS = frozenset({TARGET_PACK_ID})
ARCHIVED_BOOK_ID = "instaanki-open-medical-foundations-2026"
ZIP_TIMESTAMP = (2026, 11, 7, 0, 0, 0)

INSTRUCTIONS = """InstaAnki: return to the original Raja collection

Purpose
This data-only correction replaces only the installed content package
instaanki-medical-foundations-2026-v1 with an empty package. It removes that
package's 20 independent-reference lessons and publication from the active
collection after a full app restart. It does not convert those lessons into
Raja questions or add any new book lessons.

Apply on InstaAnki 0.1.1
1. Keep the original 20-lesson ZIP if you want to reverse this correction.
2. Settings > Export learning backup saves an additional copy of your progress.
3. Settings > Import lesson package > choose this ZIP. Do not extract it.
4. Wait for import to finish, close InstaAnki from Android's Recent apps screen,
   and reopen it. Version 0.1.1 keeps its old content list in memory until a
   complete restart, so the second publication can remain visible before this.
5. An app with the original bundled collection then shows the Raja publication
   with 3 of 200 lessons produced. Other independently installed packs, if any,
   are unaffected. No source question is claimed as newly completed.

Learning history
This ZIP contains no learning backup, database, preferences, executable code,
or commands. Saved reviews, FSRS schedules, likes and private notes remain in
the app's separate learning storage. Records for inactive lessons are retained;
historical totals in Insights may still include them. Do not clear app storage
or uninstall the app to apply this correction.

Reverse
Import the unchanged original InstaAnki-20-Lesson-Pack.zip and fully restart
the app. Its original stable lesson IDs reconnect to the retained records.

Scope and limits
This corrects the specifically named imported package. It cannot remove lessons
baked into a different APK or another package ID. Automated checks exercise the
actual Java importer and browser application; physical-phone confirmation is
still needed after the user imports it.
"""


def correction_files(target_pack_id: str = TARGET_PACK_ID) -> dict[str, bytes]:
    if target_pack_id not in ALLOWED_TARGET_PACK_IDS:
        raise ValueError("Correction is restricted to the known unintended reference pack ID.")
    payload = {"lessons.json": b"[]\n", "README.txt": INSTRUCTIONS.encode("utf-8")}
    manifest = {
        "schemaVersion": 1,
        "id": target_pack_id,
        "packId": target_pack_id,
        "version": "1.0.1",
        "title": "Restore the original Raja collection",
        "type": "collection-correction",
        "lessonsFile": "lessons.json",
        "lessonCount": 0,
        "books": [],
        "notes": "Replaces only the unintended reference pack with no active lessons or books. Fully close and reopen InstaAnki 0.1.1 after import. Learning records are retained; re-import the original pack to reverse.",
        "correction": {
            "action": "deactivate-imported-collection",
            "replacesPackId": target_pack_id,
            "archivedBookId": ARCHIVED_BOOK_ID,
            "requiresAppRestart": True,
            "learningStateFilesIncluded": False,
            "reverseByImporting": "InstaAnki-20-Lesson-Pack.zip",
        },
        "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()},
    }
    return {"manifest.json": (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), **payload}


def build_correction(output: Path, target_pack_id: str = TARGET_PACK_ID) -> dict:
    files = correction_files(target_pack_id)
    output = Path(output)
    if output.suffix.lower() != ".zip":
        raise ValueError("Correction output must be a .zip file.")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental replacement of an original archive.
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            archive.writestr(info, data)
    raw = output.read_bytes()
    return {
        "file": str(output.resolve()), "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "targetPackId": target_pack_id, "lessonCount": 0, "bookCount": 0,
        "requiresAppRestart": True, "zipCompression": "STORED",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-pack-id", choices=sorted(ALLOWED_TARGET_PACK_IDS), default=TARGET_PACK_ID)
    args = parser.parse_args()
    print(json.dumps(build_correction(args.output, args.target_pack_id), indent=2))


if __name__ == "__main__":
    main()
