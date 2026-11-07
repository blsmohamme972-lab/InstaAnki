#!/usr/bin/env python3
"""Export, inspect, or restore a private source ZIP without an encryption key.

Restoration checks the expected book identity, all manifest checksums and source
question identities before writing. It never writes a production ledger.
Requires cryptography, as used by the existing source_vault module.
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from source_vault import PROJECT, atomic_write, build_archive, digest, verify_archive


def inspect_archive(data, expected_book=None):
    manifest = verify_archive(data)
    book = manifest.get("bookId")
    if not isinstance(book, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", book):
        raise ValueError("Invalid source book identity")
    if expected_book is not None and book != expected_book:
        raise ValueError(f"Wrong book: archive contains {book}; requested {expected_book}. Question numbers are not interchangeable.")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        metadata = json.loads(archive.read("private-content/book-metadata.json"))
        questions = json.loads(archive.read("private-content/questions.json"))
    if metadata.get("id", metadata.get("book_id")) != book:
        raise ValueError("Source metadata and archive book identity differ")
    count = manifest.get("questionCount")
    if (not isinstance(count, int) or isinstance(count, bool) or count < 1
            or not isinstance(questions, list) or len(questions) != count
            or metadata.get("question_count") != count):
        raise ValueError("Source question counts do not match")
    identities = set()
    numbers = set()
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("Each source question must be an object")
        number = question.get("source_question_number")
        identity = question.get("id")
        if (not isinstance(number, int) or isinstance(number, bool)
                or number < 1 or number in numbers
                or identity != f"{book}-q{number:03d}" or identity in identities):
            raise ValueError("Source question numbers/identities are missing, duplicated or assigned to a different book")
        numbers.add(number)
        identities.add(identity)
    if numbers != set(range(1, count + 1)):
        raise ValueError("The source question sequence is incomplete")
    return manifest


def restore(data, expected_book, destination):
    manifest = inspect_archive(data, expected_book)
    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError("Source destination cannot be a symbolic link")
    destination = destination.absolute()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        payload = {Path(item["path"]).relative_to("private-content"): archive.read(item["path"])
                   for item in manifest["files"]}
    if destination.exists():
        if not destination.is_dir():
            raise ValueError("Source destination is not a directory")
        if any(destination.iterdir()):
            # Repeating an already-completed restore must not change anything.
            for relative, content in payload.items():
                target = destination / relative
                if (target.is_symlink() or not target.is_file()
                        or not target.resolve().is_relative_to(destination.resolve())
                        or target.read_bytes() != content):
                    raise ValueError("Destination has different or incomplete source files. Use a new private directory; existing files will not be overwritten.")
            return {"bookId": expected_book, "questionCount": manifest["questionCount"],
                    "destination": str(destination), "alreadyRestored": True, "productionLedgerModified": False}
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".source-restore-", dir=destination.parent))
    try:
        for relative, content in payload.items():
            atomic_write(staged / relative, content)
        # os.rename replaces only an empty directory, never a populated one.
        staged.rename(destination)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return {"bookId": expected_book, "questionCount": manifest["questionCount"],
            "destination": str(destination), "alreadyRestored": False, "productionLedgerModified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Verify every checksum and print the archive's identity")
    inspect.add_argument("archive", type=Path)
    inspect.add_argument("--book", help="Reject an archive from any other book")
    recover = commands.add_parser("restore", help="Restore into a new/empty directory, or verify an identical previous restoration")
    recover.add_argument("archive", type=Path)
    recover.add_argument("--book", required=True, help="Expected book ID, not merely a question number")
    recover.add_argument("--destination", type=Path, help="Defaults to private-content/books/BOOK_ID")
    export = commands.add_parser("export", help="Build and verify an ordinary private ZIP")
    export.add_argument("--source", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "export":
            if args.output.exists():
                raise ValueError("Archive output already exists; choose a new path")
            data, _ = build_archive(args.source, None)
            manifest = inspect_archive(data)
            atomic_write(args.output, data)
            result = {"bookId": manifest["bookId"], "questionCount": manifest["questionCount"],
                      "archive": str(args.output.resolve()), "sha256": digest(data), "verified": True}
        else:
            data = args.archive.read_bytes()
            manifest = inspect_archive(data, args.book)
            if args.command == "restore":
                destination = args.destination or PROJECT / "private-content" / "books" / args.book
                result = restore(data, args.book, destination)
            else:
                result = {"bookId": manifest["bookId"], "questionCount": manifest["questionCount"],
                          "sourceFileCount": len(manifest["files"]), "sha256": digest(data), "verified": True,
                          "originalPdfIncluded": manifest["originalPdfIncluded"]}
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Source recovery failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
