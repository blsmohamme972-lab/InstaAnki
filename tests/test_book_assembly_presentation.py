"""Book assembly preserves source identities and measured presentation evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from assemble_book_batch import assemble_presentation, normalized_real_images, validate_presentation_plan
import assemble_book_batch as assembly
from presentation import validate_presentation


class BookAssemblyPresentationTests(unittest.TestCase):
    def setUp(self):
        self.images = [{
            "url": f"media/real/synthetic-{index}.png", "title": f"Synthetic image {index}",
            "caption": "Synthetic nonmedical test image.", "author": "Fixture author",
            "license": "CC0 1.0", "licenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
            "sourceUrl": f"https://example.org/fixtures/{index}", "attribution": "Fixture attribution",
            "aiGenerated": False, "sha256": f"{index:064x}",
        } for index in (1, 2, 3)]
        self.draft = {
            "realImage": deepcopy(self.images[0]), "realImages": deepcopy(self.images),
            "scenes": [
                {"id": "intro", "phrases": [{"id": "intro-p01", "text": "Synthetic introduction."}]},
                {"id": "ending", "phrases": [
                    {"id": "ending-p01", "text": "First synthetic point."},
                    {"id": "ending-p02", "text": "Second synthetic point."},
                    {"id": "ending-p03", "text": "Third synthetic point."},
                ]},
            ],
            "presentationPlan": {"schemaVersion": 1, "endingSceneId": "ending", "recap": {
                "nodes": [{"id": f"n{index}", "label": f"Synthetic point {index}"} for index in (1, 2, 3)],
                "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
                "cueBindings": [{"phraseId": f"ending-p0{index}", "nodeId": f"n{index}"} for index in (1, 2, 3)],
            }},
        }
        # Fractional sample boundaries deliberately cannot be replaced with
        # rounded planning estimates. The encoded stream also has a silent tail.
        self.voice_end = 1484473 / 24000
        self.timing = {
            "duration": self.voice_end + 9.35,
            "scenes": [{"id": "intro", "voiceStart": .18, "voiceEnd": 50.02},
                       {"id": "ending", "voiceStart": 50.25, "voiceEnd": self.voice_end}],
            "cues": [
                {"id": "intro-p01", "sceneId": "intro", "voiceStart": .18, "voiceEnd": 50.02},
                {"id": "ending-p01", "sceneId": "ending", "voiceStart": 50.25, "voiceEnd": 54.125},
                {"id": "ending-p02", "sceneId": "ending", "voiceStart": 54.205, "voiceEnd": 58.1},
                {"id": "ending-p03", "sceneId": "ending", "voiceStart": 58.18, "voiceEnd": self.voice_end},
            ],
        }

    def test_ending_uses_exact_final_voice_samples_instead_of_encoded_silent_tail(self):
        images = normalized_real_images(self.draft)
        result = assemble_presentation(self.draft, self.timing, images)
        self.assertEqual(result["effectiveEndSeconds"], self.voice_end)
        self.assertLess(result["effectiveEndSeconds"], self.timing["duration"])
        self.assertEqual(result["clinicalGallery"]["startSeconds"], 50.25)
        self.assertEqual(result["recap"]["endSeconds"], self.voice_end)
        for binding, cue in zip(result["recap"]["cueBindings"], self.timing["cues"][1:]):
            self.assertEqual(binding["startSeconds"], cue["voiceStart"])
            self.assertEqual(binding["endSeconds"], cue["voiceEnd"])
        validate_presentation({"durationSeconds": self.timing["duration"], "presentation": result,
                               "visualGuidance": {"cues": self.timing["cues"]}, "realImages": images})
        # Assembly must not alias back to the source-reviewed private draft.
        result["recap"]["nodes"][0]["label"] = "A changed label"
        result["clinicalGallery"]["images"][0]["caption"] = "A changed caption"
        self.assertEqual(self.draft["presentationPlan"]["recap"]["nodes"][0]["label"], "Synthetic point 1")
        self.assertEqual(images[0]["caption"], "Synthetic nonmedical test image.")

    def test_gallery_requires_three_distinct_licensed_records_and_stable_primary(self):
        changes = [
            ("count", lambda d: d["realImages"].pop()),
            ("primary", lambda d: d["realImage"].update(caption="Different source caption")),
            ("duplicate URL", lambda d: d["realImages"][2].update(url=d["realImages"][1]["url"])),
            ("duplicate bytes", lambda d: d["realImages"][2].update(sha256=d["realImages"][1]["sha256"])),
            ("generated", lambda d: d["realImages"][2].update(aiGenerated=True)),
            ("missing caption", lambda d: d["realImages"][2].update(caption="")),
            ("missing license", lambda d: d["realImages"][2].update(licenseUrl="")),
            ("unsafe source", lambda d: d["realImages"][2].update(sourceUrl="http://example.org/image")),
        ]
        for label, change in changes:
            draft = deepcopy(self.draft)
            change(draft)
            with self.subTest(label=label), self.assertRaises(ValueError):
                normalized_real_images(draft)

    def assert_noncanonical_image_rejected(self, change):
        for location in ("realImage", "realImages"):
            draft = deepcopy(self.draft)
            image = draft["realImage"] if location == "realImage" else draft["realImages"][2]
            change(image)
            unchanged = deepcopy(draft)
            with self.subTest(location=location), self.assertRaisesRegex(
                    ValueError, "canonical before source review"):
                normalized_real_images(draft)
            self.assertEqual(draft, unchanged)

    def test_leading_slash_image_urls_fail_before_reviewed_provenance_is_rewritten(self):
        self.assert_noncanonical_image_rejected(
            lambda image: image.update(url="/" + image["url"]))

    def test_public_path_only_images_require_an_explicit_canonical_url(self):
        self.assert_noncanonical_image_rejected(
            lambda image: image.update(publicPath=image.pop("url")))

    def test_license_objects_require_a_string_license_and_explicit_license_url(self):
        self.assert_noncanonical_image_rejected(
            lambda image: image.update(license={"name": image["license"],
                                               "url": image.pop("licenseUrl")}))

    def test_canonical_images_preserve_all_provenance_without_mutating_the_draft(self):
        for image in self.draft["realImages"]:
            image["sourceDetails"] = {"dimensions": {"width": 20, "height": 30},
                                      "note": "Synthetic provenance extension."}
        self.draft["realImage"] = deepcopy(self.draft["realImages"][0])
        unchanged = deepcopy(self.draft)
        images = normalized_real_images(self.draft)
        self.assertEqual(images, self.draft["realImages"])
        self.assertEqual(self.draft, unchanged)
        images[0]["sourceDetails"]["dimensions"]["width"] = 99
        self.assertEqual(self.draft, unchanged)

    def test_plan_cannot_silently_omit_the_gallery_or_use_an_earlier_scene(self):
        draft = deepcopy(self.draft)
        del draft["presentationPlan"]
        with self.assertRaisesRegex(ValueError, "presentationPlan schemaVersion 1"):
            validate_presentation_plan(draft)
        draft = deepcopy(self.draft)
        draft["presentationPlan"]["endingSceneId"] = "intro"
        with self.assertRaisesRegex(ValueError, "final narrated scene"):
            validate_presentation_plan(draft)
        draft = deepcopy(self.draft)
        draft["presentationPlan"]["recap"]["cueBindings"][0]["phraseId"] = "intro-p01"
        with self.assertRaisesRegex(ValueError, "final-scene phraseId"):
            validate_presentation_plan(draft)

    def test_unvoiced_nodes_reordered_phrases_and_authored_timestamps_are_rejected(self):
        changes = [
            lambda p: p["nodes"].append({"id": "unvoiced", "label": "An unspoken addition"}),
            lambda p: p["cueBindings"].reverse(),
            lambda p: p["cueBindings"][0].update(startSeconds=50.25, endSeconds=54.125),
            lambda p: p["cueBindings"].append(deepcopy(p["cueBindings"][-1])),
            lambda p: p["edges"].append({"from": "n1", "to": "missing"}),
        ]
        for index, change in enumerate(changes):
            draft = deepcopy(self.draft)
            change(draft["presentationPlan"]["recap"])
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate_presentation_plan(draft)

    def test_stale_or_impossible_timing_cannot_be_attached_to_the_ending(self):
        changes = [
            lambda t: t["scenes"][-1].update(voiceEnd=self.voice_end + .02),
            lambda t: t["scenes"][-1].update(voiceStart=50.0),
            lambda t: t["scenes"][-1].update(id="unreviewed-ending"),
            lambda t: t["cues"].pop(),
            lambda t: t["cues"][1].update(id="unreviewed-phrase"),
            lambda t: t["cues"][0].update(voiceEnd=self.voice_end + 1),
            lambda t: t["cues"][1].update(voiceEnd=float("nan")),
            lambda t: t["cues"][2].update(voiceStart=54.0),
        ]
        for index, change in enumerate(changes):
            timing = deepcopy(self.timing)
            change(timing)
            with self.subTest(index=index), self.assertRaises(ValueError):
                assemble_presentation(self.draft, timing, self.images)


class BookMergeSafetyTests(unittest.TestCase):
    def lesson(self, number, *, identity=None, version=1):
        return {'id': identity or f'synthetic-q{number}', 'version': version,
                'source': {'bookId': assembly.BOOK_ID, 'questionNumber': number}}

    def test_mixed_book_inputs_fail_without_discarding_existing_data(self):
        original = [self.lesson(1)]
        other = self.lesson(2)
        other['source']['bookId'] = 'unapproved-independent-collection'
        for current, incoming in (([other], original), (original, [other])):
            before = deepcopy((current, incoming))
            with self.subTest(current=current), self.assertRaisesRegex(ValueError, 'original book only'):
                assembly.merge_lessons(current, incoming)
            self.assertEqual((current, incoming), before)

    def test_duplicate_or_reassigned_source_identities_fail_before_merge(self):
        original = self.lesson(1)
        invalid = [
            ([original, deepcopy(original)], []),
            ([], [original, deepcopy(original)]),
            ([original, self.lesson(1, identity='renamed-q1')], []),
            ([], [original, self.lesson(1, identity='renamed-q1')]),
            ([original], [self.lesson(1, identity='renamed-q1')]),
            ([original], [self.lesson(2, identity=original['id'])]),
        ]
        for current, incoming in invalid:
            before = deepcopy((current, incoming))
            with self.subTest(current=current, incoming=incoming), self.assertRaises(ValueError):
                assembly.merge_lessons(current, incoming)
            self.assertEqual((current, incoming), before)

    def test_valid_append_and_revision_keep_ids_and_require_explicit_version_changes(self):
        first, second = self.lesson(1), self.lesson(2)
        before = deepcopy([first])
        self.assertEqual(assembly.merge_lessons([first], [second]), [first, second])
        self.assertEqual(assembly.merge_lessons([first], [deepcopy(first)]), [first])
        corrected = {**deepcopy(first), 'version': 2, 'title': 'Reviewed correction fixture'}
        self.assertEqual(assembly.merge_lessons([first, second], [corrected]), [corrected, second])
        with self.assertRaisesRegex(ValueError, 'revision increment'):
            assembly.merge_lessons([first], [{**first, 'title': 'Changed without a revision'}])
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            assembly.merge_lessons([corrected], [first])
        self.assertEqual([first], before)

    def test_cli_output_aliases_cannot_overwrite_inputs_or_other_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'production').mkdir()
            policy = root / 'production/source-policy.json'
            policy.write_bytes((ROOT / 'production/source-policy.json').read_bytes())
            draft, guidance, registry, output = [root / name for name in (
                'draft.json', 'visual-guidance.json', 'registry.json', 'existing-output.json')]
            for path in (draft, guidance, registry, output):
                path.write_text(json.dumps({'synthetic': path.name}))
            base = ['assemble_book_batch', '--input', str(draft), '--guidance', str(guidance), '--registry', str(registry)]
            cases = [
                ['--output', str(output), '--validation-output', str(output)],
                ['--prepare-audio', str(draft)],
                ['--output', str(guidance)],
                ['--validation-output', str(draft)],
                ['--output', str(policy)],
                ['--output', str(output), '--merge', '--app-lessons', str(output)],
            ]
            before = {path: path.read_bytes() for path in (policy, draft, guidance, registry, output)}
            for args in cases:
                with self.subTest(args=args), patch.object(assembly, 'ROOT', root), patch.object(sys, 'argv', base + args), \
                        patch.object(assembly, 'load_draft') as load, self.assertRaisesRegex(ValueError, 'outputs must use distinct|output must not overwrite'):
                    assembly.main()
                load.assert_not_called()
                self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_write_failure_preserves_existing_output_and_an_unrelated_dot_tmp_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'lessons.json'
            unrelated = root / 'lessons.json.tmp'
            output.write_text('Existing reviewed output')
            unrelated.write_text('Another retained input must remain intact')
            with patch.object(assembly.os, 'replace', side_effect=OSError('Synthetic write failure')), self.assertRaises(OSError):
                assembly.write(output, [])
            self.assertEqual(output.read_text(), 'Existing reviewed output')
            self.assertEqual(unrelated.read_text(), 'Another retained input must remain intact')
            self.assertFalse(list(root.glob('.book-assembly-*')))


if __name__ == "__main__":
    unittest.main()
