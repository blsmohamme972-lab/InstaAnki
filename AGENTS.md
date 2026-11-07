# InstaAnki project instructions

## Current task scope

The user explicitly stopped new-video production. Work only on app errors, interface/playback improvements, lossless media optimization, feedback/reporting, and update delivery. Test with the three existing Raja lessons. Do not generate new lessons, narration, mnemonic artwork, or video exports, and do not increase the produced count. Resuming new lesson production requires a new explicit user instruction. Unfinished batch drafts are paused and are not active content.

## Active source and user intent

The active source is **200 Practice Questions in Cardiothoracic Surgery**, Shahzad G. Raja, 2015. Keep that original book as the only active publication. Its stable book ID is `shahzad-raja-2015-200-practice-questions`. Current work repairs the app and its three existing lessons; it does not continue lesson production.

- Read `production/source-policy.json` and `docs/SOURCE_SCOPE.md` before creating, assembling, generating audio for, completing, packaging, or publishing lessons.
- Do not substitute a different book, general medical knowledge, an independently authored collection, or a new publication when the requested source is unavailable. Explain the missing evidence and pursue legitimate recovery of the same source.
- Do not relabel the archived Medical Foundations lessons as Raja lessons. Similar topics and new images are not proof that a lesson represents a particular book question.
- A future explicit user instruction may change the source scope. Record that actual instruction, update the source policy and its tests deliberately, and preserve truthful source identities. Never invent user approval or add a force/bypass option to keep production moving.

## Evidence before production

- A new lesson requires the actual question, choices, keyed answer, explanation, and any referenced figures for that specific edition. Verify that the private evidence is readable now; an old extraction audit or `ready` ledger flag does not prove current availability.
- The production tools bind the source extraction and selected questions to hashes. Run their checks before generating expensive artwork or audio, and again before completion and delivery.
- Before asset generation, actually compare the authored lesson and quiz to the source and record the per-question `sourceReview` with the source-record, authored-content and quiz fingerprints. A copied `sourceEvidence` object or a calculated hash is not a completed review. Changed narration, captions, title, locus or quiz requires a fresh comparison and review record.
- Existing exactly verified starter lessons may be repackaged under the policy's immutable replay checks. This does not authorize new source-derived lessons without evidence.
- Keep question identities stable and count only verified produced records. The current original-book total is 3/200 (Q5, Q54, Q182). A separate collection does not increase that count.
- Keep raw source text, private archives, encryption keys and Android signing keys outside Git. Recover and verify a durable private backup before relying on it for later batches.

## User data and review

- Content corrections must preserve learning history, private notes, saved lessons and preferences. Never clear app storage or uninstall the app to repair a content selection.
- Use the narrowly scoped correction tool only to withdraw the exact unrelated imported collection documented in `docs/SOURCE_SCOPE.md`.
- Record source review, visual inspection, audio decoding and browser timeline checks honestly. Device playback and human listening remain separate checks; do not claim either from a browser/JVM test.
- Run `npm run source:check` and the relevant source-policy tests before delivering changed content or code. See `docs/production-workflow.md` for the full workflow.

## Repair and delivery rules

- Reports saved on the phone are not visible to an agent until the user shares the feedback JSON. Read its reason, exact lesson ID/version and hashes; compare with the currently active version before preparing a correction. A stale report must not roll back a newer correction. Dislike, hide, report and quiz grade remain separate actions.
- Preserve the lesson ID, source identity and learning history when repairing an existing lesson. Review any changed teaching content against that same source. A cosmetic repair does not authorize producing other source questions.
- Use the lossless media optimizer on generated and retrieved images; verify decoded pixels, alpha, color profile, orientation and dimensions. Retain originals and provenance. Do not reduce quality or resize silently.
- Run `tools/prepare_existing_media.py` before checks on a fresh checkout. It restores only pinned existing lesson media from the supplied update ZIP or the documented licensed source URLs. Do not commit newly prepared binary media or temporary ZIPs to Git history.
- Keep the original Android signing identity. Missing signing material is a release blocker, not permission to generate a new key, change the package name, uninstall the user's app or clear its data.
- Use the reviewed temporary-release workflow for data-only updates. A release still referenced by the live catalog must not be deleted. Do not claim a phone installed a pack without actual confirmation. Interface/native changes need a same-key APK; a content ZIP cannot update executable app code.
- Offer repaired presentation packages only through `content/catalog-v2.json`, with an explicit minimum app version (the current repair requires version code 3). Keep the legacy `content/catalog.json` lesson list empty: already-installed older apps ignore minimum-version fields. Check both catalogs before retiring a download.
