"""Prevent unrelated media and replacement signing identities in app updates."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("apk_builder", ROOT / "android/build_apk.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class AndroidBuildSafetyTests(unittest.TestCase):
    def test_personal_cover_uses_recovered_file_without_other_private_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "private-content").mkdir()
            (root / "private-content/book-cover.jpeg").write_bytes(b"cover-fixture")
            (root / "private-content/questions.json").write_text("private source")
            with patch.object(builder, "ROOT", root):
                self.assertEqual(builder.stage_private_cover(root / "stage"), ["private-content/book-cover.jpeg"])
            self.assertEqual((root / "stage/private-content/book-cover.jpeg").read_bytes(), b"cover-fixture")
            self.assertEqual(len(list((root / "stage").rglob("*.*"))), 1)

    def test_missing_key_does_not_generate_replacement_or_create_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing-private-backup"
            with self.assertRaisesRegex(SystemExit, "Original Android signing backup is missing"):
                builder.signing_key(missing)
            self.assertFalse(missing.exists())

    def test_incomplete_key_backup_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "instaanki-release.p12").write_bytes(b"fixture")
            with self.assertRaisesRegex(SystemExit, "Incomplete signing backup"):
                builder.signing_key(directory)
            self.assertFalse((directory / "keystore-password.txt").exists())

    def test_wrong_certificate_is_rejected_and_password_not_on_commandline(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "instaanki-release.p12").write_bytes(b"fixture")
            (directory / "keystore-password.txt").write_text("private-fixture-password")
            with patch.object(builder.subprocess, "run", return_value=SimpleNamespace(stdout=b"wrong-public-certificate")) as run:
                with self.assertRaisesRegex(SystemExit, "Signing certificate differs"):
                    builder.signing_key(directory)
            self.assertNotIn("private-fixture-password", str(run.call_args))

    def test_runtime_staging_excludes_unreferenced_media_and_authoring_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            web = root / "web"
            (web / "data").mkdir(parents=True)
            (web / "media").mkdir()
            (web / "index.html").write_text("<!doctype html><title>Fixture</title>")
            (web / "app.js").write_text("/* runtime */")
            (web / "learning.entry.js").write_text("/* authoring input */")
            (web / "app.js.map").write_text("{}")
            for name in ("active.mp3", "active.png", "clinical.jpg", "archived.mp3", "unproduced.png", "cover.webp"):
                (web / "media" / name).write_bytes(name.encode())
            lesson = {"id": "existing-source-lesson", "durationSeconds": 20,
                "audioUrl": "media/active.mp3", "poster": "media/active.png",
                "scenes": [{"start": 0, "end": 10, "image": "media/active.png"}],
                "realImages": [{"url": "media/clinical.jpg"}],
                "realImageOutro": {"start": 10, "end": 20},
                "quiz": {"options": ["A", "B"], "correctIndex": 0}}
            (web / "data/lessons.json").write_text(json.dumps([lesson]))
            (web / "data/books.json").write_text(json.dumps([{"coverUrl": "media/cover.webp"}]))
            destination = root / "staged"
            result = builder.stage_web_bundle(web, destination)
            self.assertEqual(result["activeLessons"], 1)
            self.assertEqual(result["mediaFiles"], 4)
            self.assertEqual({p.name for p in (destination / "media").iterdir()},
                             {"active.mp3", "active.png", "clinical.jpg", "cover.webp"})
            self.assertTrue((destination / "app.js").is_file())
            self.assertFalse((destination / "learning.entry.js").exists())
            self.assertFalse((destination / "app.js.map").exists())
            self.assertTrue((web / "media/archived.mp3").is_file())


if __name__ == "__main__":
    unittest.main()
