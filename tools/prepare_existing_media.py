#!/usr/bin/env python3
"""Verify or restore the reviewed images for the existing three lessons.

The checked-in manifests pin every accepted path, byte length and SHA-256.
Default mode only verifies. Downloads are opt-in and restricted to the six
reviewed public originals; ZIP restore only reads expected image members.
Existing files are never replaced, including on an integrity failure.
"""
from __future__ import annotations

import argparse
from datetime import timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import random
import re
import stat
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PILLOW_VERSION = '13.0.0'
WEBP_VERSION = '1.6.0'
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_BYTES = 128 * 1024 * 1024
LESSON_IDS = {'shahzad2015-q005', 'shahzad2015-q054', 'shahzad2015-q182'}
DOWNLOAD_PATHS = {
    'media/real/starter-q005-ct.png',
    'media/real/starter-q005-followup-ct.png',
    'media/real/starter-q054-collaterals.png',
    'media/real/starter-q054-small-rca.png',
    'media/real/starter-q182-arteriole.jpg',
    'media/real/starter-q182-celiac-ultrasound.jpg',
}
SOURCE_PATHS = DOWNLOAD_PATHS | {
    'media/mnemonic/coronary-palace.png',
    'media/mnemonic/sequestration-palace.png',
    'media/mnemonic/resistance-palace.png',
    'media/real/coronary-dominance-angiograms.png',
    'media/real/extralobar-sequestration-thoracoscopy.jpg',
    'media/real/artery-cross-section.png',
}
DOWNLOAD_HOSTS = {'media.springernature.com', 'upload.wikimedia.org'}
USER_AGENT = ('InstaAnki-reviewed-media-restore/0.2 '
              '(https://github.com/blsmohamme972-lab/InstaAnki)')
TRANSIENT_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}
MAX_DOWNLOAD_ATTEMPTS = 4
MAX_RETRY_WAIT_SECONDS = 180
SHA256_RE = re.compile(r'[0-9a-f]{64}\Z')


class MediaPreparationError(ValueError):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def checked_hash(value):
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise MediaPreparationError('Media recipe needs an exact lowercase SHA-256')
    return value


def checked_size(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= MAX_IMAGE_BYTES:
        raise MediaPreparationError('Media recipe has an invalid pinned image size')
    return value


def image_path(web_root, value):
    if not isinstance(value, str):
        raise MediaPreparationError('Expected image path is missing')
    path = PurePosixPath(value)
    if (path.is_absolute() or not value.startswith('media/') or '\\' in value
            or any(part in {'', '.', '..'} for part in value.split('/'))
            or path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}):
        raise MediaPreparationError(f'Unsafe or non-image media path: {value!r}')
    destination = web_root / value
    # Avoid following a destination symlink even when its target remains inside
    # the checkout. This command restores files, not directory topology.
    relative = destination.relative_to(web_root)
    probe = web_root
    for part in relative.parts:
        probe = probe / part
        if probe.is_symlink():
            raise MediaPreparationError(f'Symlink is not a restorable image path: {value}')
    if not destination.resolve().is_relative_to(web_root.resolve()):
        raise MediaPreparationError(f'Image path escapes the web root: {value}')
    return destination


