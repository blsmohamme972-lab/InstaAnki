#!/usr/bin/env python3
"""Create or recover an authenticated, encrypted private source archive.

Requires the cryptography Python package. Examples:
    python tools/source_vault.py encrypt
    python tools/source_vault.py verify
    python tools/source_vault.py decrypt --output dist/Recovered-Source.zip
    python tools/source_vault.py decrypt --extract-to /private/empty-recovery-dir

The secret key is generated once outside the repository and never printed.
Back up that key separately: there is no recovery without it. The public vault
contains ciphertext only. The private ZIP contains the source extraction,
not the original PDF. Progress fields in it are historical snapshots; the
production/books ledger remains the authority for lesson production.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import tempfile
import uuid
import zipfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_KEY = PROJECT.parent / ".instaanki-source-vault/key.json"
DEFAULT_VAULT = PROJECT / "source-vault/raja2015.iaenc"
DEFAULT_ARCHIVE = PROJECT / "dist/InstaAnki-Source-Archive.zip"
MAGIC = b"IAENC\x00\x01"
MANIFEST_NAME = "source-archive-manifest.json"
SOURCE_EXTENSIONS = {".json", ".txt", ".py", ".png", ".jpg", ".jpeg", ".webp"}
EXCLUDED_DIRECTORIES = {"app-assets", "__pycache__", "node_modules", ".cache"}
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_ENTRIES = 10000
MAX_HEADER_BYTES = 65536
PROGRESS_NOTE = (
    "Progress/status fields inside this source archive are historical snapshots, "
    "not production authority. Consult the current production/books ledger in "
    "the repository. Source recovery must not replace that ledger."
)


def json_bytes(value, *, canonical=False) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=canonical,
                       separators=(",", ":") if canonical else None,
                       indent=None if canonical else 2, allow_nan=False) + "\n").encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes, mode=0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_key(path: Path, create=False) -> tuple[str, bytes, bool]:
    path = path.resolve()
    if path.is_relative_to(PROJECT.resolve()):
        raise ValueError("The secret key must be stored outside the repository")
    created = False
    if not path.exists():
        if not create:
            raise ValueError("Source-vault key is missing; restore its separate private backup")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        record = {"schemaVersion": 1, "algorithm": "AES-256-GCM",
                  "keyId": str(uuid.uuid4()),
                  "keyBase64": base64.b64encode(AESGCM.generate_key(bit_length=256)).decode("ascii")}
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json_bytes(record))
            stream.flush()
            os.fsync(stream.fileno())
        created = True
    os.chmod(path, 0o600)
    try:
        record = json.loads(path.read_text())
        key = base64.b64decode(record["keyBase64"], validate=True)
        key_id = record["keyId"]
        uuid.UUID(key_id)
        if record.get("schemaVersion") != 1 or record.get("algorithm") != "AES-256-GCM" or len(key) != 32:
            raise ValueError()
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError("The private source-vault key file is malformed") from error
    return key_id, key, created


def archive_path(name: str) -> str:
    if (not isinstance(name, str) or not name or name.startswith("/") or "\\" in name
            or "\x00" in name or ":" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))):
        raise ValueError("Unsafe source archive path")
    if name == MANIFEST_NAME:
        return name
    if not name.startswith("private-content/"):
        raise ValueError("Source files must remain under private-content/")
    relative_parts = PurePosixPath(name).parts[1:]
    if any(part in EXCLUDED_DIRECTORIES or part.startswith(".") for part in relative_parts):
        raise ValueError("Excluded source archive directory")
    if PurePosixPath(name).suffix.lower() not in SOURCE_EXTENSIONS:
        raise ValueError("Unsupported source file; original PDF and key material are excluded")
    return name


def verify_archive(data: bytes) -> dict:
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("Source ZIP exceeds the size limit")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if not 1 <= len(entries) <= MAX_ENTRIES:
            raise ValueError("Invalid source ZIP entry count")
        names = set()
        total = 0
        for entry in entries:
            name = archive_path(entry.filename)
            if entry.is_dir() or name.casefold() in names:
                raise ValueError("Duplicate or unexpected directory entry in source ZIP")
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Symbolic links are not accepted in source ZIPs")
            names.add(name.casefold())
            total += entry.file_size
            if entry.file_size < 0 or total > MAX_ARCHIVE_BYTES:
                raise ValueError("Expanded source ZIP exceeds the size limit")
        manifest = json.loads(archive.read(MANIFEST_NAME))
        if manifest.get("schemaVersion") != 1 or manifest.get("originalPdfIncluded") is not False:
            raise ValueError("Invalid source archive manifest")
        files = manifest.get("files")
        if not isinstance(files, list) or len(files) != len(entries) - 1:
            raise ValueError("Source manifest file count does not match")
        expected = {entry.filename for entry in entries} - {MANIFEST_NAME}
        if {item.get("path") for item in files} != expected:
            raise ValueError("Source manifest does not describe every payload file")
        for item in files:
            payload = archive.read(item["path"])
            if len(payload) != item.get("bytes") or digest(payload) != item.get("sha256"):
                raise ValueError(f"Source file checksum mismatch: {item['path']}")
        return manifest


def build_archive(source: Path, ledger: str | None) -> tuple[bytes, dict]:
    source = source.resolve()
    required = ["questions.json", "book-pages.json", "book-metadata.json", "source-figures.json",
                "source-annotations.json", "extraction-report.json", "figure-qa.json"]
    if any(not (source / name).is_file() for name in required):
        raise ValueError("The complete verified extraction is not present")
    metadata = json.loads((source / "book-metadata.json").read_text())
    questions = json.loads((source / "questions.json").read_text())
    qa = json.loads((source / "figure-qa.json").read_text())
    if not isinstance(questions, list) or len(questions) != metadata.get("question_count"):
        raise ValueError("Source question count does not match the book metadata")
    if qa.get("final_asset_fidelity_summary", {}).get("repair_required") != 0:
        raise ValueError("Source figure QA is incomplete")
    book_id = metadata.get("id", metadata.get("book_id"))
    if not isinstance(book_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", book_id):
        raise ValueError("Book metadata has an invalid ID")
    ledger = ledger or f"production/books/{book_id}.json"
    payload = {}
    lower_names = set()
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in EXCLUDED_DIRECTORIES or part.startswith(".") for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError("Source snapshot cannot include symbolic links")
        if not path.is_file():
            continue
        # Original PDF is never read, copied, or deleted by this tool.
        if path.suffix.lower() == ".pdf":
            continue
        name = archive_path("private-content/" + relative.as_posix())
        if name.casefold() in lower_names:
            raise ValueError("Case-insensitive source path collision")
        lower_names.add(name.casefold())
        payload[name] = path.read_bytes()
    manifest = {
        "schemaVersion": 1, "format": "instaanki-private-source-archive-v1",
        "bookId": book_id, "bookTitle": metadata.get("title"),
        "questionCount": len(questions), "originalPdfIncluded": False,
        "duplicateAppAssetsIncluded": False,
        "authoritativeProductionLedger": ledger, "progressSnapshotNote": PROGRESS_NOTE,
        "files": [{"path": name, "bytes": len(value), "sha256": digest(value)}
                  for name, value in sorted(payload.items())],
    }
    payload[MANIFEST_NAME] = json_bytes(manifest)
    if len(payload) > MAX_ENTRIES or sum(map(len, payload.values())) > MAX_ARCHIVE_BYTES:
        raise ValueError("Source snapshot exceeds archive limits")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, value in sorted(payload.items()):
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100600 << 16
            archive.writestr(entry, value)
    data = buffer.getvalue()
    verify_archive(data)
    return data, manifest


def encrypt_archive(data: bytes, manifest: dict, key_id: str, key: bytes) -> bytes:
    nonce = os.urandom(12)
    header = {"schemaVersion": 1, "algorithm": "AES-256-GCM", "keyId": key_id,
              "nonceBase64": base64.b64encode(nonce).decode("ascii"),
              "bookId": manifest["bookId"], "archiveBytes": len(data), "archiveSha256": digest(data)}
    encoded_header = json_bytes(header, canonical=True)
    associated_data = MAGIC + struct.pack(">I", len(encoded_header)) + encoded_header
    return associated_data + AESGCM(key).encrypt(nonce, data, associated_data)


def decrypt_archive(vault: bytes, key_id: str, key: bytes) -> tuple[bytes, dict]:
    prefix_size = len(MAGIC) + 4
    if len(vault) < prefix_size + 16 or not vault.startswith(MAGIC):
        raise ValueError("Invalid encrypted source-vault format")
    header_size = struct.unpack(">I", vault[len(MAGIC):prefix_size])[0]
    boundary = prefix_size + header_size
    if not 1 <= header_size <= MAX_HEADER_BYTES or boundary + 16 > len(vault):
        raise ValueError("Invalid source-vault header length")
    header = json.loads(vault[prefix_size:boundary])
    if (header.get("schemaVersion") != 1 or header.get("algorithm") != "AES-256-GCM"
            or header.get("keyId") != key_id):
        raise ValueError("Source-vault format or key identity does not match")
    nonce = base64.b64decode(header["nonceBase64"], validate=True)
    if len(nonce) != 12:
        raise ValueError("Invalid source-vault nonce")
    try:
        data = AESGCM(key).decrypt(nonce, vault[boundary:], vault[:boundary])
    except InvalidTag as error:
        raise ValueError("Source-vault authentication failed: wrong key or altered data") from error
    if len(data) != header.get("archiveBytes") or digest(data) != header.get("archiveSha256"):
        raise ValueError("Recovered source archive does not match its authenticated hash")
    manifest = verify_archive(data)
    if manifest.get("bookId") != header.get("bookId"):
        raise ValueError("Source-vault book identity mismatch")
    return data, manifest


def extract_archive(data: bytes, target: Path) -> None:
    verify_archive(data)
    target = target.resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError("Recovery directory must be new or empty; existing source/progress is not overwritten")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            path = target / archive_path(entry.filename)
            if not path.resolve().is_relative_to(target):
                raise ValueError("Recovery path escapes the destination")
            atomic_write(path, archive.read(entry.filename))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["encrypt", "decrypt", "verify"], nargs="?", default="encrypt")
    parser.add_argument("--source", type=Path, default=PROJECT / "private-content")
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    parser.add_argument("--private-zip", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--ledger", help="Relative authoritative production/books ledger path")
    parser.add_argument("--output", type=Path, help="Recovered private ZIP output, for decrypt")
    parser.add_argument("--extract-to", type=Path, help="New or empty recovery directory, for decrypt")
    parser.add_argument("--overwrite", action="store_true", help="Allow a recovered ZIP to replace an existing file")
    args = parser.parse_args()
    key_id, key, key_created = load_key(args.key, create=args.command == "encrypt")

    if args.command == "encrypt":
        archive, manifest = build_archive(args.source, args.ledger)
        vault = encrypt_archive(archive, manifest, key_id, key)
        recovered, recovered_manifest = decrypt_archive(vault, key_id, key)
        if recovered != archive or recovered_manifest != manifest:
            raise ValueError("Deterministic round-trip recovery failed")
        altered = vault[:-1] + bytes([vault[-1] ^ 1])
        try:
            decrypt_archive(altered, key_id, key)
        except ValueError:
            tamper_rejected = True
        else:
            raise ValueError("Authentication check failed to reject altered ciphertext")
        atomic_write(args.private_zip, archive)
        atomic_write(args.vault, vault, mode=0o644)
        metadata = {
            "schemaVersion": 1, "format": "instaanki-encrypted-source-vault-v1",
            "bookId": manifest["bookId"], "algorithm": "AES-256-GCM", "keyId": key_id,
            "vaultFile": args.vault.name, "vaultBytes": len(vault), "vaultSha256": digest(vault),
            "archiveBytes": len(archive), "archiveSha256": digest(archive),
            "sourceFileCount": len(manifest["files"]), "questionCount": manifest["questionCount"],
            "originalPdfIncluded": False, "duplicateAppAssetsIncluded": False,
            "authoritativeProductionLedger": manifest["authoritativeProductionLedger"],
            "privateKeyRequired": True, "roundTripHashesVerified": True,
        }
        metadata_path = args.vault.with_suffix(".metadata.json")
        atomic_write(metadata_path, json_bytes(metadata), mode=0o644)
        report = {**metadata, "keyCreated": key_created, "keyMaterialPrinted": False,
                  "ciphertextTamperRejected": tamper_rejected,
                  "privateZip": str(args.private_zip.resolve()),
                  "vault": str(args.vault.resolve()), "metadata": str(metadata_path.resolve())}
        atomic_write(args.private_zip.with_suffix(".report.json"), json_bytes(report))
        print(json.dumps(report, indent=2))
        return

    recovered, manifest = decrypt_archive(args.vault.read_bytes(), key_id, key)
    if args.command == "decrypt":
        if args.output is None and args.extract_to is None:
            args.output = PROJECT / "dist/InstaAnki-Source-Archive-recovered.zip"
        if args.output:
            if args.output.exists() and not args.overwrite:
                raise ValueError("Recovered ZIP already exists; choose a new path or use --overwrite")
            atomic_write(args.output, recovered)
        if args.extract_to:
            extract_archive(recovered, args.extract_to)
    print(json.dumps({"verified": True, "bookId": manifest["bookId"],
                      "sourceFileCount": len(manifest["files"]), "questionCount": manifest["questionCount"],
                      "archiveSha256": digest(recovered), "archiveBytes": len(recovered),
                      "authoritativeProductionLedger": manifest["authoritativeProductionLedger"],
                      "progressSnapshotNote": PROGRESS_NOTE,
                      "output": str(args.output.resolve()) if args.output else None,
                      "extractedTo": str(args.extract_to.resolve()) if args.extract_to else None}, indent=2))


if __name__ == "__main__":
    main()
