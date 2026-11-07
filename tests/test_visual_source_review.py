"""Gallery and recap edits cannot retain an earlier source-content approval."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from assemble_book_batch import audio_input
import production
from source_policy import (ORIGINAL_BOOK, SourcePolicy, SourcePolicyError,
                           canonical_hash, content_fingerprints, validate_content_review)
import test_source_policy as source_fixtures


class VisualSourceReviewTests(unittest.TestCase):
    def setUp(self):
        # Reuse only the isolated synthetic evidence fixture, not a real book or
        # existing user review. No production-media or QA assertion is fabricated.
        fixture = source_fixtures.SourceEvidenceTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        with patch.object(production, "REPO", fixture.root):
            claimed = production.claim(fixture.manifest_path, 2, "synthetic-visual-review")
        self.evidence = claimed["questions"][0]["sourceEvidence"]
        self.authored = fixture.authored_fixture(self.evidence)
        self.core_fingerprints = content_fingerprints(self.authored, authoring=True)
        self.authored.update({
            "audioLessonId": "synthetic-reviewed-audio",
            "realImages": [{
                "url": f"media/real/synthetic-{index}.png", "title": f"Synthetic image {index}",
                "caption": f"Reviewed synthetic caption {index}.", "author": "Synthetic author",
                "license": "CC0 1.0", "sourceUrl": f"https://example.org/fixture/{index}",
                "licenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
                "attribution": "Synthetic public attribution.", "aiGenerated": False,
                "sha256": f"{index:064x}",
            } for index in (1, 2, 3)],
            "presentationPlan": {"schemaVersion": 1, "endingSceneId": "scene-1", "recap": {
                "nodes": [{"id": "first", "label": "First reviewed point"},
                          {"id": "second", "label": "Second reviewed point"}],
                "edges": [{"from": "first", "to": "second"}],
                "cueBindings": [{"phraseId": "synthetic-p1", "nodeId": "first"},
                                {"phraseId": "synthetic-p2", "nodeId": "second"}],
            }},
        })
        self.authored["realImage"] = copy.deepcopy(self.authored["realImages"][0])
        self.ledger = fixture.record_fixture_content_review(self.authored)
        self.question = self.ledger["questions"][0]
        self.assembled = fixture.assembled_fixture(self.authored)
        recap = copy.deepcopy(self.authored["presentationPlan"]["recap"])
        recap.update(startSeconds=50, endSeconds=64)
        for index, binding in enumerate(recap["cueBindings"]):
            binding.update(startSeconds=50 + index * 7, endSeconds=57 + index * 7)
        self.assembled.update({
            "realImages": copy.deepcopy(self.authored["realImages"]),
            "presentation": {"schemaVersion": 1, "effectiveEndSeconds": 64,
                             "narrationEndSeconds": 64, "recap": recap,
                             "clinicalGallery": {"startSeconds": 50, "endSeconds": 64,
                                                 "images": copy.deepcopy(self.authored["realImages"])}},
        })

    def review(self, lesson, *, authoring=False, question=None):
        return validate_content_review(question or self.question, lesson, self.evidence, authoring=authoring)

    def test_exact_authored_visual_hash_matches_measured_public_presentation(self):
        expected = canonical_hash({"realImages": self.authored["realImages"],
                                   "recap": self.authored["presentationPlan"]["recap"]})
        authored_hashes = content_fingerprints(self.authored, authoring=True)
        self.assertEqual(authored_hashes["visualSupplementSha256"], expected)
        self.assertEqual(authored_hashes, content_fingerprints(self.assembled))
        self.assertEqual({key: authored_hashes[key] for key in self.core_fingerprints}, self.core_fingerprints)
        self.review(self.authored, authoring=True)
        self.review(self.assembled)
        policy = SourcePolicy(self.fixture.root)
        policy.validate_authoring({"bookId": ORIGINAL_BOOK}, [self.authored])
        policy.validate_lesson_source(self.assembled, self.ledger, self.question)

    def test_caption_provenance_node_edge_and_phrase_changes_invalidate_approval(self):
        for authoring, source in ((True, self.authored), (False, self.assembled)):
            for change in ("caption", "provenance", "node", "edge", "binding"):
                lesson = copy.deepcopy(source)
                recap = lesson["presentationPlan" if authoring else "presentation"]["recap"]
                if change == "caption":
                    lesson["realImages"][0]["caption"] = "An unreviewed image caption."
                elif change == "provenance":
                    lesson["realImages"][0]["license"] = "Different unreviewed provenance"
                elif change == "node":
                    recap["nodes"][0]["label"] = "An unreviewed teaching statement"
                elif change == "edge":
                    recap["edges"][0] = {"from": "second", "to": "first"}
                else:
                    recap["cueBindings"][0]["nodeId"] = "second"
                if not authoring:
                    # Even matching edits in both displayed and registered image
                    # records cannot escape the retained source review hash.
                    lesson["presentation"]["clinicalGallery"]["images"] = copy.deepcopy(lesson["realImages"])
                with self.subTest(authoring=authoring, change=change), self.assertRaisesRegex(SourcePolicyError, "visualSupplementSha256"):
                    self.review(lesson, authoring=authoring)

    def test_deleting_visual_fields_cannot_bypass_an_existing_review_binding(self):
        for authoring, source in ((True, self.authored), (False, self.assembled)):
            field = "presentationPlan" if authoring else "presentation"
            for missing in ("realImages", "presentation", "both", "recap", "nodes", "edges", "cueBindings"):
                lesson = copy.deepcopy(source)
                if missing in ("realImages", "both"):
                    del lesson["realImages"]
                if missing in ("presentation", "both"):
                    del lesson[field]
                if missing == "recap":
                    del lesson[field]["recap"]
                if missing in ("nodes", "edges", "cueBindings"):
                    del lesson[field]["recap"][missing]
                with self.subTest(authoring=authoring, missing=missing), self.assertRaisesRegex(SourcePolicyError, "visualSupplementSha256"):
                    self.review(lesson, authoring=authoring)

    def test_presentation_requires_review_hash_even_if_the_old_core_hashes_match(self):
        for absent in (True, False):
            question = copy.deepcopy(self.question)
            if absent:
                del question["sourceReview"]["visualSupplementSha256"]
            else:
                question["sourceReview"]["visualSupplementSha256"] = None
            for authoring, lesson in ((True, self.authored), (False, self.assembled)):
                with self.subTest(absent=absent, authoring=authoring), self.assertRaisesRegex(SourcePolicyError, "visualSupplementSha256"):
                    self.review(lesson, authoring=authoring, question=question)

    def test_displayed_gallery_cannot_diverge_from_reviewed_registered_images(self):
        lesson = copy.deepcopy(self.assembled)
        lesson["presentation"]["clinicalGallery"]["images"][0]["caption"] = "Unreviewed display-only caption."
        with self.assertRaisesRegex(SourcePolicyError, "displayed gallery"):
            self.review(lesson)
        del lesson["presentation"]["clinicalGallery"]
        with self.assertRaisesRegex(SourcePolicyError, "displayed gallery"):
            self.review(lesson)

    def test_only_measured_recap_times_are_excluded_from_the_source_fingerprint(self):
        lesson = copy.deepcopy(self.assembled)
        lesson["presentation"]["recap"]["startSeconds"] += .25
        lesson["presentation"]["recap"]["endSeconds"] += .25
        for binding in lesson["presentation"]["recap"]["cueBindings"]:
            binding["startSeconds"] += .25
            binding["endSeconds"] += .25
        self.assertEqual(content_fingerprints(lesson), content_fingerprints(self.assembled))
        # Timing validity remains an independent presentation/media gate. An
        # unknown authored-content field must not be silently ignored instead.
        lesson["presentation"]["recap"]["extraTeaching"] = "Unreviewed content"
        with self.assertRaisesRegex(SourcePolicyError, "unexpected authored recap"):
            self.review(lesson)

    def test_audio_authoring_preserves_visual_binding_without_changing_spoken_content(self):
        audio_document = audio_input({"lessons": [self.authored]})
        audio = audio_document["lessons"][0]
        self.assertEqual(audio["id"], self.authored["audioLessonId"])
        self.assertEqual(audio["lessonId"], self.authored["id"])
        self.assertEqual(audio["realImages"], self.authored["realImages"])
        self.assertEqual(audio["presentationPlan"], self.authored["presentationPlan"])
        self.assertEqual(audio["scenes"], self.authored["scenes"])
        self.assertEqual(content_fingerprints(audio, authoring=True), content_fingerprints(self.authored, authoring=True))
        SourcePolicy(self.fixture.root).validate_audio_authoring(audio_document, [audio])
        audio["realImages"][0]["caption"] = "Changed only in the prepared audio input"
        self.assertNotEqual(audio["realImages"], self.authored["realImages"])
        with self.assertRaisesRegex(SourcePolicyError, "visualSupplementSha256"):
            SourcePolicy(self.fixture.root).validate_audio_authoring(audio_document, [audio])

    def test_older_audio_input_cannot_drop_already_reviewed_visual_content(self):
        document = audio_input({"lessons": [self.authored]})
        audio = document["lessons"][0]
        del audio["realImages"]
        del audio["presentationPlan"]
        with self.assertRaisesRegex(SourcePolicyError, "missing its reviewed visualSupplementSha256"):
            SourcePolicy(self.fixture.root).validate_audio_authoring(document, [audio])


class ImmutablePublishedVisualReplayTests(unittest.TestCase):
    def test_exact_old_published_replay_uses_immutable_approval_without_private_source(self):
        lessons = json.loads((ROOT / "web/data/lessons.json").read_text())
        policy = SourcePolicy(ROOT)
        # Isolate the changed review boundary. Actual media integrity remains
        # covered by existing replay tests and is not changed by this feature.
        with patch.object(policy, "verify_frozen_assets") as assets, patch(
                "source_policy.validate_content_review", side_effect=AssertionError("Legacy replay must use frozen approval")):
            policy.validate_pack(lessons, ROOT / "web")
        self.assertEqual(assets.call_count, 3)

    def test_old_published_caption_or_map_edits_still_fail_immutable_replay(self):
        original = json.loads((ROOT / "web/data/lessons.json").read_text())[0]
        for field in ("caption", "node", "binding"):
            lesson = copy.deepcopy(original)
            if field == "caption":
                lesson["realImages"][0]["caption"] = "An unreviewed replacement caption."
            elif field == "node":
                lesson["presentation"]["recap"]["nodes"][0]["label"] = "Changed map label"
            else:
                lesson["presentation"]["recap"]["cueBindings"][0]["nodeId"] = "changed-node"
            with self.subTest(field=field), self.assertRaisesRegex(SourcePolicyError, "lesson bytes changed"):
                SourcePolicy(ROOT).validate_pack([lesson], ROOT / "web")


if __name__ == "__main__":
    unittest.main()
