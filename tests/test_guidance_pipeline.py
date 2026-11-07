"""Regression checks for measured phrase timing and stale target rejection."""
import copy
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from guidance import assemble_guidance, validate_plan, verify_guidance


class GuidancePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lessons = json.loads((ROOT / 'web/data/lessons.json').read_text())
        cls.plans = json.loads((ROOT / 'production/visual-guidance.json').read_text())['lessons']

    def inputs(self, index=0):
        lesson = copy.deepcopy(self.lessons[index])
        timing = json.loads((ROOT / 'web' / lesson['audioUrl']).with_suffix('.timing.json').read_text())
        return lesson, timing

    def test_all_recordings_and_reviewed_assets_match_measured_cues(self):
        for index in range(len(self.lessons)):
            with self.subTest(index=index):
                lesson, timing = self.inputs(index)
                result = verify_guidance(lesson, timing, ROOT / 'web')
                self.assertGreater(result['cueCount'], len(lesson['scenes']))
                self.assertEqual(result['alignment'], 'independently-synthesized-phrase-samples')

    def test_audio_replacement_is_rejected_even_when_duration_is_unchanged(self):
        lesson, timing = self.inputs()
        original_duration = timing['duration']
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / lesson['audioUrl']
            destination.parent.mkdir(parents=True)
            source = (ROOT / 'web' / lesson['audioUrl']).read_bytes()
            # An added trailing byte does not alter MPEG duration, but it changes
            # the exact file whose timing was reviewed. The validator fails first.
            destination.write_bytes(source + b'\x00')
            probe = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json']
            original = json.loads(subprocess.check_output(probe + [str(ROOT / 'web' / lesson['audioUrl'])]))
            changed = json.loads(subprocess.check_output(probe + [str(destination)]))
            self.assertEqual(original['format']['duration'], changed['format']['duration'])
            with self.assertRaisesRegex(ValueError, 'Audio bytes changed'):
                verify_guidance(lesson, timing, temp)
        self.assertEqual(timing['duration'], original_duration)

    def test_image_replacement_requires_target_review(self):
        lesson, timing = self.inputs()
        image = next(iter(lesson['visualGuidance']['images'].values()))
        image['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'image changed'):
            verify_guidance(lesson, timing, ROOT / 'web')

    def test_pointer_on_wrong_image_is_rejected(self):
        lesson, timing = self.inputs()
        cue = next(c for c in lesson['visualGuidance']['cues'] if c['targetId'] is not None)
        other = next(key for key, target in lesson['visualGuidance']['targets'].items()
                     if target['image'] != lesson['scenes'][0]['image'])
        cue['targetId'] = other
        timing['cues'] = copy.deepcopy(lesson['visualGuidance']['cues'])
        with self.assertRaisesRegex(ValueError, 'not on the displayed image'):
            verify_guidance(lesson, timing, ROOT / 'web')

    def test_cue_boundary_estimate_is_rejected(self):
        lesson, timing = self.inputs()
        lesson['visualGuidance']['cues'][0]['voiceStart'] += .03
        timing['cues'] = copy.deepcopy(lesson['visualGuidance']['cues'])
        with self.assertRaisesRegex(ValueError, 'not its measured sample boundary'):
            verify_guidance(lesson, timing, ROOT / 'web')

    def test_cue_overlap_is_rejected(self):
        lesson, timing = self.inputs()
        cue = lesson['visualGuidance']['cues'][1]
        cue['startSample'] -= 120
        cue['start'] = cue['startSample'] / timing['sampleRate']
        timing['cues'] = copy.deepcopy(lesson['visualGuidance']['cues'])
        with self.assertRaisesRegex(ValueError, 'gap or overlap'):
            verify_guidance(lesson, timing, ROOT / 'web')

    def test_incomplete_scene_plan_cannot_silently_zip_truncate(self):
        plan = copy.deepcopy(self.plans[0])
        original = self.lessons[0]['scenes']
        plan['scenes'].pop()
        with self.assertRaisesRegex(ValueError, 'same scene count'):
            validate_plan(plan, original, ROOT / 'web')

    def test_plan_change_requires_regeneration(self):
        lesson, timing = self.inputs()
        plan = copy.deepcopy(self.plans[0])
        plan['scenes'][0]['phrases'][0]['targetId'] = None
        with self.assertRaisesRegex(ValueError, 'plan changed after audio was rendered'):
            assemble_guidance(plan, timing, lesson['scenes'], lesson['audioUrl'], ROOT / 'web')


if __name__ == '__main__':
    unittest.main()
