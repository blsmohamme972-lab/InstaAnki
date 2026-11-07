"""Synthetic target-inspection checks; no real artwork or review is approved."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_book_guidance as guidance
import generate_audio
import production
from source_policy import ORIGINAL_BOOK, SourcePolicyError
import test_source_policy as source_fixtures

write_json = source_fixtures.write_json


class TargetInspectionTests(unittest.TestCase):
    def setUp(self):
        fixture = source_fixtures.SourceEvidenceTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture, self.root = fixture, fixture.root
        with patch.object(production, 'REPO', self.root):
            evidence = production.claim(fixture.manifest_path, 1, 'synthetic-target-review')['questions'][0]['sourceEvidence']
        self.lesson = fixture.authored_fixture(evidence)
        self.lesson.update(audioLessonId='synthetic-audio', poster='media/synthetic-poster.png',
                           realImage={'url': 'media/synthetic-clinical.png'})
        self.lesson['scenes'][0]['phrases'] = [
            {'id': 'synthetic-phrase', 'text': self.lesson['scenes'][0]['voice_text'], 'targetId': 'synthetic-anchor'}]
        fixture.record_fixture_content_review(self.lesson)
        self.images = {}
        for name, color in ((self.lesson['poster'], 'green'), (self.lesson['realImage']['url'], 'blue')):
            self.images[name] = self.image(name, color)
        self.inspected = {
            'schemaVersion': 1, 'visuallyInspected': True,
            'reviewer': 'Synthetic test fixture only', 'reviewedAt': '2026-01-01T12:00:00Z',
            'notes': ['Synthetic inspection fixture; no actual medical artwork is reviewed.'],
            'images': copy.deepcopy(self.images),
            'targets': {'synthetic-anchor': {'label': 'Synthetic focal point',
                                             'x': .5, 'y': .5, 'rx': .2, 'ry': .2}},
        }
        self.draft = self.root / 'private-content/draft.json'
        self.targets = self.root / 'private-content/inspected-targets.json'
        self.output = self.root / 'private-content/visual-guidance.json'
        self.save()

    def image(self, relative, color):
        path = self.root / 'web' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (32, 32), color).save(path)
        return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'width': 32, 'height': 32}

    def save(self):
        write_json(self.draft, {'schemaVersion': 1, 'bookId': ORIGINAL_BOOK, 'lessons': [self.lesson]})
        write_json(self.targets, {self.lesson['id']: self.inspected})

    def prepare(self, *extra, output=None):
        with patch.object(guidance, 'ROOT', self.root), patch.object(sys, 'argv', [
                'prepare_book_guidance', '--input', str(self.draft), '--targets', str(self.targets),
                '--output', str(output or self.output), *extra]), redirect_stdout(io.StringIO()):
            guidance.main()

    def test_exact_recorded_inspection_prepares_guidance_without_changing_source_or_images(self):
        ledger_before = self.fixture.manifest_path.read_bytes()
        self.prepare()
        plan = json.loads(self.output.read_text())['lessons'][0]
        self.assertEqual(plan['images'], self.images)
        self.assertEqual(plan['inspection']['recordSha256'], guidance.canonical_hash(self.inspected))
        self.assertEqual(plan['inspection']['reviewer'], self.inspected['reviewer'])
        for path, expected in self.images.items():
            self.assertEqual(hashlib.sha256((self.root / 'web' / path).read_bytes()).hexdigest(), expected['sha256'])
        self.assertEqual(self.fixture.manifest_path.read_bytes(), ledger_before)
        self.assertFalse(list(self.output.parent.glob('.visual-guidance-*')))

    def test_false_string_or_integer_is_not_a_completed_visual_inspection(self):
        self.prepare()
        previous = self.output.read_bytes()
        for value in (False, 'false', 'true', 1, None):
            self.inspected['visuallyInspected'] = value
            self.save()
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'actual schemaVersion-1 visual inspection'):
                self.prepare()
            self.assertEqual(self.output.read_bytes(), previous)

    def test_missing_review_metadata_or_image_binding_cannot_be_automatically_approved(self):
        original = copy.deepcopy(self.inspected)
        changes = [
            lambda value: value.pop('schemaVersion'), lambda value: value.pop('reviewer'),
            lambda value: value.update(notes=[]), lambda value: value.update(reviewedAt='2026-01-01T12:00:00'),
            lambda value: value.update(reviewedAt='2999-01-01T12:00:00Z'),
            lambda value: value.pop('images'), lambda value: value['images'].pop(self.lesson['poster']),
            lambda value: value['images'][self.lesson['poster']].pop('sha256'),
            lambda value: value['images'][self.lesson['poster']].update(width=100),
        ]
        before = self.fixture.manifest_path.read_bytes()
        for change in changes:
            self.inspected = copy.deepcopy(original)
            change(self.inspected)
            self.save()
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.prepare()
            self.assertFalse(self.output.exists())
        self.assertEqual(self.fixture.manifest_path.read_bytes(), before)

    def test_changed_image_cannot_rebind_old_target_coordinates(self):
        self.prepare()
        previous = self.output.read_bytes()
        self.image(self.lesson['poster'], 'red')
        with self.assertRaisesRegex(ValueError, 'differ from their actual target inspection'):
            self.prepare()
        self.assertEqual(self.output.read_bytes(), previous)

    def test_unknown_duplicate_or_partial_selection_never_drops_existing_plans(self):
        self.prepare()
        previous = self.output.read_bytes()
        for selected in (['missing-lesson'], [self.lesson['id'], 'missing-lesson'],
                         [self.lesson['id'], self.lesson['id']]):
            args = [item for identity in selected for item in ('--lesson', identity)]
            with self.subTest(selected=selected), self.assertRaisesRegex(ValueError, 'existing draft lessons exactly once'):
                self.prepare(*args)
            self.assertEqual(self.output.read_bytes(), previous)
        saved = json.loads(previous)
        other = {**copy.deepcopy(saved['lessons'][0]), 'id': 'other-reviewed-lesson', 'audioLessonId': 'other-audio'}
        saved['lessons'].append(other)
        write_json(self.output, saved)
        previous = self.output.read_bytes()
        with self.assertRaisesRegex(ValueError, 'drop other guidance plans'):
            self.prepare('--lesson', self.lesson['id'])
        self.assertEqual(self.output.read_bytes(), previous)

    def test_input_aliases_and_unrelated_outputs_remain_intact(self):
        for path in (self.draft, self.targets, self.fixture.manifest_path):
            previous = path.read_bytes()
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.prepare(output=path)
            self.assertEqual(path.read_bytes(), previous)

    def test_distinct_scene_image_requires_and_uses_its_own_inspection(self):
        other = 'media/another-synthetic-scene.png'
        self.inspected['images'][other] = self.image(other, 'yellow')
        self.lesson['scenes'][0]['image'] = other
        self.inspected['targets']['synthetic-anchor']['image'] = other
        self.save()
        self.prepare()
        plan = json.loads(self.output.read_text())['lessons'][0]
        self.assertEqual(set(plan['images']), {self.lesson['poster'], self.lesson['realImage']['url'], other})
        self.assertEqual(plan['targets']['synthetic-anchor']['image'], other)

    def test_target_must_match_scene_and_clinical_targets_remain_uncropped(self):
        real = self.lesson['realImage']['url']
        self.inspected['targets']['synthetic-anchor']['image'] = real
        self.save()
        with self.assertRaisesRegex(ValueError, 'image displayed in its scene'):
            self.prepare()
        self.lesson['scenes'][0]['image'] = real
        self.save()
        self.prepare()
        self.assertEqual(json.loads(self.output.read_text())['lessons'][0]['targets']['synthetic-anchor']['zoom'], 1)
        previous = self.output.read_bytes()
        self.inspected['targets']['synthetic-anchor']['zoom'] = 1.13
        self.save()
        with self.assertRaisesRegex(ValueError, 'uncropped framing'):
            self.prepare()
        self.assertEqual(self.output.read_bytes(), previous)

    def test_output_failure_and_paused_source_leave_existing_guidance_unchanged(self):
        self.prepare()
        previous = self.output.read_bytes()
        with patch.object(guidance.os, 'replace', side_effect=OSError('Synthetic write failure')), self.assertRaises(OSError):
            self.prepare()
        self.assertEqual(self.output.read_bytes(), previous)
        self.assertFalse(list(self.output.parent.glob('.visual-guidance-*')))
        policy = self.fixture.policy_doc
        policy['newProductionEnabled'] = False
        write_json(self.root / 'production/source-policy.json', policy)
        before = self.fixture.manifest_path.read_bytes()
        with self.assertRaises(SourcePolicyError):
            self.prepare()
        self.assertEqual(self.fixture.manifest_path.read_bytes(), before)
        self.assertEqual(self.output.read_bytes(), previous)

    def audio_arguments(self):
        audio_input = self.root / 'private-content/audio-input.json'
        audio = {**copy.deepcopy(self.lesson), 'lessonId': self.lesson['id'],
                 'id': self.lesson['audioLessonId'], 'real_image_path': self.lesson['realImage']['url']}
        write_json(audio_input, {'bookId': ORIGINAL_BOOK, 'lessons': [audio]})
        model, voices = self.root / 'synthetic-model.onnx', self.root / 'synthetic-voices.bin'
        for path in (model, voices):
            path.write_text('Synthetic placeholder; a speech runtime must never open this fixture.')
        return ['generate_audio', '--input', str(audio_input), '--guidance', str(self.output),
                '--model', str(model), '--voices', str(voices), '--output', str(self.root / 'audio-output'),
                '--cache', str(self.root / 'audio-cache')]

    def test_audio_preflight_rejects_stale_guidance_before_loading_a_speech_runtime(self):
        self.prepare()
        arguments = self.audio_arguments()
        self.image(self.lesson['poster'], 'red')
        # If preflight is accidentally moved after imports, the sentinel modules
        # fail instead of letting a model load or actual narration be generated.
        with patch.object(generate_audio, 'PROJECT', self.root), patch.object(sys, 'argv', arguments), \
                patch.dict(sys.modules, {'onnxruntime': None, 'kokoro_onnx': None}), \
                self.assertRaisesRegex(ValueError, 'Guidance image changed'):
            generate_audio.main()
        self.assertFalse((self.root / 'audio-output').exists())
        self.assertFalse((self.root / 'audio-cache').exists())

    def test_audio_preflight_rejects_partial_unknown_selection_and_wrong_canonical_plan(self):
        self.prepare()
        arguments = self.audio_arguments()
        for selected in ((self.lesson['audioLessonId'], 'misspelled-audio-id'),
                         (self.lesson['audioLessonId'], self.lesson['audioLessonId'])):
            requested = [value for identity in selected for value in ('--lesson', identity)]
            with patch.object(generate_audio, 'PROJECT', self.root), patch.object(sys, 'argv', arguments + requested), \
                    patch.dict(sys.modules, {'onnxruntime': None, 'kokoro_onnx': None}), redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as error:
                generate_audio.main()
            self.assertEqual(error.exception.code, 2)
        saved = json.loads(self.output.read_text())
        saved['lessons'][0]['id'] = 'another-app-lesson'
        write_json(self.output, saved)
        errors = io.StringIO()
        with patch.object(generate_audio, 'PROJECT', self.root), patch.object(sys, 'argv', arguments), \
                patch.dict(sys.modules, {'onnxruntime': None, 'kokoro_onnx': None}), redirect_stderr(errors), \
                self.assertRaises(SystemExit) as error:
            generate_audio.main()
        self.assertEqual(error.exception.code, 2)
        self.assertIn('same canonical app lessonId', errors.getvalue())
        self.assertFalse((self.root / 'audio-output').exists())
        self.assertFalse((self.root / 'audio-cache').exists())

    def test_audio_preflight_checks_guidance_identity_when_input_id_is_already_canonical(self):
        self.prepare()
        arguments = self.audio_arguments()
        audio_input = Path(arguments[arguments.index('--input') + 1])
        document = json.loads(audio_input.read_text())
        audio = document['lessons'][0]
        audio['id'] = audio.pop('lessonId')
        write_json(audio_input, document)
        saved = json.loads(self.output.read_text())
        saved['lessons'][0].update(audioLessonId=audio['id'], id='another-app-lesson')
        write_json(self.output, saved)
        errors = io.StringIO()
        with patch.object(generate_audio, 'PROJECT', self.root), patch.object(sys, 'argv', arguments), \
                patch.dict(sys.modules, {'onnxruntime': None, 'kokoro_onnx': None}), redirect_stderr(errors), \
                self.assertRaises(SystemExit) as error:
            generate_audio.main()
        self.assertEqual(error.exception.code, 2)
        self.assertIn('same canonical app lessonId', errors.getvalue())
        self.assertFalse((self.root / 'audio-output').exists())
        self.assertFalse((self.root / 'audio-cache').exists())


if __name__ == '__main__':
    unittest.main()
