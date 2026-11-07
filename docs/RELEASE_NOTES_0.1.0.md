# InstaAnki 0.1.0 — Personal preview

Prepared on 7 November 2026. Package `com.instaanki.app`, version code `1`, minimum Android 8.0/API 26, target API 35.

## Delivered implementation

This release is an offline Android APK built from a Java shell, bundled HTML/CSS/JavaScript and local media. The WebView loads intercepted local assets; a native bridge stores learning state in SQLite. There is no required account, hosted frontend or cloud progress service.

The preview includes Feed, Publications, Review, Insights and Settings; playback speeds from 0.75× to 2×; private notes and saved lessons; FSRS scheduling; backup export/restore; and a data-only ZIP importer. Viewing enrolls a lesson automatically, while MCQ results determine recall scheduling. Skipping, liking and replaying are not successful recall events. Due lessons ask the question before the explanation, and early practice does not move the scheduled review.

Three English lessons are bundled from source questions **5, 54 and 182**, with 60–90 second narration, original cartoon mnemonics, synchronized movement, real-image outros and source/license information. The personal APK includes the source book's cover. The publication progress is **3/200 (1.5%)**; the remaining 197 questions have not been produced as lessons.

## Package evidence

| Item | Verified value |
|---|---|
| Personal APK | `InstaAnki-0.1.0.apk` |
| Size | 14,592,455 bytes (14.6 MB decimal) |
| SHA-256 | `6c21cfe3d8418fab2493c247c29936e465d07ac58770f0e227c01410a41340b4` |
| APK signatures | v2 and v3 verified |
| ZIP alignment and integrity | Passed |
| Final bundled web assets | Matched the source files used for verification |
| Original PDF and signing secrets | Absent from APK |

The checksum above identifies the prepared personal build. A fresh build, especially one without private cover assets, can have different bytes and a different checksum.

## Verification performed

- **15 browser checks:** loading, all three MP3s playing without external requests, automatic enrollment, seeking and speed, real-image outros and credits, quiz scheduling, failed-save retry, local notes, publication cover, backup, catalog handling and mobile layouts.
- **8 learning unit tests:** FSRS outcomes, duplicate prevention, practice behavior, backup safety, enrollment limits, retention settings and rollback after failed writes.
- **44 JVM assertions:** 24 content importer, 13 download URL validation and 7 backup parser assertions.
- Visual inspection of the three mnemonic images and three real-image outros; complete technical decoding of all three MP3s; source/question linkage and timeline validation.

These checks do not establish clinical accuracy certification. **Physical Android/emulator execution, human listening review and a separate human medical review have not been completed.** Phone testing remains necessary for native document pickers, actual WebView/audio behavior and installation/update flow. The public [verification JSON](verification-0.1.0.json) records the scope and limits.

## Updates and distribution

The implemented content importer accepts data and media, not executable interface updates. The downloader verifies a complete ZIP's checksum before installation and removes its temporary download. Updating content preserves learning state.

At this checkpoint, the catalog has **zero published downloadable packs** and no confirmed GitHub Release URL. Catalog UI was tested with a controlled response; a live Release download/install was not exercised. Private GitHub download authentication is not implemented; private material can be imported as a local ZIP.

UI OTA, automatic APK installation and background content generation are not implemented. Interface and native changes require a new same-key signed APK with a higher version code. The app can open a future catalog-provided update link for installation through Android.

## Source continuity

The public production ledger preserves per-question progress. The extracted source data, cover and source audit are supplied privately as `InstaAnki-Source-Archive.zip`; raw extracts, encrypted vault files and vault metadata are not added to GitHub. Restore this archive into the project before continuing production. The signing identity and optional encryption keys remain separate and private. The original PDF is excluded. Production completion is not the user's personal learning progress.

See [the main README](../README.md), [native build documentation](../android/README.md) and [production workflow](production-workflow.md) for repeatable build and continuation commands.
