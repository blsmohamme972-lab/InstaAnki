"""Focused contract tests for the one-off, data-only collection correction."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_collection_correction", ROOT / "tools/build_collection_correction.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class CollectionCorrectionTest(unittest.TestCase):
    def test_only_exact_known_pack_can_be_targeted(self):
        for value in ("shahzad-raja-2015-200-practice-questions", "another-pack", "../escape", "", builder.TARGET_PACK_ID + "-other"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                builder.correction_files(value)

    def test_empty_payload_has_no_book_claims_or_learning_state(self):
        files = builder.correction_files()
        self.assertEqual(set(files), {"manifest.json", "lessons.json", "README.txt"})
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(manifest["id"], builder.TARGET_PACK_ID)
        self.assertEqual(manifest["packId"], builder.TARGET_PACK_ID)
        self.assertEqual(manifest["type"], "collection-correction")
        self.assertEqual(manifest["books"], [])
        self.assertEqual(manifest["lessonCount"], 0)
        self.assertEqual(json.loads(files["lessons.json"]), [])
        self.assertTrue(manifest["correction"]["requiresAppRestart"])
        self.assertFalse(manifest["correction"]["learningStateFilesIncluded"])
        self.assertEqual(set(manifest["sha256"]), {"lessons.json", "README.txt"})
        for name, digest in manifest["sha256"].items():
            self.assertEqual(digest, hashlib.sha256(files[name]).hexdigest())

    def test_output_is_small_deterministic_stored_zip_with_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = [Path(folder) / name for name in ("first.zip", "second.zip")]
            report = builder.build_correction(first)
            builder.build_correction(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertLess(report["bytes"], 8192)
            self.assertEqual(report["sha256"], hashlib.sha256(first.read_bytes()).hexdigest())
            with zipfile.ZipFile(first) as archive:
                self.assertIsNone(archive.testzip())
                self.assertTrue(all(item.compress_type == zipfile.ZIP_STORED for item in archive.infolist()))
                self.assertTrue(all(item.flag_bits == 0 for item in archive.infolist()))
                self.assertEqual(set(archive.namelist()), {"manifest.json", "lessons.json", "README.txt"})
            before = first.read_bytes()
            with self.assertRaises(FileExistsError):
                builder.build_correction(first)
            self.assertEqual(first.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
