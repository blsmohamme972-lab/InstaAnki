"""Reject invalid narrated endings before a lesson can be packaged."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from presentation import validate_presentation


class PresentationValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lessons = json.loads((ROOT / 'web/data/lessons.json').read_text())

    def lesson(self):
        return deepcopy(next(x for x in self.lessons if x['id'] == 'shahzad2015-q005'))

    def test_actual_three_integrated_lessons_validate(self):
        self.assertEqual({x['id'] for x in self.lessons},
                         {'shahzad2015-q005', 'shahzad2015-q054', 'shahzad2015-q182'})
        for lesson in self.lessons:
            with self.subTest(lesson=lesson['id']):
                self.assertEqual(lesson['version'], 3)
                self.assertEqual(len(lesson['presentation']['clinicalGallery']['images']), 3)
                validate_presentation(lesson)

    def test_legacy_lesson_without_presentation_remains_readable(self):
        lesson = self.lesson()
        del lesson['presentation']
        validate_presentation(lesson)

    def test_shifted_phrase_boundary_is_rejected(self):
        for boundary in ('startSeconds', 'endSeconds'):
            with self.subTest(boundary=boundary):
                lesson = self.lesson()
                lesson['presentation']['recap']['cueBindings'][1][boundary] += .02
                with self.assertRaisesRegex(ValueError, 'exact existing narrated phrase'):
                    validate_presentation(lesson)

    def test_silent_tail_cannot_be_reintroduced(self):
        lesson = self.lesson()
        p = lesson['presentation']
        # Keep sections internally consistent: the recorded voiceEnd is the
        # independent reason this otherwise plausible old-duration ending fails.
        p['effectiveEndSeconds'] = p['narrationEndSeconds'] = lesson['durationSeconds']
        p['clinicalGallery']['endSeconds'] = p['recap']['endSeconds'] = lesson['durationSeconds']
        with self.assertRaisesRegex(ValueError, 'without a silent hold'):
            validate_presentation(lesson)

    def test_missing_packaged_gallery_image_is_rejected(self):
        lesson = self.lesson()
        lesson['realImages'].pop()
        with self.assertRaisesRegex(ValueError, 'packaged realImages provenance'):
            validate_presentation(lesson)

    def test_duplicate_gallery_image_is_rejected(self):
        lesson = self.lesson()
        images = lesson['presentation']['clinicalGallery']['images']
        images[2] = deepcopy(images[0])
        with self.assertRaisesRegex(ValueError, 'must be distinct'):
            validate_presentation(lesson)

    def test_gallery_provenance_cannot_diverge_from_packaged_record(self):
        for field in ('caption', 'attribution', 'sha256'):
            with self.subTest(field=field):
                lesson = self.lesson()
                lesson['presentation']['clinicalGallery']['images'][0][field] = 'changed'
                with self.assertRaisesRegex(ValueError, 'packaged realImages provenance'):
                    validate_presentation(lesson)

    def test_required_source_license_and_hash_cannot_be_blank_in_both_records(self):
        for field in ('title', 'caption', 'sourceUrl', 'license', 'attribution', 'sha256'):
            with self.subTest(field=field):
                lesson = self.lesson()
                lesson['realImages'][0][field] = ''
                lesson['presentation']['clinicalGallery']['images'][0][field] = ''
                with self.assertRaisesRegex(ValueError, 'source, license, caption and exact asset hash'):
                    validate_presentation(lesson)

    def test_four_to_six_distinct_registered_images_are_supported(self):
        # This validator checks display schema/provenance correspondence; the
        # pack builder separately verifies that each actual local file exists.
        for count in (4, 5, 6):
            with self.subTest(count=count):
                lesson = self.lesson()
                images = lesson['presentation']['clinicalGallery']['images']
                for index in range(3, count):
                    extra = deepcopy(images[0])
                    extra['url'] = f'media/real/test-extra-{index}.png'
                    extra['sha256'] = f'{index:064x}'
                    images.append(extra)
                    lesson['realImages'].append(deepcopy(extra))
                validate_presentation(lesson)

    def test_gallery_count_outside_three_to_six_is_rejected(self):
        for count in (0, 2, 7):
            with self.subTest(count=count):
                lesson = self.lesson()
                images = lesson['presentation']['clinicalGallery']['images']
                images[:] = [deepcopy(images[0]) for _ in range(count)]
                with self.assertRaisesRegex(ValueError, 'three to six'):
                    validate_presentation(lesson)

    def test_unknown_phrase_or_unvoiced_recap_node_is_rejected(self):
        lesson = self.lesson()
        lesson['presentation']['recap']['cueBindings'][0]['phraseId'] = 'absent'
        with self.assertRaisesRegex(ValueError, 'existing phrase and node'):
            validate_presentation(lesson)
        lesson = self.lesson()
        lesson['presentation']['recap']['nodes'].append({'id': 'silent', 'label': 'Unspoken addition'})
        with self.assertRaisesRegex(ValueError, 'Every recap node requires a narration cue'):
            validate_presentation(lesson)


if __name__ == '__main__':
    unittest.main()
