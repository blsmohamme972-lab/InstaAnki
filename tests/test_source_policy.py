"""Source scope, restored evidence and unchanged published-content regressions."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import production
from source_policy import (ORIGINAL_BOOK, SourcePolicy, SourcePolicyError, canonical_hash,
                           content_fingerprints, validate_content_review, validate_pack, validate_publications)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


class SourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.records = [{
            "id": f"{ORIGINAL_BOOK}-q{n:03d}", "source_question_number": n,
            "stem": f"Reviewed fixture question {n}?",
            "options": [{"label": "A", "text": "First"}, {"label": "B", "text": "Second"}],
            "correct_answer_letter": "B", "explanation": "Reviewed fixture explanation.",
            "source_question_pages": [{"printed_page": 2}],
            "source_answer_pages": [{"printed_page": 71}],
        } for n in [1, 2]]
        self.manifest_path = self.root / "production/books" / f"{ORIGINAL_BOOK}.json"
        self.policy_doc = json.loads((ROOT / "production/source-policy.json").read_text())
        self.policy_doc["newProductionEnabled"] = True  # Explicit synthetic authorization for these isolated fixtures.
        self.policy_doc["publishedSourceRecords"] = {}
        self.policy_doc["publishedRevisionReports"] = []
        self.document = {
            "schemaVersion": 1, "bookId": ORIGINAL_BOOK, "totalQuestions": 2,
            "completedVideos": 0, "completedQuestionNumbers": [], "source": {},
            "questions": [{"number": n, "id": self.records[n-1]["id"], "status": "ready",
                           "batchId": None, "lessonId": None} for n in [1, 2]],
        }
        self.save_reviewed_fixture()

    def save_reviewed_fixture(self):
        """A test-only reviewed extraction; production exposes no override."""
        path = self.root / "private-content/questions.json"
        write_json(path, self.records)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.policy_doc["source"]["questionsSha256"] = digest
        self.document["source"]["extractionSha256"] = digest
        write_json(self.root / "private-content/book-metadata.json", {"id": ORIGINAL_BOOK})
        write_json(self.root / "production/source-policy.json", self.policy_doc)
        write_json(self.manifest_path, self.document)

    def authored_fixture(self, evidence):
        return {
            "id": "lesson-fixture-1", "source_question_number": 1, "sourceEvidence": evidence,
            "title": "A source-derived fixture", "locus": {"id": "fixture-room", "description": "A fixed room."},
            "scenes": [{"id": "scene-1", "headline": "The reviewed idea", "voice_text": "A reviewed fixture explanation."}],
            "mcq": {"stem": "Reviewed fixture question 1?", "options": copy.deepcopy(self.records[0]["options"]),
                    "correct_answer_letter": "B", "explanation": "Reviewed fixture explanation."},
        }

    def record_fixture_content_review(self, authored):
        """Create explicit synthetic review evidence in the isolated test only."""
        ledger = json.loads(self.manifest_path.read_text())
        question = ledger["questions"][0]
        evidence = question["sourceEvidence"]
        question["sourceReview"] = {
            "schemaVersion": 1, "reviewedAt": "2026-11-07T12:00:00Z", "reviewer": "Unit-test fixture reviewer",
            "notes": "Synthetic test fixture comparison only; no real book review is represented.",
            "sourceQuestionChecked": True, "keyedAnswerChecked": True, "explanationChecked": True,
            "sourceRecordSha256": evidence["sourceRecordSha256"], "evidenceSha256": canonical_hash(evidence),
            **content_fingerprints(authored, authoring=True),
        }
        write_json(self.manifest_path, ledger)
        return ledger

    def assembled_fixture(self, authored):
        mcq = authored["mcq"]
        labels = [o["label"] for o in mcq["options"]]
        evidence = authored["sourceEvidence"]
        return {
            "id": "fixture-1", "title": authored["title"], "locus": copy.deepcopy(authored["locus"]),
            "scenes": [{"id": s["id"], "caption": s["headline"], "transcript": s["voice_text"]} for s in authored["scenes"]],
            "quiz": {"prompt": mcq["stem"], "options": [o["text"] for o in mcq["options"]],
                     "correctIndex": labels.index(mcq["correct_answer_letter"]), "explanation": mcq["explanation"]},
            "source": {"bookId": ORIGINAL_BOOK, "questionNumber": 1, "questionId": evidence["questionId"],
                       "evidenceSha256": canonical_hash(evidence)},
        }

    def test_missing_private_source_blocks_claim_without_changing_ledger(self):
        (self.root / "private-content/questions.json").unlink()
        before = self.manifest_path.read_bytes()
        with patch.object(production, "REPO", self.root):
            with self.assertRaisesRegex(SourcePolicyError, "Restore private-content/"):
                production.claim(self.manifest_path, 2, "new-batch")
        self.assertEqual(self.manifest_path.read_bytes(), before)

    def test_paused_production_blocks_new_claim_even_with_verified_source(self):
        self.policy_doc["newProductionEnabled"] = False
        write_json(self.root / "production/source-policy.json", self.policy_doc)
        before = self.manifest_path.read_bytes()
        with patch.object(production, "REPO", self.root):
            with self.assertRaisesRegex(SourcePolicyError, "New lesson production is paused"):
                production.claim(self.manifest_path, 1, "must-not-start")
        self.assertEqual(self.manifest_path.read_bytes(), before)

    def test_wrong_book_claim_is_rejected_before_mutation(self):
        self.document["bookId"] = "authored-medical-collection"
        write_json(self.manifest_path, self.document)
        before = self.manifest_path.read_bytes()
        with patch.object(production, "REPO", self.root):
            with self.assertRaisesRegex(SourcePolicyError, "permits only"):
                production.claim(self.manifest_path, 1, "other-book")
        self.assertEqual(self.manifest_path.read_bytes(), before)

    def test_trusted_record_without_question_is_rejected(self):
        self.records[0].pop("stem")
        self.save_reviewed_fixture()
        with self.assertRaisesRegex(SourcePolicyError, "source question"):
            SourcePolicy(self.root).evidence_for(self.document, self.document["questions"][0])

    def test_trusted_record_without_key_or_explanation_is_rejected(self):
        for missing in ("correct_answer_letter", "explanation"):
            with self.subTest(missing=missing):
                value = self.records[0].pop(missing)
                self.save_reviewed_fixture()
                with self.assertRaisesRegex(SourcePolicyError, "keyed answer.*explanation"):
                    SourcePolicy(self.root).evidence_for(self.document, self.document["questions"][0])
                self.records[0][missing] = value

    def test_changed_source_bytes_rejected_even_after_read_and_matching_id(self):
        policy = SourcePolicy(self.root)
        policy.evidence_for(self.document, self.document["questions"][0])
        self.records[0]["explanation"] = "A different explanation with the same book and question ID."
        write_json(self.root / "private-content/questions.json", self.records)
        with self.assertRaisesRegex(SourcePolicyError, "extraction SHA-256"):
            policy.evidence_for(self.document, self.document["questions"][0])

    def test_claim_persists_binding_and_matching_authoring_can_proceed(self):
        with patch.object(production, "REPO", self.root):
            result = production.claim(self.manifest_path, 1, "reviewed")
            resumed = production.claim(self.manifest_path, 2, "reviewed")
        evidence = result["questions"][0]["sourceEvidence"]
        self.assertEqual(evidence["sourceRecordSha256"], canonical_hash(self.records[0]))
        self.assertEqual(resumed["questions"][0]["sourceEvidence"], evidence)
        authored = self.authored_fixture(evidence)
        # Claiming source bytes never automatically approves a new script.
        self.assertNotIn("sourceReview", json.loads(self.manifest_path.read_text())["questions"][0])
        self.record_fixture_content_review(authored)
        draft = {"bookId": ORIGINAL_BOOK, "lessons": [authored]}
        bindings = SourcePolicy(self.root).validate_authoring(draft, draft["lessons"])
        self.assertEqual(bindings["lesson-fixture-1"], evidence)

    def test_renamed_authoring_with_fabricated_evidence_is_rejected(self):
        with patch.object(production, "REPO", self.root):
            claimed = production.claim(self.manifest_path, 1, "reviewed")
        evidence = claimed["questions"][0]["sourceEvidence"]
        evidence["sourceRecordSha256"] = "0" * 64
        draft = {"bookId": ORIGINAL_BOOK, "lessons": [
            {"id": "renamed-other-collection", "source_question_number": 1, "sourceEvidence": evidence}]}
        with self.assertRaisesRegex(SourcePolicyError, "evidence differs"):
            SourcePolicy(self.root).validate_authoring(draft, draft["lessons"])

    def test_complete_checks_source_before_audio_or_browser_validation(self):
        (self.root / "private-content/questions.json").unlink()
        lesson_path = self.root / "unverified.json"
        write_json(lesson_path, {"id": "unverified", "source": {"bookId": ORIGINAL_BOOK, "questionNumber": 1}})
        args = argparse.Namespace(question=1, lesson=lesson_path, qa_report=self.root / "qa.json",
                                  root=self.root / "web", registry=None, timing=None, batch_id=None)
        before = self.manifest_path.read_bytes()
        with patch.object(production, "REPO", self.root), patch.object(production, "verify_lesson") as verify:
            with self.assertRaisesRegex(SourcePolicyError, "source is unavailable"):
                production.complete(self.manifest_path, args)
            verify.assert_not_called()
        self.assertEqual(self.manifest_path.read_bytes(), before)

    def test_assembled_source_must_bind_claim_not_just_title_or_book(self):
        with patch.object(production, "REPO", self.root):
            claimed = production.claim(self.manifest_path, 1, "reviewed")
        authored = self.authored_fixture(claimed["questions"][0]["sourceEvidence"])
        self.record_fixture_content_review(authored)
        policy = SourcePolicy(self.root)
        ledger = policy.ledger()
        question = ledger["questions"][0]
        lesson = self.assembled_fixture(authored)
        source = lesson["source"]
        source.pop("evidenceSha256")
        with self.assertRaisesRegex(SourcePolicyError, "evidenceSha256"):
            policy.validate_lesson_source(lesson, ledger, question)
        source["evidenceSha256"] = canonical_hash(question["sourceEvidence"])
        self.assertEqual(policy.validate_lesson_source(lesson, ledger, question), question["sourceEvidence"])

    def test_copied_legitimate_evidence_does_not_approve_unrelated_weather_content(self):
        with patch.object(production, "REPO", self.root):
            claimed = production.claim(self.manifest_path, 1, "claimed-only")
        authored = self.authored_fixture(claimed["questions"][0]["sourceEvidence"])
        authored["title"] = "Cloud types"
        authored["scenes"][0]["voice_text"] = "Cumulus clouds tell a weather story."
        authored["mcq"]["stem"] = "What kind of cloud is this?"
        policy = SourcePolicy(self.root)
        ledger = policy.ledger()
        lesson = self.assembled_fixture(authored)
        with self.assertRaisesRegex(SourcePolicyError, "actual source-content review"):
            policy.validate_authoring({"bookId": ORIGINAL_BOOK}, [authored])
        with self.assertRaisesRegex(SourcePolicyError, "actual source-content review"):
            policy.validate_lesson_source(lesson, ledger, ledger["questions"][0])
        with self.assertRaisesRegex(SourcePolicyError, "actual source-content review"):
            production.expected_content(ledger["questions"][0], lesson, [])

    def test_reviewed_script_and_quiz_changes_require_new_source_comparison(self):
        with patch.object(production, "REPO", self.root):
            claimed = production.claim(self.manifest_path, 1, "reviewed")
        authored = self.authored_fixture(claimed["questions"][0]["sourceEvidence"])
        self.record_fixture_content_review(authored)
        for field in ("title", "narration", "caption", "locus", "question", "answer", "explanation"):
            changed = copy.deepcopy(authored)
            if field == "title": changed["title"] = "Cloud types"
            elif field == "narration": changed["scenes"][0]["voice_text"] = "Unreviewed weather narration."
            elif field == "caption": changed["scenes"][0]["headline"] = "Unreviewed caption"
            elif field == "locus": changed["locus"]["description"] = "A different teaching location."
            elif field == "question": changed["mcq"]["stem"] = "Unrelated weather question?"
            elif field == "answer": changed["mcq"]["correct_answer_letter"] = "A"
            else: changed["mcq"]["explanation"] = "An unreviewed explanation."
            with self.subTest(field=field), self.assertRaisesRegex(SourcePolicyError, "source-reviewed content"):
                SourcePolicy(self.root).validate_authoring({"bookId": ORIGINAL_BOOK}, [changed])

    def test_public_content_is_recomputed_even_with_copied_review_hash(self):
        with patch.object(production, "REPO", self.root):
            claimed = production.claim(self.manifest_path, 1, "reviewed")
        authored = self.authored_fixture(claimed["questions"][0]["sourceEvidence"])
        ledger = self.record_fixture_content_review(authored)
        question = ledger["questions"][0]
        lesson = self.assembled_fixture(authored)
        self.assertEqual(content_fingerprints(lesson), content_fingerprints(authored, authoring=True))
        lesson["scenes"][0]["transcript"] = "Unrelated weather narration."
        lesson["source"]["authoredContentSha256"] = question["sourceReview"]["authoredContentSha256"]
        with self.assertRaisesRegex(SourcePolicyError, "source-reviewed content"):
            SourcePolicy(self.root).validate_lesson_source(lesson, ledger, question)
        with self.assertRaisesRegex(SourcePolicyError, "source-reviewed content"):
            production.expected_content(question, lesson, [])

    def test_review_must_bind_exact_source_and_record_completed_checks(self):
        with patch.object(production, "REPO", self.root):
            claimed = production.claim(self.manifest_path, 1, "reviewed")
        authored = self.authored_fixture(claimed["questions"][0]["sourceEvidence"])
        ledger = self.record_fixture_content_review(authored)
        original = ledger["questions"][0]
        for key, value in (("evidenceSha256", "0" * 64), ("sourceRecordSha256", "0" * 64),
                           ("reviewer", ""), ("keyedAnswerChecked", False), ("reviewedAt", "2026-11-07")):
            question = copy.deepcopy(original)
            question["sourceReview"][key] = value
            with self.subTest(key=key), self.assertRaises(SourcePolicyError):
                validate_content_review(question, authored, original["sourceEvidence"], authoring=True)


class PublishedReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lessons = [l for l in json.loads((ROOT / "web/data/lessons.json").read_text())
                       if l.get("source", {}).get("bookId") == ORIGINAL_BOOK]

    def test_all_three_exact_published_lessons_repackage_without_private_book(self):
        self.assertEqual({l["source"]["questionNumber"] for l in self.lessons}, {5, 54, 182})
        validate_pack(self.lessons, ROOT / "web")

    def test_wrong_and_mixed_books_cannot_be_packaged(self):
        wrong = copy.deepcopy(self.lessons[0])
        wrong["source"]["bookId"] = "original-reference-collection"
        for lessons in ([wrong], [self.lessons[1], wrong]):
            with self.subTest(count=len(lessons)), self.assertRaisesRegex(SourcePolicyError, "permits only"):
                validate_pack(lessons, ROOT / "web")

    def test_modified_published_lesson_is_not_grandfathered(self):
        lesson = copy.deepcopy(self.lessons[0])
        lesson["scenes"][0]["transcript"] += " Unreviewed added claim."
        with self.assertRaisesRegex(SourcePolicyError, "lesson bytes changed"):
            validate_pack([lesson], ROOT / "web")

    def test_changed_published_media_is_not_grandfathered(self):
        lesson = self.lessons[0]
        policy = SourcePolicy()
        ledger = policy.ledger()
        record = next(q for q in ledger["questions"] if q["number"] == lesson["source"]["questionNumber"])
        validation = policy.published_validation(lesson, ledger, record)
        with tempfile.TemporaryDirectory() as temp:
            web = Path(temp)
            for name in validation["mediaSha256"]:
                target = web / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / "web" / name, target)
            audio = web / lesson["audioUrl"]
            audio.write_bytes(audio.read_bytes() + b"changed")
            with self.assertRaisesRegex(SourcePolicyError, "media changed"):
                validate_pack([lesson], web)

    def test_original_three_pack_cli_remains_usable(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "original-three.zip"
            command = [sys.executable, str(ROOT / "tools/build_pack.py"), "--output", str(output)]
            for lesson in self.lessons:
                command += ["--lesson", lesson["id"]]
            run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = json.loads(run.stdout)
            self.assertEqual(report["lessonCount"], 3)
            self.assertTrue(report["allPayloadHashesVerified"])

    def test_wrong_book_pack_cli_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as temp:
            lessons = copy.deepcopy(self.lessons)
            lessons[-1]["source"]["bookId"] = "independent-reference-book"
            source = Path(temp) / "mixed.json"
            output = Path(temp) / "must-not-exist.zip"
            write_json(source, lessons)
            run = subprocess.run([sys.executable, str(ROOT / "tools/build_pack.py"),
                                  "--input", str(source), "--output", str(output)],
                                 cwd=ROOT, text=True, capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("Source policy permits only", run.stderr)
            self.assertFalse(output.exists())

    def test_same_book_id_cannot_ship_false_publication_metadata(self):
        books = json.loads((ROOT / "web/data/books.json").read_text())
        ledger = SourcePolicy().ledger()
        validate_publications(books, ledger)
        for field, value in (("id", "other-book"), ("title", "A counterfeit title"),
                             ("author", "Another author"), ("year", 2099), ("totalQuestions", 20),
                             ("completedVideos", 200), ("completedQuestionNumbers", list(range(1, 201)))):
            changed = copy.deepcopy(books)
            changed[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(SourcePolicyError, "Publication"):
                validate_publications(changed, ledger)

    def test_claim_status_lag_is_allowed_without_false_produced_cells(self):
        books = json.loads((ROOT / "web/data/books.json").read_text())
        ledger = SourcePolicy().ledger()
        ready = next(q for q in ledger["questions"] if q["status"] == "ready")
        ready["status"] = "claimed"
        validate_publications(books, ledger)
        for status, lesson_id in (("produced", "unreviewed-lesson"), ("needs_review", None)):
            changed = copy.deepcopy(books)
            cell = next(q for q in changed[0]["questions"] if q["number"] == ready["number"])
            cell.update(status=status, lessonId=lesson_id)
            with self.subTest(status=status), self.assertRaisesRegex(SourcePolicyError, "Publication question"):
                validate_publications(changed, ledger)
        changed = copy.deepcopy(books)
        produced = next(q for q in changed[0]["questions"] if q["status"] == "produced")
        produced["lessonId"] = "a-different-lesson"
        with self.assertRaisesRegex(SourcePolicyError, "Publication question"):
            validate_publications(changed, ledger)

    def test_custom_books_cli_blocks_false_title_and_progress_before_writing_zip(self):
        books = json.loads((ROOT / "web/data/books.json").read_text())
        for field, value in (("title", "Unrelated original collection"), ("completedVideos", 200)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                changed = copy.deepcopy(books)
                changed[0][field] = value
                custom = Path(temp) / "false-books.json"
                output = Path(temp) / "must-not-exist.zip"
                write_json(custom, changed)
                run = subprocess.run([sys.executable, str(ROOT / "tools/build_pack.py"),
                                      "--books", str(custom), "--output", str(output)],
                                     cwd=ROOT, text=True, capture_output=True)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn("Source policy: Publication", run.stderr)
                self.assertFalse(output.exists())

    def test_off_book_audio_is_blocked_before_loading_speech_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            draft = Path(temp) / "wrong-source.json"
            write_json(draft, {"bookId": "other-book", "lessons": [{"id": "other-audio"}]})
            run = subprocess.run([sys.executable, str(ROOT / "tools/generate_audio.py"),
                                  "--input", str(draft), "--force"], cwd=ROOT, text=True, capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("Source policy permits only", run.stderr)
            self.assertNotIn("Loading local Kokoro", run.stdout)


if __name__ == "__main__":
    unittest.main()
