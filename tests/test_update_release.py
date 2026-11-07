"""Temporary delivery integrity and retirement guards, with no remote writes.

All source records below are isolated synthetic fixtures. They exercise the real
source-policy gate; they do not manufacture approvals for repository lessons.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import prepare_update_release as delivery
from source_policy import SourcePolicyError, canonical_hash

NOW = "2026-11-07T12:00:00Z"
LATER = "2026-12-10T12:00:00Z"
HEAD = "a" * 40


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(delivery.json_bytes(value))


class PackInspectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.web = self.repo / "web"
        self.pack = self.repo / "test.zip"
        self.lessons, self.payload, questions, anchors = [], {}, [], {}
        for n in (5, 54, 182):
            lesson_id = f"shahzad2015-q{n:03d}"
            question_id = f"fixture-source-question-{n}"
            audio, image = f"media/audio/{n}.mp3", f"media/real/{n}.png"
            media = {audio: f"synthetic audio bytes {n}".encode(), image: f"synthetic image bytes {n}".encode()}
            for name, data in media.items():
                target = self.web / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            self.payload.update(media)
            timing = (self.web / audio).with_suffix(".timing.json")
            write_json(timing, {"testFixtureOnly": True, "number": n})
            lesson = {"id": lesson_id, "version": 3, "title": f"Synthetic existing lesson fixture {n}",
                      "source": {"bookId": delivery.BOOK_ID, "questionNumber": n},
                      "audioUrl": audio, "poster": image,
                      "scenes": [{"image": image}], "realImages": [{"url": image}],
                      "quiz": {"prompt": "Fixture?", "options": ["A", "B"], "correctIndex": 1}}
            validation = {"sourceQuestionId": question_id, "quizSha256": canonical_hash(lesson["quiz"]),
                          "lessonSha256": canonical_hash(lesson),
                          "mediaSha256": {k: hashlib.sha256(v).hexdigest() for k, v in media.items()},
                          "audioTimingSha256": delivery.sha_file(timing)}
            record_hash = hashlib.sha256(f"synthetic source {n}".encode()).hexdigest()
            questions.append({"number": n, "id": question_id, "lessonId": lesson_id, "status": "produced",
                              "sourceReview": {"sourceRecordSha256": record_hash},
                              "expectedQuizSha256": canonical_hash(lesson["quiz"]),
                              "qaReport": {"sourceChecked": True}, "productionValidation": validation})
            anchors[str(n)] = {"lessonId": lesson_id, "sourceRecordSha256": record_hash,
                               "quizSha256": canonical_hash(lesson["quiz"]), "validationSha256": canonical_hash(validation)}
            self.lessons.append(lesson)
        self.books = [{"id": delivery.BOOK_ID, "title": "Synthetic publication fixture only",
                       "author": "Test fixture", "year": 2015, "totalQuestions": 200,
                       "completedVideos": 3, "completedQuestionNumbers": [5, 54, 182]}]
        ledger = {"bookId": delivery.BOOK_ID, **{k: self.books[0][k] for k in ("title", "author", "year", "totalQuestions")},
                  "source": {"extractionSha256": "1" * 64}, "questions": questions}
        write_json(self.repo / "production/books" / (delivery.BOOK_ID + ".json"), ledger)
        write_json(self.repo / "production/source-policy.json",
                   {"schemaVersion": 1, "activeBookId": delivery.BOOK_ID, "newProductionEnabled": False,
                    "source": {"questionsSha256": "1" * 64}, "publishedSourceRecords": anchors})
        write_json(self.web / "data/lessons.json", self.lessons)
        write_json(self.web / "data/books.json", [{**self.books[0], "coverUrl": "media/private-cover-not-packaged.png"}])

    def build(self, *, lessons=None, extra=None, manifest_change=None, payload_change=None, corrupt=False):
        files = {**self.payload, "lessons.json": delivery.json_bytes(self.lessons if lessons is None else lessons), **(extra or {})}
        if payload_change:
            files.update(payload_change)
        manifest = {"schemaVersion": 1, "id": delivery.PACK_ID, "title": "Synthetic test package",
                    "version": "1.1.0", "lessonsFile": "lessons.json", "lessonCount": 3, "books": self.books,
                    "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        manifest.update(manifest_change or {})
        if corrupt:
            files["lessons.json"] += b" "  # Complete ZIP, stale payload hash.
        with zipfile.ZipFile(self.pack, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("manifest.json", delivery.json_bytes(manifest))
            for name, data in files.items():
                archive.writestr(name, data)
        return self.pack

    def inspect(self):
        return delivery.inspect_pack(self.pack, self.web, self.repo)

    def test_source_checked_three_lesson_pack_passes_real_policy_gate(self):
        self.build()
        report = self.inspect()
        self.assertEqual(report["lessonCount"], 3)
        self.assertEqual(set(report["lessonVersions"]), delivery.LESSON_IDS)
        self.assertEqual(report["zipBytes"], self.pack.stat().st_size)
        self.assertEqual(report["zipSha256"], delivery.sha_file(self.pack))
        self.assertTrue(report["sourceChecked"])
        self.assertFalse(report["privateFilesIncluded"])

    def test_extra_private_or_unreferenced_files_cannot_enter_delivery(self):
        for path in ("private-content/source.txt", "media/real/unreferenced.png", "learning-backup.json"):
            with self.subTest(path=path):
                self.build(extra={path: b"{}"})
                with self.assertRaisesRegex(ValueError, "extra/private files"):
                    self.inspect()

    def test_unknown_manifest_fields_are_rejected(self):
        self.build(manifest_change={"privateNotes": "must never publish"})
        with self.assertRaisesRegex(ValueError, "Unexpected package metadata"):
            self.inspect()

    def test_boolean_schema_does_not_masquerade_as_version_one(self):
        self.build(manifest_change={"schemaVersion": True})
        with self.assertRaisesRegex(ValueError, "integer 1"):
            self.inspect()

    def test_stable_pack_identity_includes_both_native_and_builder_aliases(self):
        for changes in ({"id": "different-pack"}, {"packId": "different-pack"}):
            with self.subTest(changes=changes):
                self.build(manifest_change=changes)
                with self.assertRaisesRegex(ValueError, "existing Raja starter pack ID"):
                    self.inspect()

    def test_renamed_or_added_lessons_are_rejected(self):
        changed = copy.deepcopy(self.lessons)
        changed[0]["id"] = "shahzad2015-q003"
        for value in (changed, self.lessons + [changed[0]], self.lessons[:2]):
            with self.subTest(count=len(value)):
                self.build(lessons=value)
                with self.assertRaisesRegex(ValueError, "three existing lessons"):
                    self.inspect()

    def test_other_book_fails_even_if_pack_and_public_json_agree(self):
        changed = copy.deepcopy(self.lessons)
        changed[0]["source"]["bookId"] = "unrelated-book"
        write_json(self.web / "data/lessons.json", changed)
        self.build(lessons=changed)
        with self.assertRaisesRegex(SourcePolicyError, "permits only"):
            self.inspect()

    def test_changed_teaching_cannot_gain_approval_by_matching_public_json(self):
        changed = copy.deepcopy(self.lessons)
        changed[0]["title"] = "Unreviewed replacement teaching"
        write_json(self.web / "data/lessons.json", changed)
        self.build(lessons=changed)
        with self.assertRaisesRegex(SourcePolicyError, "Published lesson bytes changed"):
            self.inspect()

    def test_book_count_cannot_be_inflated(self):
        books = copy.deepcopy(self.books)
        books[0]["completedVideos"] = 20
        self.build(manifest_change={"books": books})
        with self.assertRaisesRegex(SourcePolicyError, "completed counts"):
            self.inspect()

    def test_payload_checksum_corruption_and_truncated_zip_are_blocked(self):
        self.build(corrupt=True)
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.inspect()
        self.build()
        self.pack.write_bytes(self.pack.read_bytes()[:-40])
        with self.assertRaises(zipfile.BadZipFile):
            self.inspect()

    def test_self_consistent_archive_cannot_replace_reviewed_media(self):
        self.build(payload_change={"media/real/5.png": b"different bytes with a correct new archive hash"})
        with self.assertRaisesRegex(ValueError, "differs from reviewed media"):
            self.inspect()

    def test_changed_local_media_fails_source_binding(self):
        self.build()
        (self.web / "media/real/5.png").write_bytes(b"changed after review")
        with self.assertRaisesRegex(SourcePolicyError, "Published media changed"):
            self.inspect()


class DeliveryLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bytes = b"complete synthetic ZIP bytes; upload confirmation checks the prepared fingerprint"
        self.download = self.directory / "download.zip"
        self.download.write_bytes(self.bytes)
        self.checked = {"manifest": {"version": "1.1.0"}, "zipSha256": hashlib.sha256(self.bytes).hexdigest(),
                        "zipBytes": len(self.bytes), "lessonVersions": {key: 3 for key in delivery.LESSON_IDS}}
        self.catalog = {"schemaVersion": 1, "repository": delivery.REPOSITORY, "packs": [], "updatedAt": NOW}
        self.proposed, self.record = delivery.make_proposal(self.checked, self.catalog, 30, now=NOW)

    def test_proposal_has_complete_zip_fingerprint_stable_ids_and_retention(self):
        entry = self.proposed["packs"][0]
        self.assertEqual(entry["id"], delivery.PACK_ID)
        self.assertEqual(entry["bookId"], delivery.BOOK_ID)
        self.assertEqual(entry["lessonCount"], 3)
        self.assertEqual(entry["sha256"], hashlib.sha256(self.bytes).hexdigest())
        self.assertEqual(entry["sizeBytes"], len(self.bytes))
        self.assertEqual(entry["expiresAt"], "2026-12-07T12:00:00Z")
        self.assertEqual(self.catalog["packs"], [])  # Pure proposal, never an implicit live edit.

    def test_same_version_same_bytes_is_idempotent(self):
        second, record = delivery.make_proposal(self.checked, self.proposed, 90, now=LATER, prior_delivery=self.record)
        self.assertEqual(second, self.proposed)
        self.assertTrue(record["alreadyCurrent"])
        self.assertEqual(record["createdAt"], NOW)
        self.assertEqual(record["expiresAt"], self.record["expiresAt"])

    def test_same_version_different_bytes_or_url_is_rejected(self):
        for field, value in (("sha256", "0" * 64), ("sizeBytes", 999), ("url", "https://example.com/different.zip")):
            existing = copy.deepcopy(self.proposed)
            existing["packs"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "increase the version"):
                delivery.make_proposal(self.checked, existing, 30, now=NOW)

    def test_pack_and_lesson_version_downgrades_are_rejected(self):
        older = copy.deepcopy(self.checked)
        older["manifest"]["version"] = "1.0.9"
        with self.assertRaisesRegex(ValueError, "older version"):
            delivery.make_proposal(older, self.proposed, 30, now=NOW)
        older["manifest"]["version"] = "1.2.0"
        older["lessonVersions"]["shahzad2015-q005"] = 2
        with self.assertRaisesRegex(ValueError, "downgrade an existing lesson"):
            delivery.make_proposal(older, self.proposed, 30, now=NOW)

    def test_retired_version_cannot_be_reused_after_catalog_removal(self):
        empty, retired = delivery.retire(self.record, self.proposed, now=NOW)
        with self.assertRaisesRegex(ValueError, "retired delivery version"):
            delivery.make_proposal(self.checked, empty, 30, now=LATER, prior_delivery=retired)

    def test_history_keeps_versions_monotonic_after_catalog_retirement(self):
        _, retired = delivery.retire(self.record, self.proposed, now=NOW)
        records = self.directory / "records"
        write_json(records / (retired["releaseTag"] + ".json"), retired)
        self.assertEqual(delivery.check_history(self.checked, records), retired)
        older = copy.deepcopy(self.checked)
        older["manifest"]["version"] = "1.0.0"
        with self.assertRaisesRegex(ValueError, "precede a version"):
            delivery.check_history(older, records)
        older["manifest"]["version"] = "1.2.0"
        older["lessonVersions"]["shahzad2015-q005"] = 2
        with self.assertRaisesRegex(ValueError, "downgrade a lesson version"):
            delivery.check_history(older, records)

    def test_version_and_retention_inputs_fail_closed(self):
        for value in ("../escape", "1.2", "1.2.3-rc1", "01.2.3", "1.2.3\n", "1.2.3;echo secret", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                delivery.version_tuple(value)
        for days in (0, -1, 91, True, "30"):
            with self.subTest(days=days), self.assertRaises(ValueError):
                delivery.make_proposal(self.checked, self.catalog, days, now=NOW)

    def test_catalog_validation_rejects_duplicates_or_another_source(self):
        path = self.directory / "catalog.json"
        for value in ({**self.proposed, "packs": self.proposed["packs"] * 2},
                      {**self.catalog, "repository": "other/repo"},
                      {**self.catalog, "packs": [{"id": "other-pack", "bookId": "other-book"}]}):
            with self.subTest(value=value):
                write_json(path, value)
                with self.assertRaises(ValueError):
                    delivery.load_catalog(path)

    def remote_release(self):
        return {"tag_name": self.record["releaseTag"], "assets": [{
            "id": 42, "url": f"https://api.github.com/repos/{delivery.REPOSITORY}/releases/assets/42",
            "name": self.record["assetName"], "size": len(self.bytes), "state": "uploaded",
            "browser_download_url": self.record["assetUrl"], "digest": "sha256:" + self.record["zipSha256"]}]}

    def test_upload_confirmation_requires_actual_downloaded_bytes(self):
        confirmed = delivery.confirm_upload(self.record, self.download, self.remote_release())
        self.assertTrue(confirmed["remoteBytesVerified"])
        self.assertEqual(confirmed["assetId"], 42)
        for data in (self.bytes[:-1], b"x" * len(self.bytes)):
            with self.subTest(length=len(data)):
                self.download.write_bytes(data)
                with self.assertRaisesRegex(ValueError, "complete ZIP"):
                    delivery.confirm_upload(self.record, self.download, self.remote_release())

    def test_remote_asset_metadata_and_digest_must_match(self):
        for field, value in (("size", 1), ("state", "new"), ("digest", "sha256:" + "0" * 64),
                             ("browser_download_url", "https://example.com/asset.zip"),
                             ("id", True), ("url", "https://api.github.com/repos/other/repo/releases/assets/42")):
            remote = self.remote_release()
            remote["assets"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                delivery.confirm_upload(self.record, self.download, remote)
        duplicate = self.remote_release()
        duplicate["assets"] *= 2
        with self.assertRaises(ValueError):
            delivery.confirm_upload(self.record, self.download, duplicate)

    def test_retirement_removes_exact_old_url_and_preserves_newer_delivery(self):
        newer = copy.deepcopy(self.checked)
        newer["manifest"]["version"] = "1.2.0"
        new_catalog, _ = delivery.make_proposal(newer, self.proposed, 30, now=NOW)
        retired_catalog, record = delivery.retire(self.record, new_catalog, now=NOW)
        self.assertEqual(retired_catalog["packs"], new_catalog["packs"])
        self.assertEqual(record["status"], "retired")
        empty, _ = delivery.retire(self.record, self.proposed, now=NOW)
        self.assertEqual(empty["packs"], [])

    def test_retirement_cannot_leave_a_second_catalog_reference(self):
        catalog = copy.deepcopy(self.proposed)
        catalog["notes"] = {"fallbackDownload": self.record["assetUrl"] + "?download=1"}
        with self.assertRaisesRegex(ValueError, "still references"):
            delivery.retire(self.record, catalog, now=NOW)

    def test_manual_deletion_check_requires_merged_retirement_expiry_and_current_head(self):
        catalog, record = delivery.retire(self.record, self.proposed, now=NOW)
        allowed = delivery.check_retired(record, catalog, HEAD, HEAD, now=LATER)
        self.assertTrue(allowed["eligibleForManualDeletion"])
        self.assertFalse(allowed["automaticDeletion"])
        cases = [(self.record, catalog, HEAD, HEAD, LATER),
                 (record, catalog, HEAD, "b" * 40, LATER),
                 (record, catalog, "", "", LATER),
                 (record, catalog, HEAD, HEAD, NOW),
                 (record, self.proposed, HEAD, HEAD, LATER)]
        for candidate, current, observed, live, moment in cases:
            with self.subTest(observed=observed, status=candidate["status"], moment=moment), self.assertRaises(ValueError):
                delivery.check_retired(candidate, current, observed, live, now=moment)

    def test_encoded_query_and_release_page_urls_all_block_deletion(self):
        record = delivery.confirm_upload(self.record, self.download, self.remote_release())
        catalog, record = delivery.retire(record, self.proposed, now=NOW)
        refs = [record["assetUrl"] + "?download=true#file",
                record["assetUrl"].replace("InstaAnki-Raja", "%49nstaAnki-Raja"),
                record["assetUrl"].replace("blsmohamme972-lab/InstaAnki", "BLSMOHAMME972-LAB/INSTAANKI"),
                f"https://github.com/{delivery.REPOSITORY}/releases/tag/{record['releaseTag']}",
                record["assetApiUrl"].replace("blsmohamme972-lab/InstaAnki", "BLSMOHAMME972-LAB/INSTAANKI"),
                f"Older download: [ZIP]({record['assetUrl']})"]
        for ref in refs:
            with self.subTest(ref=ref), self.assertRaisesRegex(ValueError, "still references"):
                delivery.check_retired(record, {**catalog, "fallback": {"urls": [ref]}}, HEAD, HEAD, now=LATER)

    def test_review_files_describe_retirement_without_implying_deletion(self):
        source = self.directory / "catalog.json"
        write_json(source, self.proposed)
        catalog, record = delivery.retire(self.record, self.proposed, now=NOW)
        delivery.write_proposal(source, catalog, record, self.directory / "proposal")
        self.assertEqual(json.loads(source.read_text()), self.proposed)
        body = (self.directory / "proposal/release-body.md").read_text()
        self.assertIn("No release or file is deleted", body)
        self.assertTrue((self.directory / "proposal/catalog.diff").read_text())


if __name__ == "__main__":
    unittest.main()
