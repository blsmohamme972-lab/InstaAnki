# InstaAnki

An English-only personal Android app that combines a short-form medical lesson feed with automatic spaced review. **InstaAnki Fresh 0.3.0 starts with zero installed lessons and includes the repaired app. New lesson production is paused.** The original Raja book remains the only approved publication. Physical Android installation and playback must be checked separately from automated verification.

## Fresh installation — current user request

The user explicitly requested a fresh start without the old videos. **InstaAnki Fresh** uses application ID `com.instaanki.fresh` and installs separately from the original `com.instaanki.app`. It does not need an old APK, old lesson media or a learning-data migration. It includes no lesson audio, video or images. The UI distinguishes **0 lessons on this device** from the truthful **3/200 historically produced** source questions.

```bash
npm ci
npm run build:web:fresh
npx playwright install --with-deps chromium --only-shell
npm run test:fresh
python android/bootstrap_sdk.py
npm run build:apk:fresh -- --unsigned
```

The sequence above checks a clean checkout and creates an **unsigned compilation artifact**, not an installable app. The signed 0.3.0 release was built separately with the restored Fresh signing backup. For the next installable update, use the existing private backup and a higher version code:

```bash
npm run build:apk:fresh -- --key-dir /private/fresh-signing-backup --version-code 5 --version-name 0.3.1
```

The backup contains `instaanki-fresh-release.p12` and `keystore-password.txt`. The public certificate is pinned in `android/signing-identity-fresh.json`; never generate a different key for a future update. Version code 4 is recorded as delivered, so signing another update with code 4 is rejected. See [fresh installation and future updates](docs/FRESH_INSTALL_0.3.0.md) for the release verification and application-specific catalog rules.

The lower-level builder deliberately retains the legacy profile as its default, protecting existing installations. Select `--profile fresh` explicitly or use the dedicated npm command above. A missing legacy signing key does not block the separately authorized Fresh app.

## Player and learning capabilities

Fresh starts empty. These player capabilities become available after the user deliberately imports a valid original-book lesson package. The historical three-lesson collection remains a legacy QA fixture.

- Offline playback of installed English narration and original 2D visual mnemonics, with a hand/arrow tip anchored to the exact explained feature, bounded camera motion, a focused spotlight, phrase captions, and attributed clinical images.
- Camera, pointer, spotlight and captions share the audio clock, including pause, seek and speed changes. The historical QA lessons use 55 independently synthesized phrases with measured sample boundaries.
- Saved daily-topic choices: All, a specialty, a subtopic, or multiple tags. Parent tags include descendants, and filtering happens before the daily new-lesson limit. Due reviews and saved lessons remain available independently.
- Playback speeds from 0.75× to 2×, seeking and a vertical swipe feed.
- Automatic enrollment after watching; an MCQ answer, not a like or a replay, determines the FSRS review result. Due reviews start with the question. Early practice preserves the scheduled due date.
- Native SQLite storage for learning history, saved lessons, private notes and preferences; learning backup export and restore.
- Publications with individual question status and historical production progress, separate from installed lessons and the learner's progress. Fresh uses a text cover without a bundled cover image.
- Fixed English tags for Cardiac Surgery, Thoracic Surgery and Vascular Surgery, plus detailed canonical topics.
- Data-only ZIP content import, a catalog viewer and an HTTPS content downloader with SHA-256 verification.

The app uses a lightweight Java Android shell with a bundled WebView interface. It does not need a hosted website, account or cloud learning database. Browser development uses browser storage; the Android app uses SQLite.

## Historical starter collection and legacy QA

The source collection contains 200 extracted questions. **Three source questions have produced lessons: 3/200, or 1.5%.** This is production progress, not completion of the book or a clinical certification. These records and assets are retained for legacy builds and regression checks; the Fresh distribution does not ship them.

| Source question | Lesson | Duration |
|---|---|---|
| Q5 | Extralobar Sequestration: Its Own Pleural Coat | 65.2 seconds |
| Q54 | Coronary Dominance: Follow the PDA | 61.8 seconds |
| Q182 | Vascular Resistance: The Fourth-Power Rule | 62.6 seconds |

Each lesson has an original explanation, mnemonic symbols, a stable memory location, MP3 narration, a narrated three-image clinical gallery and synchronized recap, an MCQ and source references. Original book text and private source material are excluded from the public app assets. The personal build includes the book cover.

