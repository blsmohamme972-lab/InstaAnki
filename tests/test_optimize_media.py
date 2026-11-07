"""Quality gates for the lossless image optimizer."""
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image

SPEC = importlib.util.spec_from_file_location('optimize_media', Path(__file__).parents[1] / 'tools/optimize_media.py')
media = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(media)


class LosslessMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make(self, name='input.png', mode='RGB', colour=(18, 91, 143)):
        p = self.root / name
        Image.new(mode, (96, 96), colour).save(p, compress_level=0)
        return p

    def test_smaller_output_preserves_all_pixels_and_original(self):
        p = self.make()
        original = p.read_bytes()
        provenance = {'license': 'CC BY 4.0', 'sourceUrl': 'https://example.org/original', 'sha256': media.sha256(original)}
        result = media.optimize_image(p, self.root/'out', provenance)
        self.assertLess(result['optimizedBytes'], result['originalBytes'])
        self.assertEqual(p.read_bytes(), original)
        self.assertEqual(result['provenance'], provenance)
        self.assertTrue(result['imageBytesModified'])
        media.verify_same_pixels(original, Path(result['outputPath']).read_bytes())

    def test_hidden_rgb_and_alpha_survive_transparency(self):
        p = self.make(mode='RGBA', colour=(238, 14, 193, 0))
        im = Image.open(p); im.putpixel((12, 12), (35, 88, 214, 127)); im.save(p, compress_level=0)
        result = media.optimize_image(p, self.root/'out')
        with Image.open(result['outputPath']) as output:
            self.assertEqual(output.convert('RGBA').getpixel((0, 0)), (238, 14, 193, 0))
            self.assertEqual(output.convert('RGBA').getpixel((12, 12)), (35, 88, 214, 127))

    def test_larger_candidate_keeps_original(self):
        p = self.make()
        original = p.read_bytes()
        with mock.patch.object(media, 'encode_candidates', return_value=iter([('png', original+b'padding', 'test lossless candidate')])):
            result = media.optimize_image(p, self.root/'out')
        self.assertFalse(result['imageBytesModified'])
        self.assertEqual(Path(result['outputPath']), p)
        self.assertFalse((self.root/'out').exists())

    def test_pixel_changed_candidate_is_rejected_even_if_smaller(self):
        p = self.make()
        b = io.BytesIO(); Image.new('RGB', (96,96), (0,0,0)).save(b, 'PNG')
        with mock.patch.object(media, 'encode_candidates', return_value=iter([('png', b.getvalue(), 'incorrect encoder')])):
            result = media.optimize_image(p, self.root/'out')
        self.assertFalse(result['imageBytesModified'])
        self.assertFalse(result['candidates'][0]['pixelsIdentical'])

    def test_incorrect_provenance_hash_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Provenance SHA-256'):
            media.optimize_image(self.make(), self.root/'out', {'sha256': '0'*64})

    def test_nondefault_orientation_is_not_changed(self):
        p = self.root/'rotated.jpg'
        exif = Image.Exif(); exif[274] = 6
        Image.new('RGB',(24,16),(42,91,151)).save(p, exif=exif)
        result = media.optimize_image(p, self.root/'out')
        self.assertFalse(result['imageBytesModified'])
        self.assertIn('orientation', result['decision'])

    def test_animation_is_not_flattened(self):
        p = self.root/'animated.gif'
        a = Image.new('RGB',(16,16),'red'); b = Image.new('RGB',(16,16),'blue')
        a.save(p, save_all=True, append_images=[b], duration=120, loop=0)
        result = media.optimize_image(p, self.root/'out')
        self.assertFalse(result['imageBytesModified'])
        self.assertEqual(result['decoded']['frames'], 2)

    def test_sixteen_bit_source_keeps_original_precision(self):
        p = self.root/'high-depth.png'
        Image.new('I;16',(12,12),43000).save(p)
        result = media.optimize_image(p, self.root/'out')
        self.assertFalse(result['imageBytesModified'])
        self.assertIn('bit-depth', result['decision'])


if __name__ == '__main__':
    unittest.main()
