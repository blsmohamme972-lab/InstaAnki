"""The approved fresh app has a separate identity and ships no old lesson media."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fresh_apk_builder", ROOT / "android/build_apk.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
A = "{http://schemas.android.com/apk/res/android}"


class AndroidFreshProfileTests(unittest.TestCase):
    def test_manifests_keep_distinct_packages_labels_and_provider_authorities(self):
        legacy = ET.parse(builder.profile_manifest("legacy")).getroot()
        fresh = ET.parse(builder.profile_manifest("fresh")).getroot()
        self.assertEqual(legacy.get("package"), "com.instaanki.app")
        self.assertEqual(fresh.get("package"), "com.instaanki.fresh")
        self.assertEqual(fresh.get(A + "versionName"), "0.3.4")
        self.assertEqual(fresh.get(A + "versionCode"), "8")
        app = fresh.find("application")
        self.assertEqual(app.get(A + "label"), "InstaAnki Fresh")
        self.assertEqual(app.get(A + "allowBackup"), "false")
        self.assertEqual(app.find("activity").get(A + "name"), "com.instaanki.app.MainActivity")
        self.assertEqual(app.find("provider").get(A + "name"), "com.instaanki.app.FeedbackProvider")
        self.assertEqual(app.find("provider").get(A + "authorities"), "com.instaanki.fresh.feedback")
        self.assertNotEqual(app.find("provider").get(A + "authorities"), legacy.find("application/provider").get(A + "authorities"))

    def test_wrong_fresh_manifest_identity_or_java_component_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for change in ("package", "component", "authority"):
                tree = ET.parse(ROOT / "android/AndroidManifest.fresh.xml")
                document = tree.getroot()
                if change == "package": document.set("package", "com.instaanki.app")
                if change == "component": document.find("application/activity").set(A + "name", ".MainActivity")
                if change == "authority": document.find("application/provider").set(A + "authorities", "com.instaanki.app.feedback")
                tree.write(directory / "AndroidManifest.fresh.xml")
                with self.subTest(change=change), patch.object(builder, "ANDROID", directory), self.assertRaises(SystemExit):
                    builder.profile_manifest("fresh")

    def test_missing_fresh_key_does_not_create_key_or_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "not-created"
            with patch.object(builder.subprocess, "run") as process, self.assertRaisesRegex(SystemExit, "Fresh Android signing backup is missing"):
                builder.signing_key(missing, "fresh", 4)
            process.assert_not_called()
            self.assertFalse(missing.exists())

    def test_legacy_key_files_are_never_used_as_a_fresh_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "instaanki-release.p12").write_bytes(b"legacy fixture only")
            (directory / "keystore-password.txt").write_text("synthetic password")
            with patch.object(builder.subprocess, "run") as process, self.assertRaisesRegex(SystemExit, "Incomplete signing backup"):
                builder.signing_key(directory, "fresh", 4)
            process.assert_not_called()
            self.assertFalse((directory / "instaanki-fresh-release.p12").exists())

    def make_signing_fixture(self, root):
        key_dir, public = root / "private-fixture", root / "android"
        key_dir.mkdir();public.mkdir()
        (key_dir / "instaanki-fresh-release.p12").write_bytes(b"not a real key")
        (key_dir / "keystore-password.txt").write_text("synthetic private password")
        certificate = b"synthetic public certificate"
        identity = {"schemaVersion": 1, "packageName": "com.instaanki.fresh",
                    "certificateSha256": hashlib.sha256(certificate).hexdigest(), "lastDeliveredVersionCode": 0}
        (public / "signing-identity-fresh.json").write_text(json.dumps(identity))
        return key_dir, public, certificate, identity

    def test_fresh_key_requires_its_pinned_certificate_and_distinct_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, public, certificate, _ = self.make_signing_fixture(Path(temporary))
            with patch.object(builder, "ANDROID", public), patch.object(builder.subprocess, "run", return_value=SimpleNamespace(stdout=certificate)) as process:
                key, password = builder.signing_key(directory, "fresh", 4)
            self.assertEqual(key.name, "instaanki-fresh-release.p12")
            self.assertEqual(password.name, "keystore-password.txt")
            self.assertIn("instaanki-fresh", process.call_args.args[0])
            self.assertIn("-storepass:file", process.call_args.args[0])
            self.assertNotIn("synthetic private password", str(process.call_args))
            with patch.object(builder, "ANDROID", public), patch.object(builder.subprocess, "run", return_value=SimpleNamespace(stdout=b"wrong certificate")), self.assertRaisesRegex(SystemExit, "pinned InstaAnki Fresh identity"):
                builder.signing_key(directory, "fresh", 4)

    def test_fresh_identity_cannot_claim_legacy_package_or_reuse_delivered_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, public, _, identity = self.make_signing_fixture(Path(temporary))
            identity["packageName"] = "com.instaanki.app"
            (public / "signing-identity-fresh.json").write_text(json.dumps(identity))
            with patch.object(builder, "ANDROID", public), patch.object(builder.subprocess, "run") as process, self.assertRaisesRegex(SystemExit, "selected application profile"):
                builder.signing_key(directory, "fresh", 4)
            process.assert_not_called()
            identity.update(packageName="com.instaanki.fresh", lastDeliveredVersionCode=4)
            (public / "signing-identity-fresh.json").write_text(json.dumps(identity))
            with patch.object(builder, "ANDROID", public), patch.object(builder.subprocess, "run") as process, self.assertRaisesRegex(SystemExit, "increase versionCode"):
                builder.signing_key(directory, "fresh", 4)
            process.assert_not_called()

    def test_fresh_staging_drops_unreferenced_old_media_and_private_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);web = root / "web"
            for folder in ("data", "media", "private-content"): (web / folder).mkdir(parents=True)
            (web / "index.html").write_text("<!doctype html><title>Fresh fixture</title>")
            (web / "data/lessons.json").write_text("[]")
            (web / "data/books.json").write_text("[{}]")
            (web / "media/old-lesson.mp3").write_bytes(b"old audio fixture")
            (web / "media/old-image.png").write_bytes(b"old image fixture")
            (web / "private-content/book.pdf").write_bytes(b"private fixture")
            target = root / "staged"
            result = builder.stage_web_bundle(web, target, "fresh")
            self.assertEqual(result, {"activeLessons": 0, "mediaFiles": 0, "mediaBytes": 0})
            self.assertFalse((target / "media").exists())
            self.assertFalse((target / "private-content").exists())
            self.assertTrue((web / "media/old-lesson.mp3").exists())

    def test_fresh_staging_rejects_a_lesson_or_cover_reference_before_copying(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);web = root / "web";(web / "data").mkdir(parents=True)
            (web / "media").mkdir();(web / "media/cover.png").write_bytes(b"fixture")
            for lessons, books in (([{"id": "must-not-ship"}], []), ([], [{"coverUrl": "media/cover.png"}])):
                (web / "data/lessons.json").write_text(json.dumps(lessons));(web / "data/books.json").write_text(json.dumps(books))
                with self.subTest(lessons=lessons), self.assertRaisesRegex(ValueError, "fresh application"):
                    builder.stage_web_bundle(web, root / "never-created", "fresh")
                self.assertFalse((root / "never-created").exists())

    def test_fresh_entrypoint_prepares_empty_input_without_legacy_media_or_sdk(self):
        from check_source_scope import FRESH_RUNTIME_FILES
        with tempfile.TemporaryDirectory() as temporary:
            web = Path(temporary) / "web"
            for name in (*FRESH_RUNTIME_FILES, "data/books.json", "data/lessons.json"):
                target = web / name;target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / "web" / name, target)
            original = (web / "data/lessons.json").read_bytes()
            observed = {}
            def capture(args, config, scope):
                observed.update(profile=args.profile, package=config["packageName"], version=args.version_name,
                                code=args.version_code, output=args.output.name, scope=scope,
                                lessons=json.loads((args.web_dir / "data/lessons.json").read_text()),
                                media=(args.web_dir / "media").exists(), private=(args.web_dir / "private-content").exists())
            with patch.object(sys, "argv", ["build_apk.py", "--profile", "fresh", "--unsigned", "--web-dir", str(web)]), patch.object(builder, "build_validated", side_effect=capture):
                builder.main()
            self.assertEqual(observed["package"], "com.instaanki.fresh")
            self.assertEqual((observed["version"], observed["code"]), ("0.3.4", 8))
            self.assertEqual(observed["output"], "InstaAnki-Fresh-0.3.4.apk")
            self.assertEqual(observed["lessons"], [])
            self.assertEqual(observed["scope"]["activeLessons"], 0)
            self.assertFalse(observed["media"] or observed["private"])
            self.assertEqual((web / "data/lessons.json").read_bytes(), original)

    def test_fresh_private_content_and_old_version_flags_are_rejected(self):
        for extra in (["--include-private"], ["--version-code", "3"]):
            with self.subTest(extra=extra), patch.object(sys, "argv", ["build_apk.py", "--profile", "fresh", "--unsigned", *extra]), patch.object(builder, "build_validated") as build, self.assertRaises(SystemExit):
                builder.main()
            build.assert_not_called()

    def test_prepared_fresh_web_input_keeps_its_compiled_runtime(self):
        from check_source_scope import prepare_fresh_web
        with tempfile.TemporaryDirectory() as temporary:
            web = Path(temporary) / "prepared"
            prepare_fresh_web(ROOT, ROOT / "web", web)
            compiled_runtime = b"/* selected compiled fresh runtime fixture */\n"
            (web / "learning.js").write_bytes(compiled_runtime)
            observed = {}
            def capture(args, config, scope):
                observed.update(web=args.web_dir, runtime=(args.web_dir / "learning.js").read_bytes(), scope=scope)
            with patch.object(sys, "argv", ["build_apk.py", "--profile", "fresh", "--unsigned", "--web-dir", str(web)]), patch.object(builder, "build_validated", side_effect=capture), patch("check_source_scope.prepare_fresh_web") as prepare:
                builder.main()
            prepare.assert_not_called()
            self.assertEqual(observed["web"], web)
            self.assertEqual(observed["runtime"], compiled_runtime)
            self.assertEqual(observed["scope"]["activeLessons"], 0)
            self.assertEqual((web / "learning.js").read_bytes(), compiled_runtime)

    def test_prepared_fresh_input_rejects_wrong_marker_missing_marker_or_old_media(self):
        from check_source_scope import prepare_fresh_web
        with tempfile.TemporaryDirectory() as temporary:
            for problem in ("wrong-marker", "missing-marker", "old-media"):
                web = Path(temporary) / problem
                prepare_fresh_web(ROOT, ROOT / "web", web)
                marker = web / "data/distribution.json"
                if problem == "wrong-marker":
                    document = json.loads(marker.read_text());document["app"]["packageName"] = "com.instaanki.app"
                    marker.write_text(json.dumps(document))
                elif problem == "missing-marker":
                    marker.unlink()
                else:
                    (web / "media").mkdir();(web / "media/old-lesson.mp3").write_bytes(b"old audio fixture")
                before = {path.relative_to(web).as_posix(): path.read_bytes() for path in web.rglob("*") if path.is_file()}
                with self.subTest(problem=problem), patch.object(sys, "argv", ["build_apk.py", "--profile", "fresh", "--unsigned", "--web-dir", str(web)]), patch.object(builder, "build_validated") as build, self.assertRaisesRegex(SystemExit, "Source scope check failed"):
                    builder.main()
                build.assert_not_called()
                self.assertEqual(before, {path.relative_to(web).as_posix(): path.read_bytes() for path in web.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()