def load_recipe(repo):
    try:
        manifest = json.loads((repo / 'production/starter-media-originals.json').read_text())
        report = json.loads((repo / 'production/qa/starter-media-optimization.json').read_text())
    except (OSError, ValueError) as exc:
        raise MediaPreparationError(f'Cannot read the reviewed media recipe: {exc}') from exc
    entries = manifest.get('assets', [])
    results = report.get('assets', [])
    if not isinstance(entries, list) or not isinstance(results, list):
        raise MediaPreparationError('Media recipe assets must be arrays')
    try:
        originals = {entry['path']: entry for entry in entries}
        outputs = {entry['sourcePath']: entry for entry in results}
    except (TypeError, KeyError) as exc:
        raise MediaPreparationError('Malformed media recipe asset') from exc
    if (set(originals) != SOURCE_PATHS or set(outputs) != SOURCE_PATHS
            or len(entries) != len(SOURCE_PATHS) or len(results) != len(SOURCE_PATHS)):
        raise MediaPreparationError('Recipe must contain exactly the twelve reviewed existing-lesson images')
    specs, destinations = [], set()
    for source in sorted(SOURCE_PATHS):
        original, result = originals[source], outputs[source]
        provenance = original.get('provenance', {})
        if (provenance.get('lessonId') not in LESSON_IDS
                or provenance != result.get('provenance')):
            raise MediaPreparationError(f'Recipe provenance differs from its reviewed optimization: {source}')
        original_hash = checked_hash(result.get('originalSha256'))
        output_hash = checked_hash(result.get('sha256'))
        if provenance.get('sha256') != original_hash:
            raise MediaPreparationError(f'Original provenance hash mismatch: {source}')
        original_size = checked_size(result.get('originalBytes'))
        output_size = checked_size(result.get('optimizedBytes'))
        output = result.get('outputPath')
        image_path(repo / 'web', source)
        image_path(repo / 'web', output)
        changed = result.get('imageBytesModified')
        if not isinstance(changed, bool) or result.get('encodedBytesModified') != changed:
            raise MediaPreparationError(f'Recipe encoding-change flags disagree: {source}')
        if changed:
            expected_stem = f'{PurePosixPath(source).stem}.{original_hash[:12]}.lossless'
            if (PurePosixPath(output).parent != PurePosixPath('media/optimized')
                    or PurePosixPath(output).stem != expected_stem
                    or PurePosixPath(output).suffix not in {'.webp', '.png'}
                    or output_size >= original_size):
                raise MediaPreparationError(f'Unexpected lossless output identity: {source}')
        elif output != source or output_hash != original_hash or output_size != original_size:
            raise MediaPreparationError(f'Unmodified image must retain its exact original bytes: {source}')
        if output in destinations:
            raise MediaPreparationError('Duplicate expected output image path')
        destinations.add(output)
        specs.append({'sourcePath': source, 'outputPath': output,
                      'originalSha256': original_hash, 'sha256': output_hash,
                      'originalBytes': original_size, 'optimizedBytes': output_size,
                      'provenance': provenance})
    if sum(spec['optimizedBytes'] for spec in specs) > MAX_OUTPUT_BYTES:
        raise MediaPreparationError('Reviewed media output size exceeds the restoration limit')
    return specs


def verify_bytes(data, expected_hash, expected_size, label):
    if len(data) != expected_size or sha256(data) != expected_hash:
        raise MediaPreparationError(f'Pinned size/SHA-256 mismatch: {label}')


def verify_existing(web_root, specs, require_outputs=False):
    missing, checked = [], set()
    for spec in specs:
        for path_key, hash_key, size_key in (
                ('sourcePath', 'originalSha256', 'originalBytes'),
                ('outputPath', 'sha256', 'optimizedBytes')):
            name = spec[path_key]
            path = image_path(web_root, name)
            if path.exists():
                if not path.is_file() or path.stat().st_size != spec[size_key]:
                    raise MediaPreparationError(f'Existing image has changed; refusing to replace it: {name}')
                if (name, spec[hash_key]) not in checked:
                    verify_bytes(path.read_bytes(), spec[hash_key], spec[size_key], name)
                    checked.add((name, spec[hash_key]))
            elif path_key == 'outputPath':
                missing.append(spec)
    if require_outputs and missing:
        paths = ', '.join(spec['outputPath'] for spec in missing)
        raise MediaPreparationError(
            f'Missing reviewed image outputs: {paths}. '
            'Use --download-sources or --from-pack PATH to restore the pinned images.')
    return missing


