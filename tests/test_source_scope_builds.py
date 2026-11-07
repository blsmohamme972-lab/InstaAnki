"""Actual build entry points must validate their selected app bundle first."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_source_scope import check_catalog
from source_policy import SourcePolicyError


class SourceScopeBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        for name in (
            "production/source-policy.json",
            "production/books/shahzad-raja-2015-200-practice-questions.json",
            "tools/source_policy.py", "tools/check_source_scope.py",
            "tools/build_web.mjs", "android/build_apk.py",
        ):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        self.books = json.loads((ROOT / "web/data/books.json").read_text())
        self.lessons = json.loads((ROOT / "web/data/lessons.json").read_text())

    def make_bundle(self, path, *, wrong_book=False, wrong_lesson=False):
        data = path / "data"
        data.mkdir(parents=True)
        books = json.loads(json.dumps(self.books))
        lessons = json.loads(json.dumps(self.lessons))
        if wrong_book:
            books[0]["id"] = "unrelated-publication"
        if wrong_lesson:
            lessons[0]["source"]["bookId"] = "unrelated-publication"
        (data / "books.json").write_text(json.dumps(books))
        (data / "lessons.json").write_text(json.dumps(lessons))
        (path / "index.html").write_text("<!doctype html><title>Fixture</title>")
        return path

    def test_selected_web_root_is_checked_instead_of_default_catalog(self):
        self.make_bundle(self.root / "web")
        selected = self.make_bundle(Path(self.temp.name) / "selected-web", wrong_book=True)
        with self.assertRaisesRegex(SourcePolicyError, "Publication id differs"):
            check_catalog(self.root, selected)

    def test_catalog_cli_checks_selected_bundle_with_fixed_repository_policy(self):
        self.make_bundle(self.root / "web")
        selected = self.make_bundle(Path(self.temp.name) / "selected-web", wrong_lesson=True)
        # A selected bundle cannot supply a replacement source policy.
        (selected / "production").mkdir()
        (selected / "production/source-policy.json").write_text(json.dumps({
            "schemaVersion": 1, "activeBookId": "unrelated-publication"}))
        run = subprocess.run([sys.executable, str(self.root / "tools/check_source_scope.py"),
                              "--web-root", str(selected)], text=True, capture_output=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("Source policy permits only shahzad-raja", run.stderr)
        self.assertIn("unrelated-publication", run.stderr)

    def test_apk_rejects_selected_bundle_before_sdk_staging_or_signing(self):
        self.make_bundle(self.root / "web")
        selected = self.make_bundle(Path(self.temp.name) / "selected-web", wrong_lesson=True)
        stage = self.root / "build/android"
        stage.mkdir(parents=True)
        sentinel = stage / "keep-existing-stage.txt"
        sentinel.write_text("unchanged")
        output = self.root / "dist/must-not-exist.apk"
        key_dir = Path(self.temp.name) / "must-not-create-signing"
        run = subprocess.run([sys.executable, str(self.root / "android/build_apk.py"),
                              "--web-dir", str(selected), "--output", str(output),
                              "--sdk-dir", str(self.root / "missing-sdk"),
                              "--key-dir", str(key_dir)], text=True, capture_output=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("Source scope check failed", run.stderr)
        self.assertIn("unrelated-publication", run.stderr)
        self.assertNotIn("Android API 35 platform missing", run.stderr)
        self.assertEqual(sentinel.read_text(), "unchanged")
        self.assertEqual(list(stage.iterdir()), [sentinel])
        self.assertFalse(output.parent.exists())
        self.assertFalse(key_dir.exists())

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_direct_web_builder_rejects_scope_before_import_or_bundle_write(self):
        web = self.make_bundle(self.root / "web", wrong_book=True)
        bundle = web / "learning.js"
        bundle.write_text("existing bundle remains unchanged")
        run = subprocess.run([shutil.which("node"), str(self.root / "tools/build_web.mjs")],
                             text=True, capture_output=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("Source scope check failed", run.stderr)
        self.assertNotIn("Cannot find package 'esbuild'", run.stderr)
        self.assertIn("Publication id differs", run.stderr)
        self.assertEqual(bundle.read_text(), "existing bundle remains unchanged")


if __name__ == "__main__":
    unittest.main()