## Build and verify the legacy collection

Requires Linux x86_64, Python 3.11+, Node.js/npm and Java 17 with `jdk.compiler` and `keytool`.

The complete browser suite includes a personal book-cover check and requires the authorized cover in `private-content/app-assets/`. The app and public code can be built without that private asset.

```bash
npm ci
python -m pip install Pillow==13.0.0
python tools/prepare_existing_media.py --download-sources
npm run build:web
npm test
npx playwright install chromium --only-shell
npm run test:browser
npm run test:guidance
npm run test:topics
npm run test:flow
node tests/reels-browser.cjs
python -m unittest discover -s tests -p 'test_guidance_pipeline.py'
python android/bootstrap_sdk.py
python android/build_apk.py
```

The output is `dist/InstaAnki-0.2.0.apk`. For a personal build with an authorized cover restored to `private-content/app-assets/`, use:

```bash
python android/build_apk.py --include-private
```

Keep the signing identity private and reuse it for updates. See [Android build and native behavior](android/README.md) for build options, import limits and backup behavior.

The [0.2.0 repair notes](docs/APP_REPAIRS_0.2.0.md) describe the current changes and installation gates. Missing original signing material blocks an installable update; `--unsigned` only checks compilation.

The [0.1.1 release notes](docs/RELEASE_NOTES_0.1.1.md) and [verification report](docs/verification-0.1.1.json) record this update’s checks. The original [0.1.0 verification](docs/verification-0.1.0.json) remains available as historical evidence. Browser playback, measured target geometry, audio decoding and Android package signing are separate checks; physical Android playback and human listening remain unverified.

## Content updates and current limits

The repaired app checks [catalog-v2.json](content/catalog-v2.json), which requires explicit minimum app versions for downloadable packages. The existing three-lesson presentation update requires app 0.2.0 (version code 3). Its ending, clinical gallery and recap need the repaired player; a ZIP cannot install that player code. The older app continues reading the separate [legacy catalog](content/catalog.json), whose lesson list stays empty because it cannot enforce a minimum app version.

Both catalogs currently contain no download offers, and no published GitHub Release download is recorded. The reviewed temporary-delivery workflow is merged. Publishing a reviewed data-only release and verifying its live download remain separate operations. A release referenced by either live catalog must not be deleted.

Fresh shares the live v2 catalog but accepts automatic offers only for its own identity: a lesson package needs `targetPackageNames: ["com.instaanki.fresh"]`, and an APK notice needs `packageName: "com.instaanki.fresh"`. Legacy and unscoped offers are excluded. Explicitly choosing a source-valid local ZIP remains available.

Interface OTA updates and automatic in-app APK installation are **not implemented**. Interface or native-code changes require a new APK signed with the same key, installed through Android. Content-only packs preserve local learning history. Checksums detect changes relative to the catalog; they do not authenticate a publisher.

## Production is paused

```bash
python tools/production.py status
python tools/production.py next --count 10
```

These commands are read-only. Claims, narration and new-lesson production fail while `newProductionEnabled` is false. Resuming requires a new explicit user instruction.

The [production ledger](production/books/shahzad-raja-2015-200-practice-questions.json) records each question separately, so completing Q182 does not skip earlier questions. Follow the [production workflow](docs/production-workflow.md), [visual rules](docs/visual-production-rules.md) and [tagging policy](taxonomy/README.md). New lessons require source, visual, audio-decode and timeline checks before marking them produced; device and human-listening checks are recorded separately.

Verified extracted source data is preserved in the privately delivered `InstaAnki-Source-Archive.zip`, outside GitHub. Raw source extracts, encrypted vault files and vault metadata are excluded from Git. Restore the private archive into the project before producing later batches; see [source recovery](source-vault/README.md). Signing keys and optional vault keys remain separate and private. The original uploaded PDF is not retained in the repository, archive or application.

## Original-book source checks

The active publication is the 2015 Raja book already recorded in the production ledger. Run `npm run source:check` to validate the catalog. Production, narration, assembly, packaging, and the actual web/Android builders now check the same source policy. New work requires readable source evidence and a reviewed authored-content fingerprint; exact published starter lessons can be repackaged from their existing public verification records. See [source scope](docs/SOURCE_SCOPE.md) and [production workflow](docs/production-workflow.md).
