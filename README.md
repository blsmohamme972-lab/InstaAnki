# InstaAnki

An English-only personal Android app that combines a short-form medical lesson feed with automatic spaced review. **Version 0.1.1 is a personal preview with three narrated lessons, precise visual guidance and saved daily-topic choices.** It has not yet been installed or tested on a physical Android device or emulator.

## What works in this version

- Offline playback of bundled English narration and original 2D visual mnemonics, with a hand/arrow tip anchored to the exact explained feature, bounded camera motion, a focused spotlight, phrase captions, and attributed clinical images.
- All three lessons use 55 independently synthesized narration phrases with measured sample boundaries. Camera, pointer, spotlight and captions share the audio clock, including pause, seek and speed changes.
- Saved daily-topic choices: All, a specialty, a subtopic, or multiple tags. Parent tags include descendants, and filtering happens before the daily new-lesson limit. Due reviews and saved lessons remain available independently.
- Playback speeds from 0.75× to 2×, seeking and a vertical swipe feed.
- Automatic enrollment after watching; an MCQ answer, not a like or a replay, determines the FSRS review result. Due reviews start with the question. Early practice preserves the scheduled due date.
- Native SQLite storage for learning history, saved lessons, private notes and preferences; learning backup export and restore.
- Publications with a book cover, individual question status and production progress, separate from the learner's progress.
- Fixed English tags for Cardiac Surgery, Thoracic Surgery and Vascular Surgery, plus detailed canonical topics.
- Data-only ZIP content import, a catalog viewer and an HTTPS content downloader with SHA-256 verification.

The app uses a lightweight Java Android shell with a bundled WebView interface. It does not need a hosted website, account or cloud learning database. Browser development uses browser storage; the Android app uses SQLite.

## Starter collection

The source collection contains 200 extracted questions. **Three source questions have produced lessons: 3/200, or 1.5%.** This is production progress, not completion of the book or a clinical certification.

| Source question | Lesson | Duration |
|---|---|---|
| Q5 | Extralobar Sequestration: Its Own Pleural Coat | 74.5 seconds |
| Q54 | Coronary Dominance: Follow the PDA | 71.2 seconds |
| Q182 | Vascular Resistance: The Fourth-Power Rule | 72.0 seconds |

Each lesson has an original explanation, mnemonic symbols, a stable memory location, MP3 narration, a timed real-image outro, an MCQ and source references. Original book text and private source material are excluded from the public app assets. The personal build includes the book cover.

## Build and verify

Requires Linux x86_64, Python 3.10+, Node.js/npm and Java 17 with `jdk.compiler` and `keytool`.

The complete browser suite includes a personal book-cover check and requires the authorized cover in `private-content/app-assets/`. The app and public code can be built without that private asset.

```bash
npm ci
npm run build:web
npm test
npx playwright install chromium --only-shell
npm run test:browser
npm run test:guidance
npm run test:topics
npm run test:flow
python -m unittest discover -s tests -p 'test_guidance_pipeline.py'
python android/bootstrap_sdk.py
python android/build_apk.py
```

The output is `dist/InstaAnki-0.1.1.apk`. For a personal build with an authorized cover restored to `private-content/app-assets/`, use:

```bash
python android/build_apk.py --include-private
```

Keep the signing identity private and reuse it for updates. See [Android build and native behavior](android/README.md) for build options, import limits and backup behavior.

The [0.1.1 release notes](docs/RELEASE_NOTES_0.1.1.md) and [verification report](docs/verification-0.1.1.json) record this update’s checks. The original [0.1.0 verification](docs/verification-0.1.0.json) remains available as historical evidence. Browser playback, measured target geometry, audio decoding and Android package signing are separate checks; physical Android playback and human listening remain unverified.

## Content updates and current limits

The app can import ZIP lessons and check [the content catalog](content/catalog.json). At verification time, `catalog.packs` is empty and no published GitHub Release download is recorded. The downloader exists, but an end-to-end live Release download has not been verified.

Interface OTA updates and automatic in-app APK installation are **not implemented**. Interface or native-code changes require a new APK signed with the same key, installed through Android. Content-only packs preserve local learning history. Checksums detect changes relative to the catalog; they do not authenticate a publisher.

## Continuing production

```bash
python tools/production.py status
python tools/production.py next --count 10
```

The [production ledger](production/books/shahzad-raja-2015-200-practice-questions.json) records each question separately, so completing Q182 does not skip earlier questions. Follow the [production workflow](docs/production-workflow.md), [visual rules](docs/visual-production-rules.md) and [tagging policy](taxonomy/README.md). New lessons require source, visual, audio-decode and timeline checks before marking them produced; device and human-listening checks are recorded separately.

Verified extracted source data is preserved in the privately delivered `InstaAnki-Source-Archive.zip`, outside GitHub. Raw source extracts, encrypted vault files and vault metadata are excluded from Git. Restore the private archive into the project before producing later batches; see [source recovery](source-vault/README.md). Signing keys and optional vault keys remain separate and private. The original uploaded PDF is not retained in the repository, archive or application.

If the archive is unavailable, `tools/extract_raja_source.py` can rebuild the private extraction from the original 190-page Raja PDF. `tools/source_archive.py` verifies, exports and restores ordinary source ZIPs with explicit book-identity checks. Check current private files and attachments before requesting another upload; a different book's question numbers cannot replace the tracked source.
