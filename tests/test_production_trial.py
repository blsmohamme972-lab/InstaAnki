"""A finite user-authorized trial never resumes production for other questions."""
import argparse
import copy
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import production
from source_policy import ORIGINAL_BOOK, SourcePolicy, SourcePolicyError, canonical_hash, content_fingerprints


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


class LimitedProductionTrialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.batch = "synthetic-three-question-trial"
        self.records = [{
            "id": f"{ORIGINAL_BOOK}-q{number:03d}", "source_question_number": number,
            "stem": f"Synthetic question {number}?",
            "options": [{"label": "A", "text": "First synthetic choice"}, {"label": "B", "text": "Second synthetic choice"}],
            "correct_answer_letter": "B", "explanation": "Synthetic source explanation for a policy regression test.",
            "source_question_pages": [{"printed_page": 2}], "source_answer_pages": [{"printed_page": 71}],
        } for number in range(1, 10)]
        source = self.root / "private-content/questions.json"
        write_json(source, self.records)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        write_json(self.root / "private-content/book-metadata.json", {"id": ORIGINAL_BOOK})
        self.policy_path = self.root / "production/source-policy.json"
        self.policy_document = {
            "schemaVersion": 1, "activeBookId": ORIGINAL_BOOK,
            "source": {"questionsFile": "private-content/questions.json", "metadataFile": "private-content/book-metadata.json", "questionsSha256": digest},
            "publishedSourceRecords": {}, "publishedRevisionReports": [], "newProductionEnabled": False,
            "productionTrial": {
                "schemaVersion": 1, "status": "active", "bookId": ORIGINAL_BOOK,
                "batchId": self.batch, "questionNumbers": [3, 6, 9], "maxNewLessons": 3,
                "authorizationText": "Synthetic test authorization for exactly three fixture questions.",
                "authorizedAt": datetime.now(timezone.utc).isoformat(),
            },
        }
        write_json(self.policy_path, self.policy_document)
        self.ledger_path = self.root / "production/books" / f"{ORIGINAL_BOOK}.json"
        self.ledger = {
            "schemaVersion": 1, "bookId": ORIGINAL_BOOK, "totalQuestions": 9,
            "completedVideos": 0, "completedQuestionNumbers": [], "source": {"extractionSha256": digest},
            "questions": [{"number": number, "id": self.records[number - 1]["id"],
                           "status": "needs_review" if number in (1, 2) else "ready",
                           "batchId": None, "lessonId": None} for number in range(1, 10)],
        }
        write_json(self.ledger_path, self.ledger)

    def claim(self, count=3, batch=None):
        with patch.object(production, "REPO", self.root):
            return production.claim(self.ledger_path, count, batch or self.batch)

    def cli(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(production, "REPO", self.root), patch.object(sys, "argv", ["production.py", *arguments]), redirect_stdout(output), redirect_stderr(errors):
            code = production.main()
        return code, json.loads(output.getvalue() or errors.getvalue())

    def authored_and_assembled(self, number, *, add_review=True):
        ledger = json.loads(self.ledger_path.read_text())
        question = next(item for item in ledger["questions"] if item["number"] == number)
        evidence = SourcePolicy(self.root).evidence_for(ledger, question)
        question.update(sourceEvidence=evidence, batchId=self.batch)
        authored = {
            "id": f"synthetic-q{number:03d}", "source_question_number": number, "sourceEvidence": evidence,
            "title": "A reviewed synthetic lesson", "locus": {"id": "synthetic-room"},
            "scenes": [{"id": "scene-1", "headline": "Synthetic idea", "voice_text": "Synthetic explanation."}],
            "mcq": {"stem": self.records[number - 1]["stem"], "options": copy.deepcopy(self.records[number - 1]["options"]),
                    "correct_answer_letter": "B", "explanation": self.records[number - 1]["explanation"]},
        }
        if add_review:
            question["sourceReview"] = {
                "schemaVersion": 1, "reviewedAt": datetime.now(timezone.utc).isoformat(),
                "reviewer": "Synthetic unit-test reviewer", "notes": "A synthetic comparison fixture; no real medical review is asserted.",
                "sourceQuestionChecked": True, "keyedAnswerChecked": True, "explanationChecked": True,
                "sourceRecordSha256": evidence["sourceRecordSha256"], "evidenceSha256": canonical_hash(evidence),
                **content_fingerprints(authored, authoring=True),
            }
        write_json(self.ledger_path, ledger)
        assembled = {
            "id": authored["id"], "title": authored["title"], "locus": copy.deepcopy(authored["locus"]),
            "scenes": [{"id": "scene-1", "caption": "Synthetic idea", "transcript": "Synthetic explanation."}],
            "quiz": {"prompt": authored["mcq"]["stem"], "options": [item["text"] for item in authored["mcq"]["options"]],
                     "correctIndex": 1, "explanation": authored["mcq"]["explanation"]},
            "source": {"bookId": ORIGINAL_BOOK, "questionNumber": number, "questionId": evidence["questionId"],
                       "evidenceSha256": canonical_hash(evidence)},
        }
        return authored, assembled

    def test_claim_owns_exact_selected_questions_and_preserves_every_other_record(self):
        before = {item["number"]: copy.deepcopy(item) for item in self.ledger["questions"]}
        result = self.claim()
        self.assertEqual([item["number"] for item in result["questions"]], [3, 6, 9])
        saved = json.loads(self.ledger_path.read_text())
        self.assertEqual(saved["batches"][self.batch]["questionNumbers"], [3, 6, 9])
        self.assertEqual(saved["completedVideos"], 0)
        for item in saved["questions"]:
            if item["number"] not in (3, 6, 9):
                self.assertEqual(item, before[item["number"]])
        self.assertFalse(json.loads(self.policy_path.read_text())["newProductionEnabled"])

    def test_next_and_status_expose_finite_scope_without_general_unpause(self):
        code, result = self.cli("next", "--count", "10")
        self.assertEqual(code, 0)
        self.assertEqual([item["number"] for item in result["questions"]], [3, 6, 9])
        self.assertEqual(result["sourcePolicy"]["authorizedQuestionNumbers"], [3, 6, 9])
        self.assertFalse(result["sourcePolicy"]["generalNewProductionEnabled"])
        self.assertEqual(result["sourcePolicy"]["maxNewLessons"], 3)

    def test_wrong_count_wrong_batch_and_default_count_cannot_broaden_the_claim(self):
        before = self.ledger_path.read_bytes()
        for count in (1, 4, 10):
            with self.subTest(count=count), self.assertRaisesRegex(production.ProductionError, "exact 3-question selection"):
                self.claim(count=count)
        with self.assertRaisesRegex(SourcePolicyError, "exact authorized batch"):
            self.claim(batch="a-different-batch")
        code, result = self.cli("claim", "--batch-id", self.batch)
        self.assertEqual(code, 1)
        self.assertIn("--count 3", result["error"])
        self.assertEqual(self.ledger_path.read_bytes(), before)

    def test_resume_cannot_append_or_substitute_an_unapproved_question(self):
        first, resumed = self.claim(), self.claim()
        self.assertEqual(first["questions"], resumed["questions"])
        saved = json.loads(self.ledger_path.read_text())
        saved["batches"][self.batch]["questionNumbers"] = [3, 6, 7]
        write_json(self.ledger_path, saved)
        before = self.ledger_path.read_bytes()
        with self.assertRaisesRegex(production.ProductionError, "exact limited-trial selection"):
            self.claim()
        self.assertEqual(self.ledger_path.read_bytes(), before)

    def test_a_selected_source_hold_aborts_the_whole_claim_without_substitution(self):
        self.ledger["questions"][5]["status"] = "needs_review"
        write_json(self.ledger_path, self.ledger)
        before = self.ledger_path.read_bytes()
        with self.assertRaisesRegex(SourcePolicyError, "Q6 still requires source review"):
            self.claim()
        self.assertEqual(self.ledger_path.read_bytes(), before)

    def test_invalid_scope_metadata_fails_before_any_claim(self):
        original = copy.deepcopy(self.policy_document)
        variants = [
            ("schemaVersion", True), ("status", "anything"), ("bookId", "another-book"),
            ("questionNumbers", [3, 3, 9]), ("questionNumbers", [True, 6, 9]),
            ("questionNumbers", [3, 6, 10]), ("questionNumbers", []),
            ("maxNewLessons", 4), ("maxNewLessons", True), ("batchId", "../unsafe"),
            ("authorizationText", ""), ("authorizedAt", "2026-11-07"),
        ]
        before = self.ledger_path.read_bytes()
        for key, value in variants:
            document = copy.deepcopy(original)
            document["productionTrial"][key] = value
            write_json(self.policy_path, document)
            with self.subTest(key=key, value=value), self.assertRaises(SourcePolicyError):
                self.claim()
            self.assertEqual(self.ledger_path.read_bytes(), before)
        document = copy.deepcopy(original)
        document["newProductionEnabled"] = True
        write_json(self.policy_path, document)
        with self.assertRaisesRegex(SourcePolicyError, "keep general new production paused"):
            self.claim()

    def test_selected_authoring_still_requires_source_and_content_review(self):
        self.claim()
        authored, _ = self.authored_and_assembled(3, add_review=False)
        with self.assertRaisesRegex(SourcePolicyError, "actual source-content review"):
            SourcePolicy(self.root).validate_authoring({"bookId": ORIGINAL_BOOK}, [authored])
        authored, _ = self.authored_and_assembled(3)
        self.assertEqual(set(SourcePolicy(self.root).validate_authoring({"bookId": ORIGINAL_BOOK}, [authored])), {authored["id"]})
        authored["scenes"][0]["voice_text"] = "A changed and unreviewed statement."
        with self.assertRaisesRegex(SourcePolicyError, "source-reviewed content"):
            SourcePolicy(self.root).validate_authoring({"bookId": ORIGINAL_BOOK}, [authored])
        (self.root / "private-content/questions.json").unlink()
        with self.assertRaisesRegex(SourcePolicyError, "source is unavailable"):
            SourcePolicy(self.root).validate_authoring({"bookId": ORIGINAL_BOOK}, [authored])

    def test_legitimate_evidence_and_reviews_do_not_authorize_a_fourth_question(self):
        self.claim()
        authored, assembled = self.authored_and_assembled(7)
        policy = SourcePolicy(self.root)
        ledger = policy.ledger()
        question = next(item for item in ledger["questions"] if item["number"] == 7)
        with self.assertRaisesRegex(SourcePolicyError, "outside the explicitly authorized"):
            policy.validate_authoring({"bookId": ORIGINAL_BOOK}, [authored])
        with self.assertRaisesRegex(SourcePolicyError, "outside the explicitly authorized"):
            policy.validate_lesson_source(assembled, ledger, question)
        candidate = self.root / "fourth.json"
        write_json(candidate, assembled)
        args = argparse.Namespace(question=7, lesson=candidate, qa_report=self.root / "qa.json",
                                  root=self.root / "web", registry=None, timing=None, batch_id=self.batch)
        before = self.ledger_path.read_bytes()
        with patch.object(production, "REPO", self.root), patch.object(production, "verify_lesson") as verify, self.assertRaisesRegex(SourcePolicyError, "outside the explicitly authorized"):
            production.complete(self.ledger_path, args)
        verify.assert_not_called()
        self.assertEqual(self.ledger_path.read_bytes(), before)

    def test_paused_or_completed_trial_cannot_start_or_finish_unproduced_work(self):
        self.claim()
        authored, assembled = self.authored_and_assembled(3)
        for state in ("paused", "completed"):
            self.policy_document["productionTrial"]["status"] = state
            write_json(self.policy_path, self.policy_document)
            with self.subTest(state=state), self.assertRaisesRegex(SourcePolicyError, "trial is not active"):
                self.claim()
            with self.assertRaisesRegex(SourcePolicyError, "trial is not active"):
                SourcePolicy(self.root).validate_authoring({"bookId": ORIGINAL_BOOK}, [authored])
            ledger = SourcePolicy(self.root).ledger()
            with self.assertRaisesRegex(SourcePolicyError, "trial is not active"):
                SourcePolicy(self.root).validate_lesson_source(assembled, ledger, ledger["questions"][2])
            code, result = self.cli("next", "--count", "10")
            self.assertEqual(code, 0)
            self.assertEqual(result["questions"], [])
            self.assertTrue(result["sourcePolicy"]["newProductionBlocked"])

    def test_direct_trial_completion_cannot_omit_the_narrated_gallery(self):
        self.claim()
        _, assembled = self.authored_and_assembled(3)
        candidate = self.root / "without-ending.json"
        write_json(candidate, assembled)
        args = argparse.Namespace(question=3, lesson=candidate, qa_report=self.root / "qa.json",
                                  root=self.root / "web", registry=None, timing=None, batch_id=self.batch)
        before = self.ledger_path.read_bytes()
        with patch.object(production, "REPO", self.root), patch.object(production, "verify_lesson") as verify, self.assertRaisesRegex(production.ProductionError, "three-image gallery and measured narrated recap"):
            production.complete(self.ledger_path, args)
        verify.assert_not_called()
        self.assertEqual(self.ledger_path.read_bytes(), before)

    def test_exact_completed_trial_content_can_replay_after_the_scope_closes(self):
        self.claim()
        _, assembled = self.authored_and_assembled(3)
        ledger = json.loads(self.ledger_path.read_text())
        question = ledger["questions"][2]
        question.update(status="produced", lessonId=assembled["id"], qaReport={"sourceChecked": True})
        question["productionValidation"] = {
            "sourceEvidenceSha256": canonical_hash(question["sourceEvidence"]),
            "sourceReviewSha256": canonical_hash(question["sourceReview"]),
        }
        write_json(self.ledger_path, ledger)
        self.policy_document["productionTrial"]["status"] = "completed"
        write_json(self.policy_path, self.policy_document)
        policy = SourcePolicy(self.root)
        # Asset integrity is separately exercised by the published/reviewed
        # content tests; this test isolates the authorization boundary only.
        with patch.object(policy, "verify_frozen_assets") as verify:
            policy.validate_pack([assembled], self.root / "web")
        verify.assert_called_once_with(assembled, question["productionValidation"], self.root / "web")
        with self.assertRaisesRegex(SourcePolicyError, "not a completed"):
            policy.validate_pack([{**assembled, "source": {**assembled["source"], "questionNumber": 7}}], self.root / "web")


if __name__ == "__main__":
    unittest.main()