def atomic_create(destination, data, expected_hash, expected_size):
    """Publish a fully checked file atomically without replacing an existing file."""
    verify_bytes(data, expected_hash, expected_size, destination.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.media-prepare-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # An atomic hard link fails if another process created this path;
            # os.replace would silently overwrite that file.
            os.link(temporary, destination)
            return True
        except FileExistsError:
            if destination.is_symlink() or not destination.is_file():
                raise MediaPreparationError(f'Refusing to replace an existing path: {destination.name}')
            verify_bytes(destination.read_bytes(), expected_hash, expected_size, destination.name)
            return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def retry_after_seconds(headers):
    """Read a server's minimum wait, accepting delta-seconds or an HTTP date."""
    value = (headers or {}).get('Retry-After', '').strip()
    if re.fullmatch(r'[0-9]+', value):
        # An enormous valid integer still means "do not retry soon". Avoid
        # treating an integer-conversion limit as a missing Retry-After header.
        return int(value) if len(value) <= 9 else float('inf')
    if value:
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            return max(0.0, target.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            pass
    return None


def retry_delay(error, retry_index, waited_seconds):
    remaining = MAX_RETRY_WAIT_SECONDS - waited_seconds
    delay = max(15 * (2 ** retry_index), retry_after_seconds(error.headers) or 0)
    if delay > remaining:
        raise MediaPreparationError(
            f'HTTP {error.code}: the host requested a wait beyond the remaining '
            f'{remaining:g}-second retry budget. Retry later after the server wait '
            'or restore the reviewed ZIP with --from-pack; no early request was sent.')
    # Jitter only adds time and never shortens the server's requested wait.
    return delay + min(random.uniform(0, 5), remaining - delay)


def wait_for_retry(seconds):
    while seconds > 0:
        interval = min(seconds, 60)
        time.sleep(interval)
        seconds -= interval


def download_source(spec):
    if spec['sourcePath'] not in DOWNLOAD_PATHS:
        raise MediaPreparationError('Only the six reviewed public originals may be downloaded')
    url = spec['provenance'].get('originalImageUrl', '')
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname not in DOWNLOAD_HOSTS
            or parts.username or parts.password or parts.port not in {None, 443}
            or parts.fragment or parts.query
            or PurePosixPath(parts.path).suffix.lower() not in {'.png', '.jpg', '.jpeg'}):
        raise MediaPreparationError(f'Unreviewed public-image URL for {spec["sourcePath"]}')
    request = Request(url, headers={'User-Agent': USER_AGENT,
                                    'Accept': 'image/png,image/jpeg', 'Accept-Encoding': 'identity'})
    opener = build_opener(NoRedirects())
    waited_seconds = 0
    for attempt in range(MAX_DOWNLOAD_ATTEMPTS):
        try:
            with opener.open(request, timeout=45) as response:
                if response.status != 200 or response.geturl() != url:
                    raise MediaPreparationError('Public image request did not return the exact reviewed URL')
                length = response.headers.get('Content-Length')
                if length is not None and int(length) != spec['originalBytes']:
                    raise MediaPreparationError(f'Public image length differs from its pin: {spec["sourcePath"]}')
                data = response.read(spec['originalBytes'] + 1)
            verify_bytes(data, spec['originalSha256'], spec['originalBytes'], spec['sourcePath'])
            return data
        except HTTPError as exc:
            exc.close()
            if exc.code not in TRANSIENT_HTTP_STATUSES or exc.geturl() != url:
                raise MediaPreparationError(
                    f'Cannot fetch reviewed public image {spec["sourcePath"]}: {exc}') from exc
            if attempt + 1 == MAX_DOWNLOAD_ATTEMPTS:
                raise MediaPreparationError(
                    f'HTTP {exc.code} fetching {spec["sourcePath"]} after '
                    f'{MAX_DOWNLOAD_ATTEMPTS} attempts. Retry later or restore '
                    'the reviewed ZIP with --from-pack.') from exc
            delay = retry_delay(exc, attempt, waited_seconds)
            print(f'HTTP {exc.code} for {spec["sourcePath"]}; waiting {delay:g}s '
                  f'before attempt {attempt + 2}/{MAX_DOWNLOAD_ATTEMPTS}.', file=sys.stderr)
            wait_for_retry(delay)
            waited_seconds += delay
        except (OSError, ValueError) as exc:
            if isinstance(exc, MediaPreparationError):
                raise
            raise MediaPreparationError(f'Cannot fetch reviewed public image {spec["sourcePath"]}: {exc}') from exc


def require_encoder():
    try:
        import PIL
        from PIL import features
    except ImportError as exc:
        raise MediaPreparationError(f'Reproduction requires Pillow=={PILLOW_VERSION}') from exc
    if PIL.__version__ != PILLOW_VERSION or features.version('webp') != WEBP_VERSION:
        raise MediaPreparationError(
            f'Reproduction requires Pillow {PILLOW_VERSION} with libwebp {WEBP_VERSION}; '
            f'found Pillow {PIL.__version__}, libwebp {features.version("webp")}. '
            'Use the pinned wheel environment or --from-pack.')


def restore_from_pack(web_root, specs, pack):
    if not pack.is_file() or pack.stat().st_size > 512 * 1024 * 1024:
        raise MediaPreparationError('Expected a local lesson ZIP no larger than 512 MiB')
    expected = {spec['outputPath']: spec for spec in specs}
    pending = {}
    try:
        with zipfile.ZipFile(pack) as archive:
            entries = archive.infolist()
            if len(entries) > 3000:
                raise MediaPreparationError('ZIP has too many entries')
            selected = {}
            wanted_case = {name.casefold(): name for name in expected}
            for info in entries:
                canonical = wanted_case.get(info.filename.casefold())
                if canonical is None:
                    continue  # Never read or extract code, JSON, private files or other media.
                if info.filename != canonical or canonical in selected:
                    raise MediaPreparationError('ZIP contains a duplicate or case-aliased expected image')
                selected[canonical] = info
            if set(selected) != set(expected):
                raise MediaPreparationError('ZIP does not contain every exact expected output image path')
            for name, spec in expected.items():
                info = selected[name]
                mode = stat.S_IFMT(info.external_attr >> 16)
                if (info.is_dir() or mode not in {0, stat.S_IFREG} or info.flag_bits & 1
                        or info.file_size != spec['optimizedBytes']):
                    raise MediaPreparationError(f'Unexpected ZIP image type or pinned size: {name}')
                with archive.open(info) as stream:
                    data = stream.read(spec['optimizedBytes'] + 1)
                verify_bytes(data, spec['sha256'], spec['optimizedBytes'], name)
                if not image_path(web_root, name).exists():
                    pending[name] = data
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise MediaPreparationError(f'Cannot verify the image-only ZIP restore: {exc}') from exc
    # Check every chosen member before publishing any of them.
    return sum(atomic_create(image_path(web_root, name), data,
                             expected[name]['sha256'], expected[name]['optimizedBytes'])
               for name, data in pending.items())


def prepare_media(repo=ROOT, *, download_sources=False, from_pack=None):
    if download_sources and from_pack is not None:
        raise MediaPreparationError('Choose either source download or ZIP restore')
    repo = Path(repo).resolve()
    web_root = repo / 'web'
    specs = load_recipe(repo)
    missing = verify_existing(web_root, specs)
    downloaded = reproduced = extracted = 0
    if from_pack is not None:
        extracted = restore_from_pack(web_root, specs, Path(from_pack))
    elif download_sources:
        # A missing tracked original is a checkout problem, never permission to
        # find a new source or substitute a different image.
        absent_tracked = [s['sourcePath'] for s in specs
                          if s['sourcePath'] not in DOWNLOAD_PATHS
                          and not image_path(web_root, s['sourcePath']).exists()]
        if absent_tracked:
            raise MediaPreparationError('Tracked original images are missing: ' + ', '.join(absent_tracked))
        if missing:
            require_encoder()  # Fail before network or writes on an unsupported encoder.
        for spec in specs:
            source = image_path(web_root, spec['sourcePath'])
            if spec['sourcePath'] in DOWNLOAD_PATHS and not source.exists():
                data = download_source(spec)
                downloaded += atomic_create(source, data, spec['originalSha256'], spec['originalBytes'])
        missing = verify_existing(web_root, specs)
        if missing:
            from optimize_media import optimize_image
            with tempfile.TemporaryDirectory(prefix='instaanki-media-reproduction-') as staging:
                pending = []
                for spec in missing:
                    source = image_path(web_root, spec['sourcePath'])
                    result = optimize_image(source, Path(staging), spec['provenance'])
                    data = Path(result['outputPath']).read_bytes()
                    verify_bytes(data, spec['sha256'], spec['optimizedBytes'], spec['outputPath'])
                    pending.append((spec, data))
                for spec, data in pending:
                    reproduced += atomic_create(image_path(web_root, spec['outputPath']), data,
                                                 spec['sha256'], spec['optimizedBytes'])
    verify_existing(web_root, specs, require_outputs=True)
    return {'mode': 'from-pack' if from_pack is not None else ('download-sources' if download_sources else 'verify'),
            'verifiedOutputImages': len(specs),
            'verifiedOutputBytes': sum(s['optimizedBytes'] for s in specs),
            'downloadedOriginals': downloaded, 'reproducedOutputs': reproduced,
            'restoredOutputs': extracted, 'existingFilesReplaced': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--download-sources', action='store_true',
                       help='Fetch only missing reviewed originals, then reproduce exact lossless output hashes.')
    modes.add_argument('--from-pack', type=Path,
                       help='Restore only exact expected image paths and hashes from the v3 lesson ZIP.')
    args = parser.parse_args(argv)
    try:
        summary = prepare_media(download_sources=args.download_sources, from_pack=args.from_pack)
    except MediaPreparationError as exc:
        parser.exit(1, f'Media preparation failed: {exc}\n')
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
