# InstaAnki project instructions

## Current task scope

The user explicitly stopped new-video production. Work only on app errors, interface/playback improvements, lossless media optimization, feedback/reporting, and update delivery. Do not generate new lessons, narration, mnemonic artwork, or video exports, and do not increase the produced count. Resuming new lesson production requires a new explicit user instruction. Unfinished batch drafts are paused and are not active content.

The subsequent prompt-update request authorizes improving the image prompt, reference-study instructions and pre-generation checkpoint. It does not authorize generating or replacing images, narration or lessons. Follow the mandatory workflow below whenever a later instruction authorizes mnemonic artwork.

On 2026-11-07 the user explicitly requested: "No need for old videos! Start fresh." The approved fresh distribution is **InstaAnki Fresh**, package **com.instaanki.fresh**, initially version **0.3.0 / code 4**. It ships an empty lesson collection and no old lesson media or progress. The three verified Raja lessons remain historical records and QA inputs, not bundled fresh content. Keep the historical production count truthful at 3/200 and show zero installed lessons in the fresh app. The approved source remains the same Raja book.

## Active source and user intent

The active source is **200 Practice Questions in Cardiothoracic Surgery**, Shahzad G. Raja, 2015. Keep that original book as the only active publication. Its stable book ID is `shahzad-raja-2015-200-practice-questions`. The fresh app ships no lessons; the three existing lessons remain historical and QA records. Current work does not continue lesson production.

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

## Mandatory checkpoint before mnemonic image generation

- Read `docs/mnemonic-image-prompt.md` and `docs/visual-production-rules.md` before drafting any new or replacement mnemonic image prompt. The required direction is an original 2D cartoon mnemonic story with expressive characters, memorable visual puns, purposeful interactions and clear fact-to-symbol mappings.
- Actually study public artwork and the teaching method at all three references: [Pixorize](https://pixorize.com/), [Picmonic](https://www.picmonic.com/) and [Sketchy](https://www.sketchy.com/). Use the official method/example links in the prompt guide. Record the exact page and example, what was visibly inspected, and how each method informs this lesson. A homepage visit, brand-name mention, search snippet or tiny promotional thumbnail is not a completed visual review. Never mark an inaccessible example as inspected.
- A stable `locus` organizes recall; it does not require an ornate literal palace. Build one coherent story in which the teaching characters and objects interact. Keep scenery subordinate to those symbols. Do not drift into glossy 3D, photorealism or decorative architectural scenes for mnemonic art.
- After the original-source review, prepare the full `artBrief`, `mnemonicSymbols` and exact `imagePrompt`. Complete the per-prompt review checklist in the guide. The reviewer must record actual observations and decisions; calculating a fingerprint does not approve a prompt.
- Run `tools/prepare_image_prompt.py` for the selected lesson immediately before every new or replacement mnemonic generator call. It must validate the private reference/prompt review and emit a matching ready artifact. Send exactly its `prompt` to the image generator. Editing the prompt, art brief, symbols, locus, reviewed source/content, or either visual specification requires a new review and gate run. No force flag, fabricated review or hand-written ready receipt is permitted.
- This is an authoring-tool checkpoint plus an agent workflow requirement, not a claim that Python intercepts external image-generation tools. Keep review records and ready artifacts private; do not publish source-derived briefs or source evidence to GitHub. Inspect the actual generated image afterward and reject any result that fails the same style, mnemonic, source-fidelity or phone-readability checks.
- Existing unchanged media replay and audio-only repair retain their established checks. Do not invent retroactive image-prompt approvals for historical assets or regenerate media just to fill a new field. Source policy and the user's production authorization remain required independently of this checkpoint.

## User data and review

- Content corrections must preserve learning history, private notes, saved lessons and preferences. Never clear app storage or uninstall the app to repair a content selection.
- Use the narrowly scoped correction tool only to withdraw the exact unrelated imported collection documented in `docs/SOURCE_SCOPE.md`.
- Record source review, visual inspection, audio decoding and browser timeline checks honestly. Device playback and human listening remain separate checks; do not claim either from a browser/JVM test.
- Run `npm run source:check` and the relevant source-policy tests before delivering changed content or code. See `docs/production-workflow.md` for the full workflow.

## Repair and delivery rules

- Reports saved on the phone are not visible to an agent until the user shares the feedback JSON. Read its reason, exact lesson ID/version and hashes; compare with the currently active version before preparing a correction. A stale report must not roll back a newer correction. Dislike, hide, report and quiz grade remain separate actions.
- Preserve the lesson ID, source identity and learning history when repairing an existing lesson. Review any changed teaching content against that same source. A cosmetic repair does not authorize producing other source questions.
- Use the lossless media optimizer on generated and retrieved images; verify decoded pixels, alpha, color profile, orientation and dimensions. Retain originals and provenance. Do not reduce quality or resize silently.
- For the empty Fresh app, use `npm run build:web:fresh`, `npm run test:fresh`, and `npm run build:apk:fresh`. It needs no old APK, lesson ZIP, source media or migration. See `docs/FRESH_INSTALL_0.3.0.md`. Use the compiled fresh web directory as Android input so learning-engine changes are included.
- Run `tools/prepare_existing_media.py` before legacy-content checks on a clean checkout. It restores only pinned existing lesson media from the supplied update ZIP or the documented licensed source URLs. `--from-pack` restores prepared outputs; lossless comparison tests also need the pinned originals, restored separately or with `--download-sources`. These QA inputs must not be bundled in Fresh. Do not commit newly prepared binary media or temporary ZIPs to Git history.
- The legacy **com.instaanki.app** distribution must retain its original signing identity. Missing legacy signing material is not permission to replace that identity, uninstall the user's app or clear its data.
- The user's explicit fresh-start instruction authorizes one new, separate signing identity for **com.instaanki.fresh**. Save its private signing backup durably before delivering the fresh APK, pin its public certificate, and reuse that same new key for every future fresh-app update. Never regenerate a key because a later build cannot find it. Keep signing secrets outside Git and outside all APKs. The original installed app remains untouched.
- Use the reviewed temporary-release workflow for data-only updates. A release still referenced by the live catalog must not be deleted. Do not claim a phone installed a pack without actual confirmation. Interface/native changes need a same-key APK; a content ZIP cannot update executable app code.
- Offer repaired presentation packages only through `content/catalog-v2.json`, with an explicit minimum app version (the current repair requires version code 3). Keep the legacy `content/catalog.json` lesson list empty: already-installed older apps ignore minimum-version fields. Check both catalogs before retiring a download.
- Fresh uses the existing live v2 catalog but only offers content whose `targetPackageNames` explicitly includes `com.instaanki.fresh`; APK notices must also name that exact package. A legacy or unscoped offer must never repopulate the fresh app or offer the wrong APK. Explicit user-selected, source-valid imports remain available.
