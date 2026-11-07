# Reproduce the existing lesson images

The presentation update keeps the three original Raja lessons, narration and
questions. New binary images are not committed to Git. The repository contains
the reviewed image recipes, source/license records and exact byte hashes instead.
CI and release builds prepare these images before checking the source policy or
bundling the app.

## Verify a prepared checkout

```sh
python3 tools/prepare_existing_media.py
```

The default command is read-only. It verifies all twelve runtime images against
the paths, byte lengths and SHA-256 hashes in
`production/qa/starter-media-optimization.json`. Any original image already
present is also checked. A changed existing file causes an error; the tool never
replaces it. Missing runtime files require one of the restoration modes below.

## Restore from reviewed public sources

```sh
python3 -m pip install 'Pillow==13.0.0'
python3 tools/prepare_existing_media.py --download-sources
```

The six original starter images are already tracked in Git. This mode downloads
only missing members of the six additional clinical images listed in
`production/starter-media-originals.json`, using their exact
`provenance.originalImageUrl`. The sources are the publisher's public image
server and Wikimedia Commons. Their original licenses and attribution remain in
the source inventory and lesson metadata.

Every response must match the pinned original byte length and SHA-256 before an
atomic new-file write. Redirects and other hosts are rejected. Existing files
are checked before downloads begin. A missing tracked original is reported as a
checkout error; the tool does not search for substitutes.

Temporary HTTP 408, 429, 500, 502, 503 and 504 responses allow at most four
attempts, with 15/30/60-second backoff and up to five additional seconds of
jitter. `Retry-After` seconds or HTTP dates are honored as a minimum wait. Total
retry waiting is limited to 180 seconds per image; a longer server wait stops
with instructions to retry later or use the reviewed ZIP, without sending an
early request. Missing/forbidden files, redirects and integrity failures are
never retried. The stable User-Agent identifies this tool and the public project
URL, following the [Wikimedia User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy).

Reproduction requires **Pillow 13.0.0 with libwebp 1.6.0**. The command checks both
versions and runs the same lossless encoder used for the reviewed images. Each
saved result must match the expected output hash and length exactly. It also
passes the optimizer's decoded pixel, alpha, dimensions, ICC profile and
orientation checks. There is no resize or lossy fallback. Three JPEG originals
remain unchanged because the reviewed lossless candidates were larger.

Encoder output is staged outside the checkout until every missing result has
passed its exact hash check. A different encoder version or result fails with an
error rather than changing the review pins. Generated files stay in the local
workspace and enter the app or temporary lesson ZIP, not Git history.

## Restore from the reviewed lesson ZIP

```sh
python3 tools/prepare_existing_media.py --from-pack /path/to/instaanki-v3.zip
```

This route does not require Pillow or network access. It reads only the twelve
expected image members, verifies their pinned lengths and hashes, and creates
missing files atomically. It never extracts code, JSON, book text, private files
or unlisted media. Duplicate/case-aliased image entries, symlinks, changed bytes
and unexpected sizes are rejected. The command checks all selected members
before writing any of them.

The ZIP route restores runtime images. It does not restore the four original
publisher PNGs retained only for reproducing lossless encodings. Use the source
download mode if you need those originals for the full pixel comparison tests.

## Verification

```sh
python3 -m unittest discover -s tests -p 'test_prepare_existing_media.py' -v
python3 -m unittest discover -s tests -p 'test_optimize_media.py' -v
python3 -m unittest discover -s tests -p 'test_starter_presentation.py' -v
python3 tools/check_source_scope.py
```

The reviewed twelve-image set is **13,337,179 bytes before lossless optimization
and 9,983,024 bytes afterward**, saving 3,354,155 bytes (25.149%). This comparison
uses the same twelve images. The audio bitstreams and teaching content are
unchanged. `production/qa/starter-media-optimization.json` records the individual
hashes, sizes and quality checks; `production/starter-gallery-sources.json`
records the additional clinical image sources and licenses.
