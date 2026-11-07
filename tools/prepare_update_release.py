#!/usr/bin/env python3
"""Prepare a reviewed, temporary delivery of the three existing Raja lessons.

This tool never uploads, merges, deletes a release, reads a signing key, or
generates lesson media. GitHub Actions performs the explicitly requested release
upload, then proposes the catalog change in a pull request. Expiry is a review
date, not permission to break an active download URL.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import unquote, urlsplit
import zipfile

from build_pack import verify_archive
from source_policy import SourcePolicy, canonical_hash, validate_publications

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "blsmohamme972-lab/InstaAnki"
BOOK_ID = "shahzad-raja-2015-200-practice-questions"
PACK_ID = "instaanki-starter-shahzad2015-v1"
LESSON_IDS = {"shahzad2015-q005", "shahzad2015-q054", "shahzad2015-q182"}
VERSION = re.compile(r"(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\Z")


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc(value=None):
    moment = datetime.now(timezone.utc) if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("A UTC/offset timestamp is required")
    return moment.astimezone(timezone.utc)


def iso(moment):
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def version_tuple(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise ValueError("Use a stable major.minor.patch content version")
    return tuple(map(int, value.split(".")))


def load_catalog(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1 or not isinstance(value.get("packs"), list):
        raise ValueError("Unsupported update catalog")
    if value.get("repository") != REPOSITORY:
        raise ValueError("Catalog belongs to a different repository")
    ids = [item.get("id") for item in value["packs"] if isinstance(item, dict)]
    if len(ids) != len(value["packs"]) or any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("Catalog contains invalid or duplicate pack IDs")
    if any(item["id"] != PACK_ID or item.get("bookId") != BOOK_ID for item in value["packs"]):
        raise ValueError("This workflow supports only the existing three-lesson Raja pack; review other catalog entries separately")
    return value


def media_paths(lessons):
    paths = set()
    for lesson in lessons:
        paths.update([lesson["audioUrl"], lesson["poster"]])
        paths.update(scene["image"] for scene in lesson["scenes"])
        paths.update(item["url"] for item in lesson["realImages"])
        if lesson.get("videoUrl"):
            paths.add(lesson["videoUrl"])
    return paths


def inspect_pack(pack, web_root, repo=ROOT):
    """Bind the entire archive to currently reviewed public content and media."""
    pack, web_root, repo = Path(pack), Path(web_root).resolve(), Path(repo).resolve()
    checked = verify_archive(pack)
    with zipfile.ZipFile(pack) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if type(manifest.get("schemaVersion")) is not int or manifest["schemaVersion"] != 1:
            raise ValueError("Package schemaVersion must be the integer 1")
        if set(manifest) - {"schemaVersion", "id", "packId", "title", "version", "lessonsFile", "lessonCount", "sha256", "books"}:
            raise ValueError("Unexpected package metadata; do not publish private or unreviewed fields")
        identifiers = {manifest[key] for key in ("id", "packId") if key in manifest}
        if identifiers != {PACK_ID}:
            raise ValueError("Keep the existing Raja starter pack ID; source substitution is forbidden")
        version_tuple(manifest.get("version"))
        if manifest.get("lessonsFile", "lessons.json") != "lessons.json":
            raise ValueError("Use the reviewed lessons.json payload")
        lessons = json.loads(archive.read("lessons.json"))
        if not isinstance(lessons, list) or len(lessons) != 3 or {x.get("id") for x in lessons} != LESSON_IDS:
            raise ValueError("This delivery is restricted to the three existing lessons Q5, Q54 and Q182")
        if manifest.get("lessonCount") != 3:
            raise ValueError("The manifest lesson count must remain three")
        public = json.loads((web_root / "data/lessons.json").read_text())
        if not isinstance(public, list) or len(public) != 3 or {x.get("id") for x in public} != LESSON_IDS:
            raise ValueError("The current app must contain exactly the three existing lessons")
        if {x["id"]: canonical_hash(x) for x in lessons} != {x["id"]: canonical_hash(x) for x in public}:
            raise ValueError("Pack lessons differ from the reviewed current app")
        # This is the real production gate, not a name-only or copied-hash check.
        policy = SourcePolicy(repo)
        policy.validate_pack(lessons, web_root)
        validate_publications(manifest.get("books"), policy.ledger())
        public_books = json.loads((web_root / "data/books.json").read_text())
        public_books = [{k: v for k, v in book.items() if k != "coverUrl"} for book in public_books]
        if canonical_hash(public_books) != canonical_hash(manifest["books"]):
            raise ValueError("Publication metadata differs from the reviewed public app")
        expected = {"manifest.json", "lessons.json"} | media_paths(lessons)
        if set(archive.namelist()) != expected:
            raise ValueError("Only the lesson list and its referenced public media may be released; extra/private files are forbidden")
        for name in expected - {"manifest.json", "lessons.json"}:
            local = (web_root / name).resolve()
            if not name.startswith("media/") or not local.is_relative_to(web_root) or not local.is_file():
                raise ValueError("A packaged asset is not approved public media")
            if sha_file(local) != manifest["sha256"][name]:
                raise ValueError(f"Pack asset differs from reviewed media: {name}")
        versions = {}
        for lesson in lessons:
            version = lesson.get("version", 1)
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise ValueError("Each existing lesson needs a positive integer version")
            versions[lesson["id"]] = version
    return {"manifest": manifest, "lessonVersions": versions, "zipBytes": checked["zipBytes"],
            "zipSha256": checked["zipSha256"], "sourceChecked": True, "dataOnly": True,
            "privateFilesIncluded": False, "lessonCount": 3}


def check_history(checked, records_dir):
    """Keep version monotonicity even after an old catalog entry is retired."""
    same_version = None
    for path in sorted(Path(records_dir).glob("content-raja-*.json")):
        record = json.loads(path.read_text())
        validate_delivery(record)
        if path.name != record["releaseTag"] + ".json":
            raise ValueError("A delivery history filename disagrees with its version")
        if version_tuple(checked["manifest"]["version"]) < version_tuple(record["version"]):
            raise ValueError("A content version cannot precede a version in delivery history")
        for lesson_id, old_version in record.get("lessonVersions", {}).items():
            if isinstance(old_version, bool) or not isinstance(old_version, int) or old_version < 1:
                raise ValueError("Delivery history has invalid lesson versions")
            if lesson_id in checked["lessonVersions"] and checked["lessonVersions"][lesson_id] < old_version:
                raise ValueError("A content update cannot downgrade a lesson version from delivery history")
        if record["version"] == checked["manifest"]["version"]:
            same_version = record
    return same_version


def make_proposal(checked, catalog, retention_days, now=None, prior_delivery=None):
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or not 1 <= retention_days <= 90:
        raise ValueError("Retention must be between 1 and 90 days")
    stamp = utc(now)
    version = checked["manifest"]["version"]
    version_tuple(version)
    tag = "content-raja-" + version
    name = "InstaAnki-Raja-Starter-" + version + ".zip"
    url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"
    previous = next((item for item in catalog["packs"] if item["id"] == PACK_ID), None)
    if prior_delivery is not None:
        validate_delivery(prior_delivery)
        if prior_delivery["version"] != version:
            raise ValueError("The prior delivery record belongs to another version")
        if prior_delivery.get("status") != "active":
            raise ValueError("A retired delivery version cannot be reused; increase the content version")
        if prior_delivery["zipSha256"] != checked["zipSha256"] or prior_delivery["zipBytes"] != checked["zipBytes"]:
            raise ValueError("This version has already been delivered with different bytes; increase the version")
    if previous:
        old, new = version_tuple(previous.get("version")), version_tuple(version)
        if new < old:
            raise ValueError("A content update cannot roll the stable pack back to an older version")
        if new == old and (previous.get("sha256") != checked["zipSha256"] or previous.get("sizeBytes") != checked["zipBytes"] or previous.get("url") != url):
            raise ValueError("This version already identifies different bytes or a different URL; increase the version")
        previous_versions = previous.get("lessonVersions", {})
        if not isinstance(previous_versions, dict):
            raise ValueError("The current catalog has invalid lesson versions")
        for lesson_id, old_version in previous_versions.items():
            if isinstance(old_version, bool) or not isinstance(old_version, int) or old_version < 1:
                raise ValueError("The current catalog has invalid lesson versions")
            if lesson_id in checked["lessonVersions"] and checked["lessonVersions"][lesson_id] < old_version:
                raise ValueError("A content update cannot downgrade an existing lesson version")
    entry = {"id": PACK_ID, "bookId": BOOK_ID, "title": "Raja: existing lessons update", "version": version,
             "url": url, "sha256": checked["zipSha256"], "sizeBytes": checked["zipBytes"], "lessonCount": 3,
             "lessonVersions": checked["lessonVersions"], "minAppVersionCode": 2, "releaseTag": tag,
             "temporary": True, "expiresAt": iso(stamp + timedelta(days=retention_days))}
    proposed = copy.deepcopy(catalog)
    if previous and version_tuple(previous["version"]) == version_tuple(version):
        if not isinstance(previous.get("expiresAt"), str):
            raise ValueError("This version lacks its delivery retention record; increase the version for a reviewed delivery")
        utc(previous["expiresAt"])
        entry = copy.deepcopy(previous)  # An identical version is an idempotent operation.
        already_current = True
    else:
        proposed["packs"] = [x for x in proposed["packs"] if x["id"] != PACK_ID] + [entry]
        proposed["updatedAt"] = iso(stamp)
        already_current = False
    delivery = {"schemaVersion": 1, "repository": REPOSITORY, "packId": PACK_ID, "bookId": BOOK_ID,
                "version": version, "releaseTag": tag, "assetName": name, "assetUrl": url,
                "zipSha256": checked["zipSha256"], "zipBytes": checked["zipBytes"], "lessonCount": 3,
                "lessonVersions": checked["lessonVersions"], "sourceChecked": True, "dataOnly": True,
                "privateFilesIncluded": False, "createdAt": iso(stamp), "expiresAt": entry["expiresAt"],
                "retentionDays": retention_days, "status": "active", "retiredAt": None,
                "deletionPolicy": "manual-only-after-retirement-merge-and-live-catalog-check",
                "alreadyCurrent": already_current}
    if prior_delivery is not None:
        # A rerun must not silently prolong retention or rewrite the original provenance.
        delivery = copy.deepcopy(prior_delivery)
        delivery["alreadyCurrent"] = already_current
        entry["expiresAt"] = delivery["expiresAt"]
    return proposed, delivery


def write_proposal(catalog_path, proposed, delivery, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    (output / "catalog.proposed.json").write_bytes(json_bytes(proposed))
    (output / "delivery.json").write_bytes(json_bytes(delivery))
    before = Path(catalog_path).read_text().splitlines(keepends=True)
    after = json_bytes(proposed).decode().splitlines(keepends=True)
    (output / "catalog.diff").write_text("".join(difflib.unified_diff(before, after, fromfile="a/content/catalog.json", tofile="b/content/catalog.json")))
    if delivery["status"] == "retired":
        body = (f"## Retire temporary Raja delivery {delivery['version']}\n\n"
                "This change removes references to this exact older ZIP from the current catalog and records its retirement. "
                "It preserves a newer catalog version, if present, and changes no installed content or learning history.\n\n"
                f"- Asset: {delivery['assetUrl']}\n- Retention review date: {delivery['expiresAt']}\n\n"
                "No release or file is deleted by this change. After this pull request is reviewed and merged, "
                "run the read-only retirement check against the current default branch. Deletion remains a separate manual action.\n")
    else:
        body = (f"## Existing Raja lessons: {delivery['version']}\n\n"
            "This package updates the same three lessons (Q5, Q54 and Q182). It adds no lessons or publication.\n\n"
            f"- Stable pack ID: `{PACK_ID}`\n- ZIP bytes: {delivery['zipBytes']}\n"
            f"- SHA-256: `{delivery['zipSha256']}`\n- Retention review date: {delivery['expiresAt']}\n\n"
            "The asset stays available while any active catalog references it. Expiry does not automatically delete it. "
            "This is a data-only package; new app features still require a compatible signed APK.\n\n"
            "Review and merge the catalog pull request before expecting Check for updates to offer this package. "
            "No code, source PDF, signing key, review history or private notes are in this ZIP.\n")
    (output / "release-body.md").write_text(body)


def normalized_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            return None
        path = unquote(parsed.path)
        parts = path.split("/")
        if parsed.hostname.lower() == "github.com" and len(parts) > 2:
            parts[1:3] = [part.lower() for part in parts[1:3]]
        elif parsed.hostname.lower() == "api.github.com" and len(parts) > 3 and parts[1] == "repos":
            parts[2:4] = [part.lower() for part in parts[2:4]]
        return parsed.hostname.lower(), "/".join(parts)
    except ValueError:
        return None


def references_delivery(value, delivery):
    targets = {normalized_url(delivery["assetUrl"]), normalized_url(f"https://github.com/{REPOSITORY}/releases/tag/{delivery['releaseTag']}")}
    if delivery.get("assetApiUrl"):
        targets.add(normalized_url(delivery["assetApiUrl"]))
    if isinstance(value, dict):
        return any(references_delivery(item, delivery) for item in value.values())
    if isinstance(value, list):
        return any(references_delivery(item, delivery) for item in value)
    if isinstance(value, str):
        candidates = [value] + [match.rstrip(").,;]}") for match in re.findall(r"https://[^\s<>\"'`]+", value, re.IGNORECASE)]
        return any(normalized_url(candidate) in targets for candidate in candidates if normalized_url(candidate))
    return False


def validate_delivery(delivery):
    if not isinstance(delivery, dict) or type(delivery.get("schemaVersion")) is not int or delivery["schemaVersion"] != 1 or delivery.get("repository") != REPOSITORY or delivery.get("packId") != PACK_ID or delivery.get("bookId") != BOOK_ID:
        raise ValueError("Unsupported delivery record")
    version_tuple(delivery.get("version"))
    expected_tag = "content-raja-" + delivery["version"]
    expected_name = "InstaAnki-Raja-Starter-" + delivery["version"] + ".zip"
    if delivery.get("releaseTag") != expected_tag or delivery.get("assetName") != expected_name or delivery.get("assetUrl") != f"https://github.com/{REPOSITORY}/releases/download/{expected_tag}/{expected_name}":
        raise ValueError("Delivery URL, tag or filename differs from its version identity")
    if isinstance(delivery.get("zipBytes"), bool) or not isinstance(delivery.get("zipBytes"), int) or delivery["zipBytes"] <= 0 or not isinstance(delivery.get("zipSha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", delivery["zipSha256"]):
        raise ValueError("Delivery lacks a complete ZIP fingerprint")
    if delivery.get("status") not in {"active", "retired"} or not isinstance(delivery.get("expiresAt"), str):
        raise ValueError("Delivery lacks its lifecycle or retention date")
    utc(delivery["expiresAt"])
    versions = delivery.get("lessonVersions")
    if delivery.get("lessonCount") != 3 or not isinstance(versions, dict) or set(versions) != LESSON_IDS or any(type(v) is not int or v < 1 for v in versions.values()):
        raise ValueError("Delivery record must identify exactly the three existing lesson versions")
    if delivery.get("sourceChecked") is not True or delivery.get("dataOnly") is not True or delivery.get("privateFilesIncluded") is not False:
        raise ValueError("Delivery record is missing its source-checked data-only scope")


def retire(delivery, catalog, now=None):
    validate_delivery(delivery)
    proposed = copy.deepcopy(catalog)
    proposed["packs"] = [item for item in proposed["packs"] if normalized_url(item.get("url")) != normalized_url(delivery["assetUrl"])]
    if references_delivery(proposed, delivery):
        raise ValueError("Another catalog field still references this asset or release; review that reference before retirement")
    proposed["updatedAt"] = iso(utc(now))
    record = copy.deepcopy(delivery);record.update(status="retired", retiredAt=iso(utc(now)))
    return proposed, record


def check_retired(delivery, catalog, observed_head, current_head, now=None):
    validate_delivery(delivery)
    if not re.fullmatch(r"[a-f0-9]{40}", observed_head or "") or observed_head != current_head:
        raise ValueError("Default-branch evidence is stale or missing; fetch and check the current catalog again")
    if delivery.get("status") != "retired" or not delivery.get("retiredAt"):
        raise ValueError("Retirement must be merged before any manual deletion")
    if utc(delivery["retiredAt"]) > utc(now) or utc(delivery["expiresAt"]) > utc(now):
        raise ValueError("The delivery retention period has not elapsed")
    if references_delivery(catalog, delivery):
        raise ValueError("The current catalog still references this asset or release; do not delete it")
    return {"eligibleForManualDeletion": True, "automaticDeletion": False, "assetUrl": delivery["assetUrl"],
            "releaseTag": delivery["releaseTag"], "assetName": delivery["assetName"], "checkedDefaultBranchHead": current_head,
            "checkedAt": iso(utc(now)), "catalogSha256": hashlib.sha256(json_bytes(catalog)).hexdigest()}


def confirm_upload(delivery, downloaded, release):
    validate_delivery(delivery)
    if Path(downloaded).stat().st_size != delivery["zipBytes"] or sha_file(downloaded) != delivery["zipSha256"]:
        raise ValueError("Downloaded release asset does not match the prepared complete ZIP")
    if release.get("tag_name") != delivery["releaseTag"]:
        raise ValueError("Release tag differs from the prepared delivery")
    assets = [a for a in release.get("assets", []) if a.get("name") == delivery["assetName"]]
    if len(assets) != 1 or assets[0].get("size") != delivery["zipBytes"] or assets[0].get("browser_download_url") != delivery["assetUrl"] or assets[0].get("state") != "uploaded":
        raise ValueError("Uploaded asset metadata does not match the prepared delivery")
    asset = assets[0]
    if asset.get("digest") not in (None, "sha256:" + delivery["zipSha256"]):
        raise ValueError("GitHub reports a different asset digest")
    asset_id = asset.get("id")
    if isinstance(asset_id, bool) or not isinstance(asset_id, int) or asset_id <= 0 or asset.get("url") != f"https://api.github.com/repos/{REPOSITORY}/releases/assets/{asset_id}":
        raise ValueError("Uploaded asset identity is not the expected repository asset")
    result = copy.deepcopy(delivery)
    result.update(assetId=asset["id"], assetApiUrl=asset["url"], remoteBytesVerified=True, remoteVerifiedAt=iso(utc()))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--pack", type=Path, required=True)
    prepare.add_argument("--web-root", type=Path, default=ROOT / "web")
    prepare.add_argument("--catalog", type=Path, default=ROOT / "content/catalog.json")
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--retention-days", type=int, default=30)
    prepare.add_argument("--source-commit", required=True)
    prepare.add_argument("--records-dir", type=Path, default=ROOT / "content/deliveries")
    for name in ("retire", "check-retired"):
        command = commands.add_parser(name)
        command.add_argument("--delivery", type=Path, required=True)
        command.add_argument("--catalog", type=Path, required=True)
        if name == "retire": command.add_argument("--output-dir", type=Path, required=True)
        else:
            command.add_argument("--observed-default-head", required=True)
            command.add_argument("--current-default-head", required=True)
    confirm = commands.add_parser("confirm-upload")
    confirm.add_argument("--delivery", type=Path, required=True)
    confirm.add_argument("--downloaded", type=Path, required=True)
    confirm.add_argument("--release-json", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        if not re.fullmatch(r"[a-f0-9]{40}", args.source_commit): raise ValueError("A full source commit SHA is required")
        checked = inspect_pack(args.pack, args.web_root)
        previous = check_history(checked, args.records_dir)
        proposed, delivery = make_proposal(checked, load_catalog(args.catalog), args.retention_days, prior_delivery=previous)
        delivery.setdefault("sourceCommit", args.source_commit)
        delivery.setdefault("sourcePolicySha256", sha_file(ROOT / "production/source-policy.json"))
        delivery.setdefault("publicLessonsSha256", sha_file(args.web_root / "data/lessons.json"))
        write_proposal(args.catalog, proposed, delivery, args.output_dir)
        destination = args.output_dir / delivery["assetName"]
        if args.pack.resolve() != destination.resolve(): shutil.copyfile(args.pack, destination)
        print(json.dumps({"tag": delivery["releaseTag"], "assetName": delivery["assetName"], "sha256": delivery["zipSha256"], "sizeBytes": delivery["zipBytes"], "alreadyCurrent": delivery["alreadyCurrent"]}))
    elif args.command == "confirm-upload":
        result = confirm_upload(json.loads(args.delivery.read_text()), args.downloaded, json.loads(args.release_json.read_text()))
        args.delivery.write_bytes(json_bytes(result));print(json.dumps({"remoteBytesVerified": True, "assetId": result["assetId"]}))
    else:
        delivery, catalog = json.loads(args.delivery.read_text()), load_catalog(args.catalog)
        if args.command == "retire":
            proposed, record = retire(delivery, catalog)
            write_proposal(args.catalog, proposed, record, args.output_dir)
            print(json.dumps({"retirementProposalPrepared": True, "automaticDeletion": False}))
        else: print(json.dumps(check_retired(delivery, catalog, args.observed_default_head, args.current_default_head), indent=2))


if __name__ == "__main__":
    try: main()
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile) as error:
        print(f"Delivery blocked: {error}", file=sys.stderr)
        raise SystemExit(1)
