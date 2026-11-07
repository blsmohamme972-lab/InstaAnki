# App repairs 0.2.0

## Scope

This update repairs the application and the three existing Raja lessons: Q5, Q54 and Q182. The original book remains **3/200**. No new lesson, narration recording, mnemonic artwork or rendered video was produced for this update. New lesson production is disabled in the source policy and project instructions.

## Interface and playback

- The mobile feed fills its available screen, with compact overlays, vertical swipes and accessible controls. Android uses immersive system bars on the feed and restores them for other screens and dialogs.
- MCQs appear over the lesson image with a translucent surface, clear selection/answer states, scrollable questions and reachable actions on small screens.
- Existing lessons finish at the last measured spoken phrase. Their old 9.35-second silent hold/padding is excluded from presentation. MP3 recordings, source question identities, authored explanations, MCQ answers and review identities are unchanged.
- Three attributed clinical images appear together during each existing narrated recap. Images retain full framing and original annotations; source details distinguish separate cases and specimens. A small animated flow diagram uses the existing phrase timing. No additional narration is implied.
- Playback uses one audio element, bounded image preloading, animation only while needed, and a common audio clock for speed/seek/recap. Background playback pauses. Duplicate end events cannot grade a review twice.

## Collection, reports and updates

Imported content is rebuilt from the bundled collection plus the currently installed packs. Replacing a pack with an empty correction no longer leaves its removed lessons active until restart. Packs outside the bundled book scope are quarantined with a visible explanation; their files and learning records are preserved.

Reports record a reason, optional comment, exact lesson ID/version and available source/media hashes. Dislike and hide are reversible preferences, separate from grading. Reports remain on the device until the user shares or saves a feedback file. A future agent needs that file to know what was reported. Replacements use the same lesson ID and a higher version, preserving reviews and notes. See [feedback instructions](feedback-and-updates.md).

The importer keeps atomic rollback and cold-start recovery. Download checks include the complete ZIP's SHA-256 and catalog byte size. Friendly errors identify incomplete/corrupt downloads without replacing installed content. Backup migrations preserve existing learning and new feedback fields.

## Size and image fidelity

The 12-image set totals 13,337,179 bytes before optimization and 9,983,024 bytes afterward: **25.149% smaller**. Nine PNGs use verified lossless WebP; three JPEG originals remain because tested lossless alternatives were larger. Every decoded RGBA channel, alpha, dimensions, ICC profile and orientation was checked. There is no resizing or lossy fallback.

Even with six additional clinical images, the new image set is 1,267,007 bytes smaller than the original six-image set. Archives choose the smaller lossless ZIP encoding per entry and deduplicate referenced media. Android staging includes only active media, preventing archived or unfinished batches from bloating the application.

## Delivery and remaining installation gate

Content ZIPs update lesson data/media. Interface and native changes require an APK signed with the original certificate. The builder pins the previously delivered certificate, refuses missing or different signing material, and does not generate a substitute identity. Its `--unsigned` mode is solely a compilation/alignment check and cannot be installed over the existing app.

The temporary-release workflow prepares and verifies a complete content ZIP and proposes the catalog through a review branch. It does not merge into the default branch or delete an asset still referenced by the live catalog. A retention date is not proof that a phone installed the package. See the temporary delivery instructions before retiring a release.

## Verification boundaries

Source, exact image pixels, audio sample boundaries, importer rollback, feedback privacy, backup migration and browser interaction are tested separately. Android code compiles against API 35. Browser screenshots and mocked native bridges do not establish physical-device playback, system-bar behavior or human listening. Those checks remain separate before an installable release is described as device-tested.
