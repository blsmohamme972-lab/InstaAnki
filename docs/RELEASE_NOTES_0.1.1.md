# InstaAnki 0.1.1 — Personal preview update

Prepared on 7 November 2026. Package `com.instaanki.app`, version code `2`, minimum Android 8.0/API 26, target API 35.

This update improves visual guidance, adds saved daily topic choices, and makes the video → question → result sequence explicit. It updates the **three existing lessons from source questions 5, 54 and 182**. Publication production remains **3/200 lessons (1.5%)**; the remaining 197 source questions have not been produced as lessons.

## Precise visual guidance synchronized with narration

The three lessons now use **55 measured narration phrases and 16 named visual targets**. The hand-arrow tip points to a calibrated feature in the original image. The spotlight and camera use the same image transform, so they remain attached during camera movement and changes in screen size. Grouped objects can use a separate spotlight center: the four-lock cue points at an actual lock while highlighting all four.

The final MP3 is the shared clock for narration, phrase captions, camera movement and targeting. Pause keeps the target visible; forward and backward seeks resolve the correct phrase; playback-rate changes preserve synchronization. Reduced motion stops the camera while retaining instructional guidance. Clinical images keep their full framing, and their nine-second endings hold a calibrated static target before the question.

Phrase timing comes from the sample boundaries of separately synthesized phrases. This is **phrase-level alignment, not forced word-level alignment**. Audio, image and authoring-plan hashes reject stale timing or targets after media changes. Unannotated legacy content and phrases without a justified visible target have no invented pointer. See [visual production rules](visual-production-rules.md) for the coordinate schema and regeneration procedure.

## Saved daily lesson topics

**Settings → Spaced recall → Daily lesson topics**, directly below **New lessons each day**, now offers **All**, individual specialties, parent topics, subtags and multiple selections.

- Parent topics include their descendants. Multiple selections form a union without duplicate lessons.
- Search includes canonical labels, aliases and parent context. The selector shows available lesson counts.
- The choice persists on the device and is included in the learning backup. Canceling the editor preserves the saved choice; All removes the topic constraint.
- Topic filtering happens before the daily new-lesson limit, so unrelated lessons do not consume the selected feed's available positions.
- Due and Saved remain accessible outside the daily topic choice. Selecting topics does not alter recall history or review scheduling.

Shared taxonomy eligibility does not automatically assign a lesson to another specialty. A vascular lesson with a shared physiology tag remains vascular unless it has an explicit additional specialty assignment. An empty selected topic shows an explanatory empty state.

## Clear video, question and result flow

The player identifies the current learning step and the action that comes next. A first viewing reaches the real-image ending before its question; automatic enrollment during the video no longer interrupts an unfinished lesson. Due reviews continue to ask the question before showing the explanation.

Closing an unfinished question preserves the selected option and attempt. Returning through Play resumes that question. Answer feedback states the correct answer in text and keeps the next-lesson and replay controls visible on the tested phone layouts. A single-lesson selection ends with clear choices.

Replaying an answered lesson returns to its existing result without recording a second grade. Explicit practice stays practice after watching the explanation. Incorrect answers and “I don't know” continue to schedule Again where the attempt is a scheduled review; practice does not move the review date.

## Package evidence

| Item | Verified value |
| --- | --- |
| Personal APK | `InstaAnki-0.1.1.apk` |
| Package / version code | `com.instaanki.app` / `2` |
| Size | 14,555,734 bytes, approximately 14.56 MB decimal |
| SHA-256 | `1b0c1011b9f71973f8c87eb32fe8febd91b8fa4dc16559e80b23e05fa718c59b` |
| APK signatures | v2 and v3 verified |
| ZIP alignment | Passed |
| Signing certificate | Matches the delivered 0.1.0 personal build |
| Checked bundled assets | Match the frozen source; lesson audio/image bindings also verified |
| Learning storage identity | Existing namespace and database retained |

The checksum identifies this personal build, which includes the private book cover. Other builds can have different bytes and checksums. The certificate fingerprint, asset hashes and test details are recorded in [verification-0.1.1.json](verification-0.1.1.json).

## Verification performed

| Check group | Result |
| --- | --- |
| JavaScript unit tests | 22 passed |
| Python guidance-pipeline tests | 8 passed |
| Browser smoke checks | 15 passed |
| Guidance browser checks | 11 passed, including 191 independently measured DOM positions |
| Daily-topic browser checks | 9 passed |
| Lesson-flow browser checks | 9 passed, with real audio playback |
| Existing native JVM baseline | 44 assertions passed: 24 importer, 13 download validation and 7 backup assertions; the tested native sources are unchanged |

Guidance checks exercised 360 × 640, 390 × 844 and 430 × 932 layouts, as well as seeking, pause, playback speed, reduced motion, resizing and delayed image loading. Measured arrow endpoints and spotlight centers stayed within the one-CSS-pixel acceptance tolerance against the authored image coordinates. This verifies rendering geometry, not independent medical accuracy.

**`physicalAndroidTested: false` and `humanListeningReviewed: false`.** Browser playback, technical audio validation, JVM assertions and APK signature checks do not establish physical-device installation, native document-picker behavior or human listening quality. An actual on-device update from 0.1.0 has not been verified.

## Distribution and continuity

This is a **privately distributed personal APK**. These notes do not announce a public APK release or a tested public download/install path. Interface changes require the new signed APK; data-only lesson packages do not replace the player implementation.

The package name, signing certificate, learning-storage namespace and SQLite database identity are retained. Existing lesson IDs are stable, and revised lesson metadata uses version `2`. The public production ledger continues to distinguish produced lessons from the user's learning progress.

See [the main README](../README.md), [native build documentation](../android/README.md), [visual production rules](visual-production-rules.md) and [production workflow](production-workflow.md) for continuation instructions.
