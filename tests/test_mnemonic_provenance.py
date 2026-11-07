"""Synthetic checks for the fail-closed mnemonic provenance policy."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import check_mnemonic_provenance as provenance


class MnemonicProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        (self.repo / "web/data").mkdir(parents=True)
        (self.repo / "web/media/mnemonic").mkdir(parents=True)
        (self.repo / "production/qa/mnemonic-generation").mkdir(parents=True)
        self.poster = "media/mnemonic/q014.png"
        image = Image.new("RGB", (768, 1024), "#d6efe8")
        image.save(self.repo / "web" / self.poster)
        self.lesson = {"id": "book-q014", "poster": self.poster}
        self._write_lessons()

    def tearDown(self):
        self.temp.cleanup()

    def _write_lessons(self, lesson=None):
        (self.repo / "web/data/lessons.json").write_text(json.dumps([lesson or self.lesson]))

    def _digest(self):
        return hashlib.sha256((self.repo / "web" / self.poster).read_bytes()).hexdigest()

    def _receipt(self, *, generated=True):
        digest = self._digest()
        return {
            "schemaVersion": 1, "artifactKind": "image-generation", "lessonId": "book-q014",
            "poster": self.poster, "generator": "openai-imagegen", "actualCall": True,
            "imageGenerated": generated,
            "promptGate": {"requestSha256": "a" * 64},
            "outputPath": self.poster, "outputSha256": digest,
            "outputWidth": 768, "outputHeight": 1024,
            "embeddedTextDetected": False,
            "visualInspection": {
                "reviewed": True, "reviewedAt": "2026-11-07T21:00:00+00:00",
                "checks": {name: True for name in provenance.REQUIRED_VISUAL_CHECKS},
                "notes": "Exact output checked for source alignment, labels, crop and phone readability.",
            },
            "recordedAt": "2026-11-07T21:00:00+00:00",
        }

    def _write_receipt(self, receipt=None):
        path = self.repo / "production/qa/mnemonic-generation/book-q014.json"
        path.write_text(json.dumps(receipt or self._receipt()))

    def test_unchanged_media_is_skipped(self):
        result = provenance.validate(self.repo)
        self.assertEqual(result["changedPosters"], 0)
        self.assertEqual(result["verifiedGenerated"], 0)

    def test_new_or_changed_poster_without_receipt_is_rejected(self):
        with self.assertRaisesRegex(provenance.ProvenanceError, "no image-generation receipt"):
            provenance.validate(self.repo, changed=[self.poster])

    def test_prompt_gate_false_cannot_be_used_as_generation_receipt(self):
        self._write_receipt(self._receipt(generated=False))
        with self.assertRaisesRegex(provenance.ProvenanceError, "prompt-gate receipt"):
            provenance.validate(self.repo, changed=[self.poster])

    def test_valid_generation_receipt_passes(self):
        self._write_receipt()
        result = provenance.validate(self.repo, changed=[self.poster])
        self.assertEqual(result["verifiedGenerated"], 1)

    def test_new_gallery_requires_explicit_fit_and_framing_review(self):
        lesson = copy.deepcopy(self.lesson)
        lesson["presentation"] = {"clinicalGallery": {"images": [{
            "focusRegion": {"coordinates": "normalized-original-image", "x": 0, "y": 0, "width": 1, "height": 1},
        }]}}
        self._write_lessons(lesson)
        self._write_receipt()
        with self.assertRaisesRegex(provenance.ProvenanceError, "explicit fit"):
            provenance.validate(self.repo, changed=[self.poster])


if __name__ == "__main__":
    unittest.main()
