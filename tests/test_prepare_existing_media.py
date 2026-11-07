"""Integrity and file-scope tests for code-only restoration of reviewed media."""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import format_datetime
import io
import json
from pathlib import Path
import random
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError
import warnings
import zipfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_existing_media as prepare
from optimize_media import optimize_image


class ExistingMediaPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Tiny, independently generated test images keep these tests fast. They
        # use the same twelve path roles but never download clinical images.
        cls.fixture_dir = tempfile.TemporaryDirectory()
        cls.template = Path(cls.fixture_dir.name)
        web = cls.template / 'web'
        real_manifest = json.loads((ROOT / 'production/starter-media-originals.json').read_text())
        urls = {a['path']: a['provenance'].get('originalImageUrl') for a in real_manifest['assets']}
        assets, results = [], []
        for index, name in enumerate(sorted(prepare.SOURCE_PATHS)):
            path = web / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == '.jpg':
                image = Image.frombytes('RGB', (64, 48), random.Random(index).randbytes(64 * 48 * 3))
                image.save(path, quality=80)
            else:
                Image.new('RGB', (64, 48), (index * 17, index * 11, index * 7)).save(path, compress_level=0)
            q = 54 if 'coronary' in name or 'q054' in name else (5 if 'sequestration' in name or 'q005' in name else 182)
            provenance = {'lessonId': f'shahzad2015-q{q:03}',
                          'sha256': prepare.sha256(path.read_bytes()),
                          'license': 'test-only generated fixture'}
            if name in prepare.DOWNLOAD_PATHS:
                provenance['originalImageUrl'] = urls[name]
            assets.append({'path': name, 'provenance': provenance})
            result = optimize_image(path, web / 'media/optimized', provenance)
            for key in ('sourcePath', 'outputPath'):
                result[key] = str(Path(result[key]).relative_to(web))
            results.append(result)
        (cls.template / 'production/qa').mkdir(parents=True)
        (cls.template / 'production/starter-media-originals.json').write_text(json.dumps({'assets': assets}))
        (cls.template / 'production/qa/starter-media-optimization.json').write_text(json.dumps({'assets': results}))
        cls.results = results

    @classmethod
    def tearDownClass(cls):
        cls.fixture_dir.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / 'repo'
        shutil.copytree(self.template, self.repo)
        self.web = self.repo / 'web'

    def tearDown(self):
        self.temp.cleanup()

    def remove_untracked_media(self):
        for asset in self.results:
            if asset['imageBytesModified']:
                (self.web / asset['outputPath']).unlink()
        for name in prepare.DOWNLOAD_PATHS:
            (self.web / name).unlink()

    def download_fixture(self):
        spec = next(s for s in prepare.load_recipe(self.repo)
                    if s['sourcePath'] == 'media/real/starter-q182-arteriole.jpg')
        return spec, (self.template / 'web' / spec['sourcePath']).read_bytes()

    def response(self, spec, data, *, url=None, length=None):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.geturl.return_value = url or spec['provenance']['originalImageUrl']
        response.headers = {'Content-Length': str(len(data) if length is None else length)}
        response.read.return_value = data
        return response

    def http_error(self, spec, status, retry_after=None, *, url=None):
        headers = {} if retry_after is None else {'Retry-After': retry_after}
        return HTTPError(url or spec['provenance']['originalImageUrl'], status,
                         'mock HTTP error', headers, io.BytesIO(b'mock error body'))

    @contextmanager
    def mock_download_attempts(self, events, *, now=1767225600, jitter=0):
        opener = mock.Mock()
        opener.open.side_effect = events
        with mock.patch.object(prepare, 'build_opener', return_value=opener) as factory, \
                mock.patch.object(prepare.time, 'sleep') as sleep, \
                mock.patch.object(prepare.time, 'time', return_value=now), \
                mock.patch.object(prepare.random, 'uniform', return_value=jitter), \
                mock.patch.object(prepare.sys, 'stderr', io.StringIO()):
            yield opener, sleep, factory

    def pack(self, *, corrupt=None, extra=None, duplicate=None, symlink=None, omit=None):
        pack = Path(self.temp.name) / 'reviewed.zip'
        with zipfile.ZipFile(pack, 'w', zipfile.ZIP_DEFLATED) as archive:
            for asset in self.results:
                name = asset['outputPath']
                if name == omit:
                    continue
                data = (self.template / 'web' / name).read_bytes()
                if name == corrupt:
                    data = bytes([data[0] ^ 1]) + data[1:]
                if name == symlink:
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, data)
                else:
                    archive.writestr(name, data)
            if duplicate:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    archive.writestr(duplicate, b'untrusted duplicate')
            for name, data in (extra or {}).items():
                archive.writestr(name, data)
        return pack

    def test_default_verify_is_read_only(self):
        before = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}
        with mock.patch.object(prepare, 'download_source') as download:
            result = prepare.prepare_media(self.repo)
        after = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(result['verifiedOutputImages'], 12)
        self.assertEqual(result['existingFilesReplaced'], 0)
        download.assert_not_called()

    def test_default_missing_output_fails_without_downloading(self):
        self.remove_untracked_media()
        with mock.patch.object(prepare, 'download_source') as download:
            with self.assertRaisesRegex(prepare.MediaPreparationError, 'Missing reviewed image outputs'):
                prepare.prepare_media(self.repo)
        download.assert_not_called()

    def test_only_six_missing_public_originals_download_then_exact_reproduction(self):
        self.remove_untracked_media()
        fetched = []
        def fetch(spec):
            fetched.append(spec['sourcePath'])
            return (self.template / 'web' / spec['sourcePath']).read_bytes()
        with mock.patch.object(prepare, 'download_source', side_effect=fetch):
            result = prepare.prepare_media(self.repo, download_sources=True)
        self.assertEqual(set(fetched), prepare.DOWNLOAD_PATHS)
        self.assertEqual(len(fetched), 6)
        self.assertEqual(result['downloadedOriginals'], 6)
        for asset in self.results:
            self.assertEqual((self.web / asset['outputPath']).read_bytes(),
                             (self.template / 'web' / asset['outputPath']).read_bytes())

    def test_changed_existing_source_or_output_fails_before_network(self):
        for key in ('sourcePath', 'outputPath'):
            with self.subTest(key=key):
                asset = next(a for a in self.results if a['imageBytesModified'])
                path = self.web / asset[key]
                saved = path.read_bytes()
                changed = bytes([saved[0] ^ 1]) + saved[1:]
                path.write_bytes(changed)
                with mock.patch.object(prepare, 'download_source') as download:
                    with self.assertRaisesRegex(prepare.MediaPreparationError, 'SHA-256 mismatch'):
                        prepare.prepare_media(self.repo, download_sources=True)
                download.assert_not_called()
                self.assertEqual(path.read_bytes(), changed)
                path.write_bytes(saved)

    def test_bad_download_is_not_published(self):
        self.remove_untracked_media()
        with mock.patch.object(prepare, 'download_source', return_value=b'wrong bytes'):
            with self.assertRaisesRegex(prepare.MediaPreparationError, 'size/SHA-256 mismatch'):
                prepare.prepare_media(self.repo, download_sources=True)
        self.assertTrue(all(not (self.web / name).exists() for name in prepare.DOWNLOAD_PATHS))

    def test_missing_tracked_original_is_not_replaced_with_a_download(self):
        self.remove_untracked_media()
        name = sorted(prepare.SOURCE_PATHS - prepare.DOWNLOAD_PATHS)[0]
        (self.web / name).unlink()
        with mock.patch.object(prepare, 'download_source') as download:
            with self.assertRaisesRegex(prepare.MediaPreparationError, 'Tracked original images are missing'):
                prepare.prepare_media(self.repo, download_sources=True)
        download.assert_not_called()

    def test_wrong_encoder_fails_before_download_or_write(self):
        self.remove_untracked_media()
        with mock.patch.object(prepare, 'require_encoder', side_effect=prepare.MediaPreparationError('encoder version mismatch')):
            with mock.patch.object(prepare, 'download_source') as download:
                with self.assertRaisesRegex(prepare.MediaPreparationError, 'encoder version mismatch'):
                    prepare.prepare_media(self.repo, download_sources=True)
        download.assert_not_called()

    def test_pack_restores_only_exact_expected_images_without_encoder_or_network(self):
        self.remove_untracked_media()
        pack = self.pack(extra={'app.js': b'untrusted code', 'lessons.json': b'{}',
                                'private-content/book.pdf': b'private', '../../escape': b'escape'})
        with mock.patch.object(prepare, 'download_source') as download, mock.patch.object(prepare, 'require_encoder') as encoder:
            result = prepare.prepare_media(self.repo, from_pack=pack)
        self.assertGreater(result['restoredOutputs'], 0)
        download.assert_not_called()
        encoder.assert_not_called()
        self.assertFalse((self.repo / 'app.js').exists())
        self.assertFalse((self.web / 'app.js').exists())
        self.assertFalse((self.web / 'lessons.json').exists())
        self.assertFalse((self.repo / 'private-content').exists())
        self.assertFalse((Path(self.temp.name) / 'escape').exists())
        self.assertEqual(prepare.prepare_media(self.repo)['verifiedOutputImages'], 12)

    def test_pack_hash_failure_writes_no_output(self):
        self.remove_untracked_media()
        changed = next(a for a in self.results if a['imageBytesModified'])
        pack = self.pack(corrupt=changed['outputPath'])
        with self.assertRaisesRegex(prepare.MediaPreparationError, 'SHA-256 mismatch'):
            prepare.prepare_media(self.repo, from_pack=pack)
        for asset in self.results:
            if asset['imageBytesModified']:
                self.assertFalse((self.web / asset['outputPath']).exists())

    def test_pack_duplicate_case_alias_and_symlink_are_rejected(self):
        self.remove_untracked_media()
        path = self.results[0]['outputPath']
        for options in ({'duplicate': path}, {'duplicate': path.upper()}, {'symlink': path}):
            with self.subTest(options=options):
                with self.assertRaises(prepare.MediaPreparationError):
                    prepare.prepare_media(self.repo, from_pack=self.pack(**options))

    def test_missing_pack_member_fails(self):
        self.remove_untracked_media()
        with self.assertRaisesRegex(prepare.MediaPreparationError, 'every exact expected output image path'):
            prepare.prepare_media(self.repo, from_pack=self.pack(omit=self.results[0]['outputPath']))

    def test_unsafe_recipe_output_and_destination_symlink_are_rejected(self):
        report_path = self.repo / 'production/qa/starter-media-optimization.json'
        report = json.loads(report_path.read_text())
        original = deepcopy(report)
        report['assets'][0]['outputPath'] = '../escape.png'
        report_path.write_text(json.dumps(report))
        with self.assertRaisesRegex(prepare.MediaPreparationError, 'Unsafe or non-image'):
            prepare.prepare_media(self.repo)
        report_path.write_text(json.dumps(original))
        asset = next(a for a in self.results if a['imageBytesModified'])
        target = self.web / asset['outputPath']
        target.unlink()
        target.symlink_to(self.web / asset['sourcePath'])
        with self.assertRaisesRegex(prepare.MediaPreparationError, 'Symlink'):
            prepare.prepare_media(self.repo)

    def test_unreviewed_download_host_is_rejected_without_a_request(self):
        spec = next(s for s in prepare.load_recipe(self.repo) if s['sourcePath'] in prepare.DOWNLOAD_PATHS)
        spec['provenance']['originalImageUrl'] = 'https://example.invalid/book.pdf'
        with mock.patch.object(prepare, 'build_opener') as opener:
            with self.assertRaisesRegex(prepare.MediaPreparationError, 'Unreviewed public-image URL'):
                prepare.download_source(spec)
        opener.assert_not_called()

    def test_atomic_create_never_replaces_changed_existing_bytes(self):
        destination = self.repo / 'already-present.png'
        destination.write_bytes(b'keep this')
        with self.assertRaisesRegex(prepare.MediaPreparationError, 'SHA-256 mismatch'):
            prepare.atomic_create(destination, b'new', prepare.sha256(b'new'), 3)
        self.assertEqual(destination.read_bytes(), b'keep this')
        self.assertFalse(list(destination.parent.glob('.media-prepare-*')))

    def test_http_429_retries_after_server_delay_and_keeps_identity(self):
        spec, data = self.download_fixture()
        error = self.http_error(spec, 429, '30')
        response = self.response(spec, data)
        with self.mock_download_attempts([error, response], jitter=2) as (opener, sleep, factory):
            self.assertEqual(prepare.download_source(spec), data)
        self.assertEqual(opener.open.call_count, 2)
        sleep.assert_called_once_with(32)
        self.assertTrue(error.fp.closed)
        for call in opener.open.call_args_list:
            request = call.args[0]
            self.assertEqual(request.full_url, spec['provenance']['originalImageUrl'])
            self.assertEqual(request.get_header('User-agent'),
                             'InstaAnki-reviewed-media-restore/0.2 '
                             '(https://github.com/blsmohamme972-lab/InstaAnki)')
            self.assertEqual(request.get_header('Accept-encoding'), 'identity')
            self.assertEqual(call.kwargs, {'timeout': 45})
        response.read.assert_called_once_with(spec['originalBytes'] + 1)
        handler = factory.call_args.args[0]
        self.assertIsInstance(handler, prepare.NoRedirects)
        self.assertIsNone(handler.redirect_request(None, None, 302, None, None, 'https://example.invalid/'))

    def test_http_date_retry_after_is_honored(self):
        spec, data = self.download_fixture()
        now = 1767225600
        header = format_datetime(datetime.fromtimestamp(now + 45, timezone.utc), usegmt=True)
        with self.mock_download_attempts([self.http_error(spec, 503, header), self.response(spec, data)],
                                        now=now) as (opener, sleep, _):
            self.assertEqual(prepare.download_source(spec), data)
        sleep.assert_called_once_with(45)
        self.assertEqual(opener.open.call_count, 2)

    def test_transient_http_exhaustion_is_bounded(self):
        spec, _ = self.download_fixture()
        for status in (408, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                errors = [self.http_error(spec, status) for _ in range(4)]
                with self.mock_download_attempts(errors) as (opener, sleep, _):
                    with self.assertRaisesRegex(prepare.MediaPreparationError, 'after 4 attempts'):
                        prepare.download_source(spec)
                self.assertEqual(opener.open.call_count, 4)
                self.assertEqual(sleep.call_args_list, [mock.call(15), mock.call(30), mock.call(60)])

    def test_retry_after_over_budget_stops_without_early_request(self):
        spec, _ = self.download_fixture()
        now = 1767225600
        future = format_datetime(datetime.fromtimestamp(now + 600, timezone.utc), usegmt=True)
        for header in ('600', future, '999999999999999999999999999999'):
            with self.subTest(header=header):
                with self.mock_download_attempts([self.http_error(spec, 429, header)],
                                                now=now) as (opener, sleep, _):
                    with self.assertRaisesRegex(prepare.MediaPreparationError, 'no early request was sent'):
                        prepare.download_source(spec)
                self.assertEqual(opener.open.call_count, 1)
                sleep.assert_not_called()

    def test_retry_wait_budget_is_cumulative(self):
        spec, data = self.download_fixture()
        events = [self.http_error(spec, 429, '100'), self.http_error(spec, 429, '100'),
                  self.response(spec, data)]
        with self.mock_download_attempts(events) as (opener, sleep, _):
            with self.assertRaisesRegex(prepare.MediaPreparationError, 'remaining 80-second retry budget'):
                prepare.download_source(spec)
        self.assertEqual(opener.open.call_count, 2)
        self.assertEqual(sleep.call_args_list, [mock.call(60), mock.call(40)])

    def test_invalid_or_past_retry_after_uses_polite_backoff(self):
        spec, data = self.download_fixture()
        past = format_datetime(datetime.fromtimestamp(1767225500, timezone.utc), usegmt=True)
        for header in ('not a date', '-3', '0', past):
            with self.subTest(header=header):
                with self.mock_download_attempts([self.http_error(spec, 503, header),
                                                 self.response(spec, data)]) as (opener, sleep, _):
                    self.assertEqual(prepare.download_source(spec), data)
                self.assertEqual(opener.open.call_count, 2)
                sleep.assert_called_once_with(15)

    def test_permanent_http_and_redirect_errors_never_retry(self):
        spec, _ = self.download_fixture()
        for status, url in ((404, None), (403, None), (301, None), (302, None),
                            (429, 'https://example.invalid/other-image.jpg')):
            with self.subTest(status=status, url=url):
                with self.mock_download_attempts([self.http_error(spec, status, '30', url=url)]) as (opener, sleep, _):
                    with self.assertRaises(prepare.MediaPreparationError):
                        prepare.download_source(spec)
                self.assertEqual(opener.open.call_count, 1)
                sleep.assert_not_called()

    def test_integrity_failures_after_retry_never_retry_again(self):
        spec, data = self.download_fixture()
        altered = bytes([data[0] ^ 1]) + data[1:]
        for kind in ('declared length', 'actual length', 'hash'):
            with self.subTest(kind=kind):
                if kind == 'declared length':
                    invalid = self.response(spec, data, length=len(data) + 1)
                elif kind == 'actual length':
                    invalid = self.response(spec, data + b'extra', length=len(data))
                else:
                    invalid = self.response(spec, altered)
                with self.mock_download_attempts([self.http_error(spec, 429), invalid,
                                                 self.response(spec, data)]) as (opener, sleep, _):
                    with self.assertRaises(prepare.MediaPreparationError):
                        prepare.download_source(spec)
                self.assertEqual(opener.open.call_count, 2)
                sleep.assert_called_once_with(15)

    def test_redirected_success_after_retry_is_rejected(self):
        spec, data = self.download_fixture()
        redirected = self.response(spec, data, url='https://example.invalid/other-image.jpg')
        with self.mock_download_attempts([self.http_error(spec, 503), redirected]) as (opener, sleep, _):
            with self.assertRaisesRegex(prepare.MediaPreparationError, 'exact reviewed URL'):
                prepare.download_source(spec)
        self.assertEqual(opener.open.call_count, 2)
        sleep.assert_called_once_with(15)


if __name__ == '__main__':
    unittest.main()
