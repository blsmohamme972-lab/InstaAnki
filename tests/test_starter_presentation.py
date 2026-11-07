"""Verify the reviewed starter display proposal against real media and timing.

These checks protect the three existing teaching objectives while packaging
images differently and changing the player's effective ending.
"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from optimize_media import verify_same_pixels
from source_policy import canonical_hash, content_fingerprints, file_hash


def read(relative):
    return json.loads((ROOT / relative).read_text())


class StarterPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proposal = read('production/starter-presentation.json')
        cls.optimization = read('production/qa/starter-media-optimization.json')
        cls.lessons = {x['id']: x for x in read('web/data/lessons.json')}

    def test_only_existing_three_objectives_and_keys_are_retained(self):
        self.assertEqual({p['lessonId'] for p in self.proposal['lessons']},
                         {'shahzad2015-q005', 'shahzad2015-q054', 'shahzad2015-q182'})
        for p in self.proposal['lessons']:
            with self.subTest(lesson=p['lessonId']):
                live = self.lessons[p['lessonId']]
                self.assertEqual(content_fingerprints(live), {
                    k: p['baseline'][k] for k in ('authoredContentSha256', 'quizSha256')})
                self.assertEqual(canonical_hash(live['source']), p['baseline']['sourceSha256'])
                self.assertEqual(live['audioUrl'], p['baseline']['audioUrl'])
                if live['version'] == p['baseVersion']:
                    self.assertEqual(canonical_hash(live), p['baseline']['lessonSha256'])

    def test_audio_is_unchanged_and_ending_uses_recorded_last_voice_sample(self):
        for p in self.proposal['lessons']:
            with self.subTest(lesson=p['lessonId']):
                baseline, display = p['baseline'], p['presentation']
                audio = ROOT / 'web' / baseline['audioUrl']
                timing_path = ROOT / 'web' / baseline['timingPath']
                self.assertEqual(file_hash(audio), baseline['audioSha256'])
                self.assertEqual(file_hash(timing_path), baseline['timingSha256'])
                timing = json.loads(timing_path.read_text())
                self.assertEqual(timing['alignment'], 'independently-synthesized-phrase-samples')
                final = timing['scenes'][-1]
                end = final['voiceEndSample'] / timing['sampleRate']
                start = final['voiceStartSample'] / timing['sampleRate']
                self.assertEqual(display['effectiveEndSeconds'], end)
                self.assertEqual(display['narrationEndSeconds'], end)
                for section in ('clinicalGallery', 'recap'):
                    self.assertEqual(display[section]['startSeconds'], start)
                    self.assertEqual(display[section]['endSeconds'], end)
                self.assertAlmostEqual(timing['duration'] - end, 9.35, places=6)
                cues = {c['id']: c for c in timing['cues'] if c['sceneId'] == final['id']}
                bindings = display['recap']['cueBindings']
                self.assertEqual({b['phraseId'] for b in bindings}, set(cues))
                nodes = {node['id'] for node in display['recap']['nodes']}
                self.assertTrue(2 <= len(nodes) <= 4)
                for binding in bindings:
                    cue = cues[binding['phraseId']]
                    self.assertEqual(binding['startSeconds'], cue['voiceStart'])
                    self.assertEqual(binding['endSeconds'], cue['voiceEnd'])
                    self.assertIn(binding['nodeId'], nodes)

    def test_three_licensed_full_images_are_collectible_in_each_gallery(self):
        for p in self.proposal['lessons']:
            with self.subTest(lesson=p['lessonId']):
                images = p['presentation']['clinicalGallery']['images']
                self.assertEqual(len(images), 3)
                self.assertEqual(len({i['url'] for i in images}), 3)
                self.assertEqual(images, p['realImages'])
                for image in images:
                    path = ROOT / 'web' / image['url']
                    self.assertTrue(path.is_file(), path)
                    self.assertEqual(file_hash(path), image['sha256'])
                    self.assertEqual(file_hash(ROOT / 'web' / image['originalPath']), image['originalSha256'])
                    for field in ('title', 'caption', 'sourceUrl', 'author', 'license',
                                  'licenseUrl', 'attribution', 'caseRelationship', 'visualInspection'):
                        self.assertTrue(image.get(field), field)
                    self.assertEqual(image['checkedOn'], '2026-11-07')
                    self.assertFalse(image['encoding']['resized'])
                    self.assertFalse(image['encoding']['newLossyEncoding'])

    def test_actual_saved_files_reproduce_pixels_alpha_colour_and_size(self):
        assets = self.optimization['assets']
        self.assertEqual(len(assets), 12)
        self.assertEqual(len({a['sourcePath'] for a in assets}), 12)
        before, after = 0, 0
        for asset in assets:
            with self.subTest(asset=asset['sourcePath']):
                source = ROOT / 'web' / asset['sourcePath']
                output = ROOT / 'web' / asset['outputPath']
                self.assertEqual(file_hash(source), asset['originalSha256'])
                self.assertEqual(file_hash(output), asset['sha256'])
                self.assertEqual(source.stat().st_size, asset['originalBytes'])
                self.assertEqual(output.stat().st_size, asset['optimizedBytes'])
                self.assertLessEqual(output.stat().st_size, source.stat().st_size)
                actual = verify_same_pixels(source.read_bytes(), output.read_bytes())
                self.assertEqual(actual, asset['decoded'])
                self.assertEqual(asset['imageBytesModified'], source.read_bytes() != output.read_bytes())
                self.assertEqual(asset['encodedBytesModified'], asset['imageBytesModified'])
                before += source.stat().st_size
                after += output.stat().st_size
        self.assertEqual(before, self.optimization['originalBytes'])
        self.assertEqual(after, self.optimization['optimizedBytes'])
        self.assertEqual(before - after, self.optimization['savedBytes'])
        self.assertLess(after, before)


if __name__ == '__main__':
    unittest.main()
