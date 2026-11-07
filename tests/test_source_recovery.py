import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from source_archive import inspect_archive, restore
from source_vault import build_archive
from extract_raja_source import ANSWER, QUESTION, parse_options, sections


class SourceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = self.root / "source"
        source.mkdir()
        records = {
            "book-metadata.json": {"id": "test-book", "question_count": 1},
            "questions.json": [{"id": "test-book-q001", "source_question_number": 1}],
            "figure-qa.json": {"final_asset_fidelity_summary": {"repair_required": 0}},
            "book-pages.json": [], "source-figures.json": [],
            "source-annotations.json": [], "extraction-report.json": {},
        }
        for name, value in records.items():
            (source / name).write_text(json.dumps(value))
        self.data, self.manifest = build_archive(source, None)

    def test_restore_round_trip_and_repeated_restore_preserve_progress(self):
        ledger = self.root / "production" / "books" / "test-book.json"
        ledger.parent.mkdir(parents=True)
        ledger.write_text('{"completedVideos":3}')
        destination = self.root / "private-content" / "books" / "test-book"
        result = restore(self.data, "test-book", destination)
        self.assertFalse(result["alreadyRestored"])
        self.assertEqual(json.loads((destination / "questions.json").read_text())[0]["id"], "test-book-q001")
        self.assertTrue(restore(self.data, "test-book", destination)["alreadyRestored"])
        self.assertEqual(ledger.read_text(), '{"completedVideos":3}')

    def test_wrong_book_rejected_before_any_write(self):
        destination = self.root / "absent"
        with self.assertRaisesRegex(ValueError, "Wrong book"):
            restore(self.data, "different-book", destination)
        self.assertFalse(destination.exists())

    def test_existing_different_source_is_untouched(self):
        destination = self.root / "private-content"
        destination.mkdir()
        source = destination / "questions.json"
        source.write_text("preserve me")
        with self.assertRaisesRegex(ValueError, "will not be overwritten"):
            restore(self.data, "test-book", destination)
        self.assertEqual(source.read_text(), "preserve me")
        self.assertEqual(len(list(destination.iterdir())), 1)

    def test_changed_payload_rejected(self):
        changed = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.data)) as original, zipfile.ZipFile(changed, "w") as archive:
            for name in original.namelist():
                payload = b"[]" if name.endswith("questions.json") else original.read(name)
                archive.writestr(name, payload)
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            inspect_archive(changed.getvalue())

    def test_unsafe_archive_path_rejected(self):
        changed = io.BytesIO(self.data)
        with zipfile.ZipFile(changed, "a") as archive:
            archive.writestr("private-content/../../production/books/test-book.json", "{}")
        with self.assertRaisesRegex(ValueError, "Unsafe source archive path"):
            restore(changed.getvalue(), "test-book", self.root / "destination")

    def test_symlink_destination_rejected(self):
        destination = self.root / "linked"
        destination.symlink_to(self.root / "source", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            restore(self.data, "test-book", destination)

    def test_metadata_identity_must_match_manifest(self):
        source = self.root / "source"
        (source / "questions.json").write_text('[{"id":"another-book-q001","source_question_number":1}]')
        data, _ = build_archive(source, None)
        with self.assertRaisesRegex(ValueError, "different book"):
            inspect_archive(data)


class SourceParserTests(unittest.TestCase):
    def test_question_can_span_pages(self):
        pages = [{"pdf_page": 13, "body_text": "1. A question\n"},
                 {"pdf_page": 14, "body_text": "continued.\n2. Another question\n"}]
        records = sections(pages, QUESTION)
        self.assertEqual([p["pdf_page"] for p in records[0]["pages"]], [13, 14])
        self.assertEqual(records[0]["text"], "A question\n\ncontinued.")

    def test_duplicate_answers_are_retained(self):
        records = sections([{"pdf_page": 113, "body_text": "49. Answer: E\nFirst.\n49. Answer: E\nSecond.\n"}], ANSWER)
        self.assertEqual(len(records), 2)
        self.assertEqual([record["text"] for record in records], ["First.", "Second."])

    def test_leading_blank_lines_do_not_assign_answer_to_previous_page(self):
        records = sections([{"pdf_page": 168, "body_text": "173. Answer: A\nExplanation.\n  \n"},
                            {"pdf_page": 169, "body_text": "174. Answer: C\n"}], ANSWER)
        self.assertEqual(records[1]["pages"], [{"pdf_page": 169, "printed_page": 157}])

    def test_nonsequential_source_option_order_is_recorded(self):
        stem, options, order = parse_options(8, "Question?\nA. First\nB. Second\nD. Fourth\nE. Fifth\nC. Third\n")
        self.assertEqual(order, list("ABDEC"))
        self.assertEqual(options[2]["label"], "C")
        self.assertEqual(options[2]["text"], "Third")

    def test_image_choices_are_not_invented(self):
        _, options, _ = parse_options(23, "Question?\nA.\nB.\nC.\nD.\nE.\n")
        self.assertTrue(all(option["text"] is None for option in options))
        self.assertTrue(all(option["format"] == "image" for option in options))

    def test_incomplete_ordinary_choices_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "five distinct"):
            parse_options(7, "Question?\nA. First\nB. Second\n")

    def test_unlabeled_choices_require_known_layout(self):
        _, options, _ = parse_options(103, "Synthetic incidence of WPW is\nOne\nTwo\nThree\nFour\nFive\n")
        self.assertEqual([option["label"] for option in options], list("ABCDE"))
        self.assertTrue(all(option["label_inferred_from_order"] for option in options))
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            parse_options(103, "Unrecognized layout\nOne\nTwo\nThree\nFour\nFive\n")


if __name__ == "__main__":
    unittest.main()
