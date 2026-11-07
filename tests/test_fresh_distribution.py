"""The authorized empty app is a separate, constrained distribution profile."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_source_scope import FRESH_DATA_FILES, FRESH_RUNTIME_FILES, check_catalog, prepare_fresh_web
from source_policy import SourcePolicy, SourcePolicyError


class FreshDistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.web = self.root / "web"
        self.stage = self.root / "build/fresh-web"
        for name in (
            "production/source-policy.json", "production/distribution-profiles.json",
            "production/books/shahzad-raja-2015-200-practice-questions.json",
            "web/data/books.json", "web/data/lessons.json",
            *("web/" + name for name in FRESH_RUNTIME_FILES),
        ):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)

    def prepare(self):
        return prepare_fresh_web(self.root, self.web, self.stage)

    def edit_json(self, relative, change):
        path = self.stage / relative
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))

    def test_empty_stage_needs_no_old_media_and_preserves_historical_truth(self):
        original_lessons = (self.web / "data/lessons.json").read_bytes()
        original_ledger = (self.root / "production/books/shahzad-raja-2015-200-practice-questions.json").read_bytes()
        # There are deliberately no media assets in this fixture.
        result = self.prepare()
        self.assertEqual((result["activeLessons"], result["producedQuestions"], result["totalQuestions"]), (0, 3, 200))
        self.assertEqual(json.loads((self.stage / "data/lessons.json").read_text()), [])
        books = json.loads((self.stage / "data/books.json").read_text())
        self.assertEqual(books[0]["completedQuestionNumbers"], [5, 54, 182])
        self.assertEqual(books[0]["completedVideos"], 3)
        self.assertTrue(books[0]["productionPaused"])
        self.assertNotIn("coverUrl", books[0])
        self.assertFalse((self.stage / "media").exists())
        self.assertFalse((self.stage / "private-content").exists())
        self.assertEqual((self.web / "data/lessons.json").read_bytes(), original_lessons)
        self.assertEqual((self.root / "production/books/shahzad-raja-2015-200-practice-questions.json").read_bytes(), original_ledger)
        self.assertEqual(check_catalog(self.root, self.stage, profile="fresh"), result)

    def test_standard_catalog_and_normal_packs_still_reject_empty_content(self):
        self.prepare()
        with self.assertRaisesRegex(SourcePolicyError, "explicit fresh distribution"):
            check_catalog(self.root, self.stage)
        (self.stage / "data/distribution.json").unlink()
        with self.assertRaises(SourcePolicyError):
            check_catalog(self.root, self.stage)
        with self.assertRaises(SourcePolicyError):
            SourcePolicy(self.root).validate_pack([], self.stage)

    def test_missing_or_modified_fresh_marker_cannot_approve_a_bundle(self):
        self.prepare()
        self.edit_json("data/distribution.json", lambda value: value.update(bundledLessonCount=3))
        with self.assertRaisesRegex(SourcePolicyError, "exact reviewed distribution marker"):
            check_catalog(self.root, self.stage, profile="fresh")
        (self.stage / "data/distribution.json").unlink()
        with self.assertRaisesRegex(SourcePolicyError, "missing required regular files: data/distribution.json"):
            check_catalog(self.root, self.stage, profile="fresh")

    def test_fresh_gate_requires_every_runtime_and_data_file(self):
        self.prepare()
        for name in FRESH_RUNTIME_FILES + FRESH_DATA_FILES:
            path = self.stage / name
            original = path.read_bytes()
            path.unlink()
            with self.subTest(missing=name), self.assertRaisesRegex(SourcePolicyError, "missing required regular files") as caught:
                check_catalog(self.root, self.stage, profile="fresh")
            self.assertIn(name, str(caught.exception))
            path.write_bytes(original)

    def test_fresh_gate_rejects_directory_in_place_of_required_runtime(self):
        self.prepare()
        path = self.stage / "learning.js"
        path.unlink()
        path.mkdir()
        with self.assertRaisesRegex(SourcePolicyError, "missing required regular files: learning.js"):
            check_catalog(self.root, self.stage, profile="fresh")

    def test_fresh_gate_rejects_symlinked_runtime_and_marker(self):
        self.prepare()
        for name in ("app.js", "learning.js", "data/distribution.json"):
            path = self.stage / name
            original = path.read_bytes()
            external = Path(self.temp.name) / (Path(name).name + ".outside")
            external.write_bytes(original)
            path.unlink()
            path.symlink_to(external)
            with self.subTest(symlink=name), self.assertRaisesRegex(SourcePolicyError, "cannot contain symlinks"):
                check_catalog(self.root, self.stage, profile="fresh")
            path.unlink()
            path.write_bytes(original)

    def test_fresh_gate_rejects_symlinked_data_directory(self):
        self.prepare()
        outside = Path(self.temp.name) / "outside-data"
        (self.stage / "data").rename(outside)
        (self.stage / "data").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(SourcePolicyError, "cannot contain symlinks.*data"):
            check_catalog(self.root, self.stage, profile="fresh")

    def test_fresh_gate_rejects_old_lesson_even_with_correct_source(self):
        self.prepare()
        shutil.copyfile(self.web / "data/lessons.json", self.stage / "data/lessons.json")
        with self.assertRaisesRegex(SourcePolicyError, "zero bundled lessons"):
            check_catalog(self.root, self.stage, profile="fresh")

    def test_fresh_gate_rejects_wrong_source_and_false_zero_production(self):
        self.prepare()
        self.edit_json("data/books.json", lambda books: books[0].update(completedVideos=0))
        with self.assertRaises(SourcePolicyError):
            check_catalog(self.root, self.stage, profile="fresh")
        shutil.rmtree(self.stage)
        self.prepare()
        self.edit_json("data/books.json", lambda books: books[0].update(id="unrelated-book"))
        with self.assertRaisesRegex(SourcePolicyError, "Publication id differs"):
            check_catalog(self.root, self.stage, profile="fresh")

    def test_fresh_gate_requires_paused_scope_and_no_cover_or_media(self):
        self.prepare()
        self.edit_json("data/books.json", lambda books: books[0].update(productionPaused=False))
        with self.assertRaisesRegex(SourcePolicyError, "production paused"):
            check_catalog(self.root, self.stage, profile="fresh")
        self.edit_json("data/books.json", lambda books: books[0].update(productionPaused=True, coverUrl="media/old-cover.jpg"))
        with self.assertRaisesRegex(SourcePolicyError, "omit cover media"):
            check_catalog(self.root, self.stage, profile="fresh")
        self.edit_json("data/books.json", lambda books: books[0].pop("coverUrl"))
        extra = self.stage / "media/old-video.mp4"
        extra.parent.mkdir()
        extra.write_bytes(b"not a real video")
        with self.assertRaisesRegex(SourcePolicyError, "old media files"):
            check_catalog(self.root, self.stage, profile="fresh")

    def test_unpaused_source_policy_disables_empty_distribution(self):
        path = self.root / "production/source-policy.json"
        policy = json.loads(path.read_text())
        policy["newProductionEnabled"] = True
        path.write_text(json.dumps(policy))
        with self.assertRaisesRegex(SourcePolicyError, "fresh-distribution profile"):
            self.prepare()
        self.assertFalse(self.stage.exists())

    def test_staging_cannot_overwrite_canonical_or_unrelated_files(self):
        with self.assertRaisesRegex(SourcePolicyError, "separate"):
            prepare_fresh_web(self.root, self.web, self.web)
        self.stage.mkdir(parents=True)
        sentinel = self.stage / "keep-this.txt"
        sentinel.write_text("private user file")
        with self.assertRaises((SourcePolicyError, OSError)):
            self.prepare()
        self.assertEqual(sentinel.read_text(), "private user file")

    def test_existing_valid_stage_can_be_refreshed_without_adding_lessons(self):
        self.prepare()
        (self.web / "app.js").write_text("/* refreshed runtime */")
        self.assertEqual(self.prepare()["activeLessons"], 0)
        self.assertEqual((self.stage / "app.js").read_text(), "/* refreshed runtime */")

    def update_synthetic_progress(self, *, produce=False, update_source=True):
        path = self.root / "production/books/shahzad-raja-2015-200-practice-questions.json"
        ledger = json.loads(path.read_text())
        for question in ledger["questions"]:
            if question["number"] in ((1, 2, 4) if produce else (1,)):
                question["status"] = "produced" if produce else "needs_review"
                question["lessonId"] = f"synthetic-q{question['number']:03d}" if produce else None
        completed = sorted(question["number"] for question in ledger["questions"] if question["status"] == "produced")
        ledger.update(completedVideos=len(completed), completedQuestionNumbers=completed)
        path.write_text(json.dumps(ledger))
        if update_source:
            path = self.web / "data/books.json"
            books = json.loads(path.read_text())
            books[0].update(completedVideos=len(completed), completedQuestionNumbers=completed,
                            progress=round(len(completed) / ledger["totalQuestions"] * 100, 1),
                            questions=[{key: question.get(key) for key in ("number", "status", "lessonId")}
                                       for question in ledger["questions"]])
            path.write_text(json.dumps(books))

    def test_previous_stage_can_refresh_after_legitimate_progress_or_status_changes(self):
        for produce in (False, True):
            with self.subTest(produce=produce):
                self.prepare()
                self.update_synthetic_progress(produce=produce)
                with self.assertRaises(SourcePolicyError):
                    check_catalog(self.root, self.stage, profile="fresh")
                result = self.prepare()
                self.assertEqual(result["producedQuestions"], 6 if produce else 3)
                self.assertEqual(result["activeLessons"], 0)
                self.assertEqual(check_catalog(self.root, self.stage, profile="fresh"), result)

    def test_stale_current_source_cannot_replace_an_existing_stage(self):
        self.prepare()
        previous = (self.stage / "data/books.json").read_bytes()
        self.update_synthetic_progress(produce=True, update_source=False)
        with self.assertRaisesRegex(SourcePolicyError, "completed counts"):
            self.prepare()
        self.assertEqual((self.stage / "data/books.json").read_bytes(), previous)

    def test_refresh_preserves_unowned_modified_or_symlinked_stages(self):
        for problem in ("extra-file", "symlink", "marker", "runtime", "book", "lessons", "cached-count"):
            with self.subTest(problem=problem):
                self.prepare()
                if problem == "extra-file":
                    (self.stage / "keep-this.txt").write_text("Synthetic user file")
                elif problem == "symlink":
                    outside = Path(self.temp.name) / "outside.js"
                    outside.write_text("Synthetic external runtime")
                    (self.stage / "app.js").unlink()
                    (self.stage / "app.js").symlink_to(outside)
                elif problem == "marker":
                    self.edit_json("data/distribution.json", lambda marker: marker.update(profile="standard"))
                elif problem == "runtime":
                    (self.stage / "index.html").write_text('<meta name="instaanki-distribution" content="standard">')
                elif problem == "book":
                    self.edit_json("data/books.json", lambda books: books[0].update(id="unrelated-book"))
                elif problem == "lessons":
                    (self.stage / "data/lessons.json").write_text('[{"id":"synthetic-unrelated-lesson"}]')
                else:
                    self.edit_json("data/books.json", lambda books: books[0].update(completedVideos=99))
                def snapshot():
                    return {path.relative_to(self.stage).as_posix():
                            ("symlink", str(path.readlink())) if path.is_symlink() else ("file", path.read_bytes())
                            for path in self.stage.rglob("*") if path.is_symlink() or path.is_file()}
                before = snapshot()
                with self.assertRaises(SourcePolicyError):
                    self.prepare()
                self.assertEqual(snapshot(), before)
                shutil.rmtree(self.stage)

    def test_refresh_rejects_symlinked_source_runtime_and_destination(self):
        self.prepare()
        previous = (self.stage / "app.js").read_bytes()
        source = self.web / "app.js"
        outside = Path(self.temp.name) / "outside-runtime.js"
        source.rename(outside)
        source.symlink_to(outside)
        with self.assertRaisesRegex(SourcePolicyError, "runtime input is missing or unsafe"):
            self.prepare()
        self.assertEqual((self.stage / "app.js").read_bytes(), previous)
        source.unlink()
        outside.rename(source)
        old_stage = Path(self.temp.name) / "retained-stage"
        self.stage.rename(old_stage)
        self.stage.symlink_to(old_stage, target_is_directory=True)
        with self.assertRaisesRegex(SourcePolicyError, "destination must not be a symlink"):
            self.prepare()
        self.assertTrue(self.stage.is_symlink())
        self.assertEqual((old_stage / "app.js").read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
