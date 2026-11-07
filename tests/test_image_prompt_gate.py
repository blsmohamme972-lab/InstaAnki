"""Synthetic-only checks for exact reviewed prompts before an external image tool.

No test visits the reference sites, approves real artwork, generates images, or
changes production records. Review assertions exist only in temporary fixtures.
"""
import copy
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import prepare_image_prompt as gate
import production
from source_policy import ORIGINAL_BOOK, SourcePolicyError
import test_source_policy as source_fixtures


class ImagePromptGateTests(unittest.TestCase):
    def setUp(self):
        fixture = source_fixtures.SourceEvidenceTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture, self.root = fixture, fixture.root
        with patch.object(production, "REPO", self.root):
            claim = production.claim(fixture.manifest_path, 2, "synthetic-image-review")
        self.lesson = fixture.authored_fixture(claim["questions"][0]["sourceEvidence"])
        self.lesson.update({
            "imagePrompt": "\nDraw one original flat cartoon scene with a cheerful synthetic character actively connecting the reviewed symbols.\n",
            "mnemonicSymbols": [{"symbol": "Synthetic key", "meaning": "The first synthetic fact"},
                                {"symbol": "Synthetic gate", "meaning": "The second synthetic fact"}],
            "artBrief": {
                "schemaVersion": 1, "rendering": "2d-mnemonic-cartoon",
                "objective": "Recall the two synthetic facts in the source fixture.",
                "story": "A cheerful character uses the key to open the gate.",
                "styleNotes": "Readable ink contours, flat colors and an expressive cartoon character.",
                "composition": "One connected scene with both large symbols visible on a phone.",
                "locusUse": "The existing locus appears as a small contextual landmark.",
                "overlayPlan": "Keep exact text and arrows for controlled runtime overlays.",
                "symbolActions": [
                    {"symbol": "Synthetic key", "meaning": "The first synthetic fact", "action": "The character turns the key.",
                     "recallCue": "The key recalls the first synthetic fact through the stated association.",
                     "position": "Left center", "narrationCue": "First reviewed phrase"},
                    {"symbol": "Synthetic gate", "meaning": "The second synthetic fact", "action": "The gate opens as the key turns.",
                     "recallCue": "Opening the gate recalls the second synthetic fact.",
                     "position": "Right center", "narrationCue": "Second reviewed phrase"},
                ],
            },
        })
        fixture.record_fixture_content_review(self.lesson)
        ledger = json.loads(fixture.manifest_path.read_text())
        ledger["questions"][0]["sourceReview"]["reviewedAt"] = "2025-01-01T10:00:00Z"
        fixture.manifest_path.write_text(json.dumps(ledger))
        self.draft_path = self.root / "private-content/image-draft.json"
        self.review_path = self.root / "private-content/image-review.json"
        self.output = self.root / "private-content/ready-prompt.json"
        for relative in gate.SPEC_FILES:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Synthetic specification version 2.0.0. No actual reference review is claimed.\n")
        self.save_draft()
        self.review = self.approved_fixture()
        self.save_review()

    def save_draft(self):
        self.draft_path.write_text(json.dumps({"bookId": ORIGINAL_BOOK, "lessons": [self.lesson]}))

    def request(self):
        return gate.prepare_request(self.root, self.draft_path, self.lesson["id"])

    def approved_fixture(self):
        return {
            "schemaVersion": 1, "lessonId": self.lesson["id"], "requestSha256": self.request()["requestSha256"],
            "reviewer": "Synthetic test reviewer", "reviewedAt": "2025-01-01T12:00:00Z",
            "decision": "approved", "notes": "Synthetic approval data for an isolated test, never an actual reference or artwork review.",
            "checks": {name: True for name in gate.CHECKS},
            "references": [{
                "provider": provider, "pageUrl": f"https://www.{domain}/synthetic-public-example",
                "exampleUrl": f"https://media.{domain}/synthetic-example.png", "exampleKind": "image",
                "inspectionScope": "complete-scene", "linkedFromPage": f"https://www.{domain}/synthetic-public-example",
                "linkEvidence": "Synthetic example link is recorded inside this synthetic official-page fixture only.",
                "access": "public", "inspectionStatus": "inspected", "inspectedAt": "2025-01-01T11:00:00+00:00",
                "observations": "Synthetic visible outlines and character action demonstrate a connected visual story here.",
                "appliedMethod": "Apply the synthetic observed interaction by connecting both reviewed symbols in this scene.",
            } for provider, domain in gate.PROVIDERS.items()],
        }

    def save_review(self):
        self.review_path.write_text(json.dumps(self.review))

    def emit(self):
        return gate.emit(self.root, self.draft_path, self.lesson["id"], self.review_path, self.output)

    def test_fingerprint_mode_is_unapproved_read_only_and_never_creates_output(self):
        ledger_before = self.fixture.manifest_path.read_bytes()
        review_before = self.review_path.read_bytes()
        output = io.StringIO()
        with patch.object(gate, "ROOT", self.root), patch.object(sys, "argv", [
                "prepare_image_prompt", "--input", str(self.draft_path), "--lesson", self.lesson["id"], "--fingerprint"]), redirect_stdout(output):
            gate.main()
        result = json.loads(output.getvalue())
        self.assertIs(result["approved"], False)
        self.assertEqual(result["reviewStatus"], "not-evaluated")
        self.assertIs(result["imageGenerated"], False)
        self.assertEqual(set(result["styleSpec"]["documents"]), set(gate.SPEC_FILES))
        self.assertFalse(self.output.exists())
        self.assertEqual(self.fixture.manifest_path.read_bytes(), ledger_before)
        self.assertEqual(self.review_path.read_bytes(), review_before)

    def test_complete_record_emits_exact_prompt_and_receipt_without_mutating_review_or_ledger(self):
        ledger_before = self.fixture.manifest_path.read_bytes()
        review_before = self.review_path.read_bytes()
        bundle = self.emit()
        self.assertEqual(set(bundle), {"prompt", "receipt"})
        self.assertEqual(bundle["prompt"], self.lesson["imagePrompt"])
        self.assertEqual(json.loads(self.output.read_text()), bundle)
        self.assertEqual(bundle["receipt"]["requestSha256"], self.review["requestSha256"])
        self.assertIs(bundle["receipt"]["imageGenerated"], False)
        self.assertEqual(self.fixture.manifest_path.read_bytes(), ledger_before)
        self.assertEqual(self.review_path.read_bytes(), review_before)
        self.assertFalse(list(self.output.parent.glob(".image-prompt-*")))

    def test_default_and_explicit_emit_cli_use_the_same_required_gate(self):
        for mode in ([], ["--emit"]):
            with self.subTest(mode=mode), patch.object(gate, "ROOT", self.root), patch.object(sys, "argv", [
                    "prepare_image_prompt", "--input", str(self.draft_path), "--lesson", self.lesson["id"],
                    "--review", str(self.review_path), "--output", str(self.output), *mode]), redirect_stdout(io.StringIO()):
                gate.main()
            self.assertEqual(json.loads(self.output.read_text())["prompt"], self.lesson["imagePrompt"])
            self.output.unlink()

    def test_missing_false_placeholder_or_blocked_review_never_emits_partial_output(self):
        original = copy.deepcopy(self.review)
        mutations = [
            lambda r: r.update(decision="pending"),
            lambda r: r.pop("reviewer"),
            lambda r: r.update(notes="looks fine"),
            lambda r: r.update(notes="TODO replace this with actual review observations before sending anything"),
            lambda r: r["checks"].update(phoneReadable=False),
            lambda r: r["checks"].pop("allThreeReferencesVisuallyInspected"),
            lambda r: r["references"].pop(),
            lambda r: r["references"].append(copy.deepcopy(r["references"][0])),
            lambda r: r["references"][0].update(inspectionStatus="blocked"),
            lambda r: r["references"][0].update(access="login-required"),
            lambda r: r["references"][0].update(observations="A cartoon"),
            lambda r: r["references"][0].update(appliedMethod="Same style"),
        ]
        ledger_before = self.fixture.manifest_path.read_bytes()
        for mutate in mutations:
            self.review = copy.deepcopy(original)
            mutate(self.review)
            self.save_review()
            with self.subTest(mutation=mutate), self.assertRaises(gate.PromptReviewError):
                self.emit()
            self.assertFalse(self.output.exists())
            self.assertFalse(list(self.output.parent.glob(".image-prompt-*")))
            self.assertEqual(self.fixture.manifest_path.read_bytes(), ledger_before)

    def test_prompt_brief_symbols_locus_source_review_and_spec_changes_invalidate_approval(self):
        original = copy.deepcopy(self.lesson)
        ledger_before = self.fixture.manifest_path.read_bytes()
        mutations = {
            "prompt": lambda d: d.update(imagePrompt=d["imagePrompt"] + " Add a new visible action."),
            "brief": lambda d: d["artBrief"].update(composition="A different reviewed visual composition."),
            "symbols": lambda d: (d["mnemonicSymbols"][0].update(meaning="Another synthetic mapping"),
                                   d["artBrief"]["symbolActions"][0].update(meaning="Another synthetic mapping")),
            "locus": lambda d: d["locus"].update(description="A newly reviewed synthetic location."),
            "source-content": lambda d: d["scenes"][0].update(voice_text="A newly reviewed synthetic explanation."),
        }
        for label, mutate in mutations.items():
            self.lesson = copy.deepcopy(original)
            mutate(self.lesson)
            self.save_draft()
            # A new *synthetic* source review allows testing the separate art
            # binding rather than failing only the earlier content boundary.
            self.fixture.record_fixture_content_review(self.lesson)
            with self.subTest(field=label), self.assertRaisesRegex(gate.PromptReviewError, "stale"):
                self.emit()
            self.assertFalse(self.output.exists())
            self.fixture.manifest_path.write_bytes(ledger_before)
        self.lesson = original
        self.save_draft()
        ledger = json.loads(ledger_before)
        ledger["questions"][0]["sourceReview"]["notes"] += " Extra synthetic review detail."
        self.fixture.manifest_path.write_text(json.dumps(ledger))
        with self.assertRaisesRegex(gate.PromptReviewError, "stale"):
            self.emit()
        self.fixture.manifest_path.write_bytes(ledger_before)
        for relative in gate.SPEC_FILES:
            spec = self.root / relative
            before = spec.read_bytes()
            spec.write_bytes(before + b"Changed synthetic visual rule.\n")
            with self.subTest(spec=relative), self.assertRaisesRegex(gate.PromptReviewError, "stale"):
                self.emit()
            self.assertFalse(self.output.exists())
            spec.write_bytes(before)

    def test_source_evidence_or_scope_changes_remain_blocked_before_emission(self):
        policy_path = self.root / "production/source-policy.json"
        policy = json.loads(policy_path.read_text())
        policy["newProductionEnabled"] = False
        policy_path.write_text(json.dumps(policy))
        before = self.fixture.manifest_path.read_bytes()
        with self.assertRaisesRegex(SourcePolicyError, "paused"):
            self.emit()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.fixture.manifest_path.read_bytes(), before)
        policy["newProductionEnabled"] = True
        policy_path.write_text(json.dumps(policy))
        path = self.root / "private-content/questions.json"
        path.write_text(path.read_text() + "\n")
        with self.assertRaises(SourcePolicyError):
            self.emit()
        self.assertFalse(self.output.exists())

    def test_official_subdomains_and_grounded_external_examples_are_accepted(self):
        ref = self.review["references"][0]
        ref.update(pageUrl="https://learn.pixorize.com/synthetic-example", linkedFromPage="https://learn.pixorize.com/synthetic-example",
                   exampleUrl="https://www.youtube.com/watch?v=synthetic-fixture", exampleKind="video", inspectionScope="video-scene")
        gate.validate_review(self.request(), self.review)

    def test_homepage_only_ungrounded_lookalike_and_thumbnail_evidence_is_rejected(self):
        original = copy.deepcopy(self.review)
        mutations = [
            {"pageUrl": "https://pixorize.com.evil.example/example", "linkedFromPage": "https://pixorize.com.evil.example/example"},
            {"exampleUrl": "https://pixorize.com.evil.example/example.png"},
            {"pageUrl": "https://example.org/pixorize", "linkedFromPage": "https://example.org/pixorize"},
            {"exampleUrl": "https://www.pixorize.com/"},
            {"exampleUrl": "https://www.pixorize.com/#examples"},
            {"linkedFromPage": "https://www.pixorize.com/a-different-page"},
            {"exampleUrl": "https://www.picmonic.com/other-provider-example"},
            {"exampleKind": "thumbnail"},
            {"inspectionScope": "thumbnail-only"},
            {"inspectionScope": None},
        ]
        for change in mutations:
            self.review = copy.deepcopy(original)
            self.review["references"][0].update(change)
            self.save_review()
            with self.subTest(change=change), self.assertRaises(gate.PromptReviewError):
                self.emit()
            self.assertFalse(self.output.exists())

    def test_local_private_and_reserved_examples_cannot_claim_public_inspection(self):
        original = copy.deepcopy(self.review)
        examples = [
            "https://localhost/scene.png", "https://LOCALHOST./scene.png",
            "https://media.localhost/scene.png", "https://intranet/scene.png",
            "https://assets.local/scene.png", "https://assets.internal/scene.png",
            "https://assets.home.arpa/scene.png", "https://assets.invalid/scene.png",
            "https://assets.test/scene.png", "https://assets.example/scene.png",
            "https://example.com/scene.png", "https://example.org/scene.png",
            "https://example.net/scene.png", "https://assets.example.com/scene.png",
            "https://assets.example.org/scene.png", "https://assets.example.net/scene.png",
            "https://127.0.0.1/scene.png", "https://[::1]/scene.png",
            "https://10.42.0.5/scene.png", "https://172.16.0.9/scene.png",
            "https://192.168.1.9/scene.png", "https://169.254.169.254/scene.png",
            "https://100.64.0.1/scene.png", "https://[fd00::1]/scene.png",
            "https://2130706433/scene.png", "https://0x7f.0.0.1/scene.png",
            "https://media.pixorize.com/\x00scene.png",
        ]
        before = self.fixture.manifest_path.read_bytes()
        for example in examples:
            self.review = copy.deepcopy(original)
            self.review["references"][0]["exampleUrl"] = example
            self.save_review()
            with self.subTest(example=example), self.assertRaises(gate.PromptReviewError):
                self.emit()
            self.assertFalse(self.output.exists())
            self.assertEqual(self.fixture.manifest_path.read_bytes(), before)
        # These are syntax-only synthetic fixtures, not asserted real artwork.
        # Independent CDN hosts and globally routable addresses remain usable
        # when the reviewer actually records their official-page connection.
        for example in ("https://i.ytimg.com/vi/synthetic-fixture/scene.png",
                        "https://8.8.8.8/synthetic-scene.png"):
            review = copy.deepcopy(original)
            review["references"][0]["exampleUrl"] = example
            gate.validate_review(self.request(), review)

    def test_timestamps_require_timezones_and_completed_inspection_before_review(self):
        for field, value in (("reviewedAt", "2025-01-01T12:00:00"),
                             ("reviewedAt", "2999-01-01T12:00:00Z"),
                             ("inspectedAt", "2025-01-02T12:00:00Z"),
                             ("inspectedAt", "2025-01-01T11:00:00")):
            review = copy.deepcopy(self.review)
            target = review if field == "reviewedAt" else review["references"][0]
            target[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(gate.PromptReviewError):
                gate.validate_review(self.request(), review, now=datetime(2025, 1, 2, tzinfo=timezone.utc))
        review = copy.deepcopy(self.review)
        review["reviewedAt"] = "2025-01-01T09:00:00Z"
        for ref in review["references"]:
            ref["inspectedAt"] = "2025-01-01T08:00:00Z"
        with self.assertRaisesRegex(gate.PromptReviewError, "predate"):
            gate.validate_review(self.request(), review)

    def test_required_art_details_and_exact_symbol_mapping_cannot_be_omitted(self):
        original = copy.deepcopy(self.lesson)
        changes = [lambda d: d.pop("artBrief"), lambda d: d.update(imagePrompt=""),
                   lambda d: d["artBrief"].update(rendering="cinematic-3d"),
                   lambda d: d["artBrief"]["symbolActions"][0].update(meaning="Unmatched meaning")]
        changes += [lambda d, field=field: d["artBrief"]["symbolActions"][0].pop(field)
                    for field in ("action", "recallCue", "position", "narrationCue")]
        for change in changes:
            self.lesson = copy.deepcopy(original)
            change(self.lesson)
            self.save_draft()
            with self.subTest(change=change), self.assertRaises(gate.PromptReviewError):
                self.request()

    def test_actual_canonical_template_cannot_be_emitted_unfilled(self):
        document = (ROOT / "docs/mnemonic-image-prompt.md").read_text(encoding="utf-8")
        template = re.search(r"## Final generator prompt template.*?```text\n(.*?)\n```", document, re.S)
        self.assertIsNotNone(template, "The canonical generator template must remain identifiable.")
        self.lesson["imagePrompt"] = template.group(1)
        self.save_draft()
        ledger_before = self.fixture.manifest_path.read_bytes()
        with self.assertRaisesRegex(gate.PromptReviewError, "placeholder"):
            gate.validate_art(self.lesson)
        with self.assertRaisesRegex(gate.PromptReviewError, "placeholder"):
            self.emit()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.fixture.manifest_path.read_bytes(), ledger_before)

    def test_explicit_unfilled_markers_fail_without_rejecting_medical_brackets(self):
        self.lesson["imagePrompt"] += " Use the verified objective {{sourceObjective}} in the scene."
        self.save_draft()
        ledger_before = self.fixture.manifest_path.read_bytes()
        with self.assertRaisesRegex(gate.PromptReviewError, "placeholder"):
            self.emit()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.fixture.manifest_path.read_bytes(), ledger_before)
        self.lesson["imagePrompt"] = "Reserve a clear area for separately rendered labels such as [Na+] and [95% CI]."
        gate.validate_art(self.lesson)

    def test_completed_negative_placeholder_instruction_is_valid_but_empty_markers_are_not(self):
        self.lesson["imagePrompt"] += " Do not render placeholder text in the reserved overlay space."
        self.lesson["artBrief"]["overlayPlan"] = "Leave clean room for labels; no placeholder text is drawn in the artwork."
        self.save_draft()
        self.review["requestSha256"] = self.request()["requestSha256"]
        self.save_review()
        self.assertEqual(self.emit()["prompt"], self.lesson["imagePrompt"])
        self.output.unlink()
        before = self.fixture.manifest_path.read_bytes()
        for unfinished in ("{{}}", "{{sourceObjective}}", "PLACEHOLDER", "placeholder: write the objective later"):
            lesson = copy.deepcopy(self.lesson)
            lesson["artBrief"]["objective"] = unfinished
            with self.subTest(unfinished=unfinished), self.assertRaises(gate.PromptReviewError):
                gate.validate_art(lesson)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.fixture.manifest_path.read_bytes(), before)

    def test_private_prompt_cannot_be_emitted_into_public_or_build_trees(self):
        before = self.fixture.manifest_path.read_bytes()
        for relative in ("ready-prompt.json", "web/data/ready-prompt.json",
                         "production/ready-prompt.json", "build/fresh-web/ready-prompt.json",
                         "dist/ready-prompt.json", "private-content/../web/ready-prompt.json"):
            output = self.root / relative
            with self.subTest(relative=relative), self.assertRaisesRegex(gate.PromptReviewError, "private-content"):
                gate.emit(self.root, self.draft_path, self.lesson["id"], self.review_path, output)
            self.assertFalse(output.exists())
            self.assertEqual(self.fixture.manifest_path.read_bytes(), before)
        self.assertEqual(self.emit()["prompt"], self.lesson["imagePrompt"])

    def test_private_prompt_output_rejects_public_symlink_aliases_and_allows_external_workspace(self):
        public = self.root / "web"
        public.mkdir(exist_ok=True)
        private_alias = self.root / "private-content/public-alias"
        private_alias.symlink_to(public, target_is_directory=True)
        before = self.fixture.manifest_path.read_bytes()
        with tempfile.TemporaryDirectory(prefix="image-prompt-private-fixture-") as temporary:
            external = Path(temporary)
            public_alias = public / "external-alias"
            public_alias.symlink_to(external, target_is_directory=True)
            external_alias = external / "public-alias"
            external_alias.symlink_to(public, target_is_directory=True)
            for output in (private_alias / "ready.json", private_alias / "../ready.json",
                           public_alias / "ready.json", external_alias / "ready.json"):
                with self.subTest(output=output), self.assertRaisesRegex(gate.PromptReviewError, "private-content"):
                    gate.emit(self.root, self.draft_path, self.lesson["id"], self.review_path, output)
                self.assertFalse(output.exists())
                self.assertEqual(self.fixture.manifest_path.read_bytes(), before)
            output = external / "private-ready.json"
            result = gate.emit(self.root, self.draft_path, self.lesson["id"], self.review_path, output)
            self.assertEqual(json.loads(output.read_text()), result)
            self.assertEqual(result["prompt"], self.lesson["imagePrompt"])
            private_external = self.root / "private-content/external-private"
            private_external.symlink_to(external, target_is_directory=True)
            alias_output = private_external / "private-alias-ready.json"
            alias_result = gate.emit(self.root, self.draft_path, self.lesson["id"], self.review_path, alias_output)
            self.assertEqual(json.loads(alias_output.read_text()), alias_result)
            self.assertTrue((external / "private-alias-ready.json").is_file())

    def test_unknown_duplicate_wrong_source_and_existing_outputs_are_protected(self):
        with self.assertRaisesRegex(gate.PromptReviewError, "exactly one existing"):
            gate.prepare_request(self.root, self.draft_path, "missing-lesson")
        self.draft_path.write_text(json.dumps({"bookId": ORIGINAL_BOOK, "lessons": [self.lesson, self.lesson]}))
        with self.assertRaisesRegex(gate.PromptReviewError, "unique"):
            self.request()
        self.draft_path.write_text(json.dumps({"bookId": "another-book", "lessons": [self.lesson]}))
        with self.assertRaises(SourcePolicyError):
            self.request()
        self.save_draft()
        self.output.write_text("Existing private output must remain unchanged.")
        with self.assertRaisesRegex(gate.PromptReviewError, "already exists"):
            self.emit()
        self.assertEqual(self.output.read_text(), "Existing private output must remain unchanged.")
        ledger_before = self.fixture.manifest_path.read_bytes()
        with self.assertRaisesRegex(gate.PromptReviewError, "already exists"):
            gate.emit(self.root, self.draft_path, self.lesson["id"], self.review_path, self.fixture.manifest_path)
        self.assertEqual(self.fixture.manifest_path.read_bytes(), ledger_before)

    def test_fingerprint_cannot_be_combined_with_output_or_review(self):
        for argument, value in (("--output", self.output), ("--review", self.review_path)):
            with self.subTest(argument=argument), patch.object(sys, "argv", [
                    "prepare_image_prompt", "--input", str(self.draft_path), "--lesson", self.lesson["id"],
                    "--fingerprint", argument, str(value)]), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                gate.main()
            self.assertEqual(caught.exception.code, 2)
            self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
