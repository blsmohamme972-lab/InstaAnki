#!/usr/bin/env python3
"""Choose a smaller *lossless* image encoding after exact pixel verification.

Original files are never overwritten. There is no resize or lossy fallback.
The report preserves supplied provenance and records both encoded and decoded
hashes so a byte change cannot be misreported as an unchanged original file.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, PngImagePlugin, features


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decoded_signature(data: bytes) -> dict:
    """Hash every decoded RGBA channel, including RGB under transparent pixels."""
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        rgba = image.convert('RGBA')
        return {
            'width': image.width,
            'height': image.height,
            'rgbaSha256': sha256(rgba.tobytes()),
            'alphaSha256': sha256(rgba.getchannel('A').tobytes()),
            'iccProfileSha256': sha256(image.info.get('icc_profile') or b''),
            'orientation': image.getexif().get(274, 1),
            'frames': getattr(image, 'n_frames', 1),
        }


def verify_same_pixels(original: bytes, candidate: bytes) -> dict:
    before, after = decoded_signature(original), decoded_signature(candidate)
    if before != after:
        differences = [key for key in before if before[key] != after[key]]
        raise ValueError('Lossless verification failed: ' + ', '.join(differences))
    return after


def encode_candidates(image: Image.Image):
    """Yield only lossless encodings; metadata affecting display is retained."""
    metadata = {}
    for key in ('icc_profile', 'exif'):
        if image.info.get(key):
            metadata[key] = image.info[key]
    png_info = PngImagePlugin.PngInfo()
    for key, value in image.info.items():
        if isinstance(value, str):
            png_info.add_itxt(key, value)
    png = io.BytesIO()
    image.save(png, format='PNG', optimize=True, compress_level=9,
               pnginfo=png_info, **metadata)
    yield 'png', png.getvalue(), 'PNG optimize=True, compress_level=9'
    # A grayscale ICC profile cannot be attached to a converted RGB WebP.
    if features.check('webp') and not (image.info.get('icc_profile') and image.mode not in ('RGB', 'RGBA')):
        webp = io.BytesIO()
        if image.info.get('xmp'):
            metadata['xmp'] = image.info['xmp']
        pixels = image.convert('RGBA') if image.mode in ('P', 'LA', 'RGBA') or 'transparency' in image.info else image.convert('RGB')
        pixels.save(webp, format='WEBP', lossless=True, quality=100, method=6,
                    exact=True, **metadata)
        yield 'webp', webp.getvalue(), 'WebP lossless=True, exact=True, method=6, quality=100'


def optimize_image(source: Path, output_dir: Path, provenance: dict | None = None) -> dict:
    source, output_dir = Path(source).resolve(), Path(output_dir).resolve()
    original = source.read_bytes()
    original_sha = sha256(original)
    signature = decoded_signature(original)
    supplied = deepcopy(provenance or {})
    if supplied.get('sha256') and supplied['sha256'] != original_sha:
        raise ValueError(f'Provenance SHA-256 does not match original: {source}')
    selected = original
    selected_ext = source.suffix.lstrip('.').lower()
    encoding = 'original bytes retained'
    attempts = []
    reason = 'No verified smaller lossless candidate.'
    with Image.open(io.BytesIO(original)) as image:
        image.load()
        # Retaining original is safer than flattening animation, reducing bit
        # depth, changing CMYK colour interpretation or altering orientation.
        supported = image.mode in ('RGB', 'RGBA', 'L', 'LA', 'P')
        guarded_colour = any(key in image.info for key in ('gamma', 'chromaticity', 'srgb'))
        if signature['frames'] != 1:
            reason = 'Animated/multipage original retained; all frames must remain intact.'
        elif not supported:
            reason = f'Original {image.mode} retained; no bit-depth or colour-mode reduction.'
        elif signature['orientation'] != 1:
            reason = 'Original retained to preserve non-default EXIF orientation across decoders.'
        elif guarded_colour:
            reason = 'Original retained to preserve explicit PNG colour/gamma metadata.'
        else:
            for extension, candidate, settings in encode_candidates(image):
                verified = False
                error = None
                try:
                    verify_same_pixels(original, candidate)
                    verified = True
                except ValueError as exc:
                    error = str(exc)
                attempts.append({'format': extension, 'bytes': len(candidate),
                                 'pixelsIdentical': verified, 'settings': settings,
                                 **({'rejectedReason': error} if error else {})})
                if verified and len(candidate) < len(selected):
                    selected, selected_ext, encoding = candidate, extension, settings
                    reason = 'Smallest verified candidate; decoded pixels and alpha are identical.'
    changed = selected != original
    output = source
    if changed:
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f'{source.stem}.{original_sha[:12]}.lossless.{selected_ext}'
        if output.resolve() == source:
            raise ValueError('Optimization must never overwrite the original image.')
        if output.exists() and output.read_bytes() != selected:
            raise ValueError(f'Refusing to overwrite a different existing output: {output}')
        output.write_bytes(selected)
        # Verify the actual saved bytes, not only an in-memory encoder result.
        verify_same_pixels(original, output.read_bytes())
    return {
        'sourcePath': str(source), 'outputPath': str(output),
        'originalSha256': original_sha, 'sha256': sha256(selected),
        'originalBytes': len(original), 'optimizedBytes': len(selected),
        'savedBytes': len(original)-len(selected),
        'savedPercent': round(100*(len(original)-len(selected))/len(original), 3),
        'imageBytesModified': changed, 'encodedBytesModified': changed,
        'pixelsIdentical': True,
        'alphaIdentical': True, 'resized': False, 'lossy': False,
        'decoded': signature, 'encoding': encoding, 'decision': reason,
        'candidates': attempts, 'provenance': supplied,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-manifest', type=Path, required=True,
                        help='JSON object with assets [{path, provenance}].')
    parser.add_argument('--root', type=Path, required=True,
                        help='Root for asset paths; report paths are relative to this root.')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    data = json.loads(args.input_manifest.read_text())
    assets = data.get('assets')
    if not isinstance(assets, list) or not assets:
        parser.error('input manifest requires a nonempty assets array')
    results = []
    seen = set()
    for entry in assets:
        relative = Path(entry['path'])
        path = (root / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root):
            raise ValueError('Asset paths must stay within --root')
        if path in seen:
            raise ValueError(f'Duplicate input asset: {relative}')
        seen.add(path)
        result = optimize_image(path, args.output_dir, entry.get('provenance'))
        for field in ('sourcePath', 'outputPath'):
            p = Path(result[field])
            result[field] = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
        results.append(result)
        print(f'{relative}: {result["originalBytes"]} -> {result["optimizedBytes"]} bytes; exact pixels verified', flush=True)
    before = sum(x['originalBytes'] for x in results)
    after = sum(x['optimizedBytes'] for x in results)
    report = {
        'schemaVersion': 1, 'method': 'lossless-candidates-with-exact-decoded-rgba-verification',
        'policy': 'No resizing, lossy fallback, alpha changes, original replacement or provenance loss.',
        'originalBytes': before, 'optimizedBytes': after, 'savedBytes': before-after,
        'savedPercent': round(100*(before-after)/before, 3), 'assets': results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
