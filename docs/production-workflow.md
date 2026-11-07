# Lesson production workflow

This workflow records which source questions have verified teaching assets and a reviewed browser timeline. It never reads or changes a learner's answers, comments, likes, due dates or FSRS state. Production completion does not certify playback on a physical Android device or a human listening review; those checks are recorded separately and can remain pending.

The active source is the original 2015 Raja book only. Read [SOURCE_SCOPE.md](SOURCE_SCOPE.md) and `production/source-policy.json` first. A missing private source is a production blocker, not permission to substitute an independent collection. The normal claim, generation, assembly, completion and packaging tools enforce this scope.

Choose checks for the actual work: `npm run build:web:fresh` followed by `npm run source:check:fresh` validates Fresh without old media. `npm run source:check` validates the separate legacy bundle and needs its pinned assets. Synthetic prompt/source/trial tests need neither an old APK nor an old lesson ZIP. New source-derived lessons still need their actual private book evidence, current authorization and recorded reviews. Read current ledger counts instead of copying the historical 3/200 baseline into a newer private checkpoint.

## Files and identities

- `production/books/<bookId>.json` contains the public-safe production checkpoint: book metadata, stable source IDs, statuses and completed lesson references.
- `private-content/` contains the private source transcription, original question text, source figures and extraction audit. It is excluded from Git. The original uploaded PDF is not required inside the application or repository.
- `web/data/lessons.json` contains the original teaching lessons assembled for the app. Each lesson links to `source.bookId` and `source.questionNumber`; an optional `source.questionId` must match the manifest's stable ID.
- `web/media/audio/<audio-basename>.timing.json` records the final measured voice segments. Its scene IDs, boundaries and transcripts must match the lesson.
- `web/media/real/attributions.json` records the original real-image bytes, source, license and SHA-256. Each lesson also carries readable attribution in `realImages`.

Use stable IDs when a batch is interrupted or a book is processed out of order. A completed lesson for question 182 does not imply that questions 1-181 are complete.

## Production states

| State | Meaning | Selected by `next`? |
|---|---|---|
| `ready` | Ledger record is eligible, subject to a fresh check that its actual source evidence is available | Yes |
| `needs_review` | A source, extraction or content issue still needs resolution | No |
| `claimed` | A named batch owns the unfinished work | No |
| `produced` | The lesson assets passed technical checks and the explicitly recorded source, visual, audio-decode and browser-timeline checks | No |

The manifest owner resolves a `needs_review` reason and changes that source record to `ready` after checking it. A source figure or formula may require a layout check without being a medical error; record the actual resolution rather than silently discarding the flag.

`completedVideos` and `completedQuestionNumbers` are derived from records marked `produced`. They describe production, not what the user has learned.

## Inspect and reserve work

The CLI needs Python 3.10 or later. `complete` additionally needs `ffprobe` on `PATH`. Mutating commands use POSIX file locks and run on Linux or macOS; they have no third-party Python package dependencies.

The active book from the source policy is selected by default:

```bash
python tools/production.py status
python tools/production.py next --count 10
python tools/production.py claim --count 10 --batch-id batch-2026-11-07-01
```

To select the book explicitly, put the target before the subcommand. Historical manifests can be inspected read-only; mutation is restricted to the active source:

```bash
python tools/production.py --book shahzad-raja-2015-200-practice-questions status
python tools/production.py --manifest production/books/shahzad-raja-2015-200-practice-questions.json next --count 10
```

`status` and `next` are read-only. `next` selects ready records in source-question order, inspecting every record's status rather than using the maximum completed number. It skips both outstanding claims and unresolved review items.

Those commands do not prove that the private source still exists. Before a claim is written, the source gate checks the original extraction fingerprint, question identity, choices, keyed answer and explanation. The claim stores a `sourceEvidence` binding; keep it with the authoring input so generation and completion can verify the same source. A changed, incomplete or missing extraction fails before new assets are created. See the source-policy tests for the accepted private record shape and evidence binding.

`claim` saves the selected stable IDs immediately. Repeating the same batch ID resumes its original selection; it does not silently append another ten questions. A resumed batch reports any already-produced records and remaining review blockers. The requested count sets the size of a new batch only.

To release unfinished claims for retry:

```bash
python tools/production.py release --batch-id batch-2026-11-07-01
```

Release returns that batch's unfinished claimed records to `ready`. It leaves produced records intact. The same batch ID can reclaim its original outstanding selection if another batch has not taken those questions. A conflicting claim causes an error rather than taking another batch's work.

## Produce and review a lesson

For each claimed source ID:

1. Check the original question, keyed answer, explanation and any linked source figures or cross-references. Review historical management statements against suitable current sources before using them in a new lesson.
2. Write one tested objective and validate its canonical English annotation against the declared taxonomy version.
3. Draft the fixed locus, original English narration and quiz. Compare them against the specific source question, keyed answer and explanation, then record the per-question `sourceReview` described below. Keep source text in the private archive.
4. Follow [mnemonic-image-prompt.md](mnemonic-image-prompt.md): actually inspect Pixorize, Picmonic and Sketchy examples, write the fact-to-symbol/action map and `artBrief`, and review the exact `imagePrompt`. Pass `tools/prepare_image_prompt.py --emit` before any new or replacement mnemonic image-generator call. A missing or stale review blocks generation; the fingerprint-only command never grants approval. Send the exact emitted `prompt`, then visually inspect the generated result before lossless optimization and target placement.
5. Generate the final voice segments and derive their timing from the actual audio samples. Regenerating the voice invalidates the previous timing until it is checked again.
6. Assemble the lesson, quiz, measured timeline and attributed real-image gallery/recap.
7. Inspect the images and labels, decode the actual audio, and test the browser timeline: camera/spotlight positions, pauses, seeking, playback speed and the transition to the MCQ.
8. Record exactly which checks were performed. Device playback and human listening are separate checks; when unavailable, retain them as false and pending.

The detailed visual criteria are in [visual-production-rules.md](visual-production-rules.md). Writing a script, downloading an image or creating an audio file alone does not mark a source question produced.

The image-prompt gate binds the exact prompt, brief, symbols, locus, source evidence, reviewed teaching content and both visual specifications. It supplements the source review; it does not expand production authorization or replace post-generation visual inspection. Keep its review and ready artifact private. Existing unchanged-media replay and audio-only repair do not require invented retrospective prompt reviews. The Python tool validates records and emits the approved prompt; agents must obey the documented checkpoint when calling external image-generation tools.

### Preserve identity during repairs and audio preparation

A produced question must retain the ledger's exact canonical lesson ID. Authoring rejects renaming it, reusing another question's lesson ID, contradictory question-number fields, and duplicate question selections. These checks happen before artwork or narration preparation, so a renamed draft cannot detach the repaired content from its existing learning history.

Prepared audio has two identities: `id` names the audio files, while `lessonId` identifies the canonical app lesson. `assemble_book_batch.py --prepare-audio` records both. `generate_audio.py` and the historical assembler use the dedicated audio validator; ordinary lesson/image authoring remains strict about the canonical `id`. If an older produced audio draft uses a different filename ID, add the verified canonical `lessonId` from that same question's ledger record. This is identity metadata, not new narration: do not regenerate or rewrite audio provenance merely to add it.

Unknown or duplicate audio `--lesson` selections, unsafe audio IDs and missing or mismatched guidance are rejected before the speech model is initialized or output is rendered.

### Bind target coordinates to the inspected image

For new guidance preparation, each lesson entry in the private `inspected-targets.json` must contain `schemaVersion: 1`, `visuallyInspected: true` as a JSON boolean, the actual `reviewer`, a timezone-aware `reviewedAt`, nonempty `notes`, and named `targets`. Add an `images` map keyed by every poster, primary clinical, scene and target image path. Each image record contains the `sha256`, integer `width` and integer `height` of the bytes actually inspected.

Complete this record only after viewing those images and placing the targets. The tool compares the recorded bytes and dimensions with the current files; it never makes old coordinates valid by silently calculating a new hash. Any changed image requires another actual target inspection. Targets must belong to the image displayed during their narrated scene; clinical-image targets use zoom `1` and retain their full framing.

`prepare_book_guidance.py` rejects unknown/duplicate `--lesson` selections, draft/inspection output aliases, and subset writes that would discard other plans in an existing guidance document. Use a separate `--output` for a subset or prepare the full batch. Valid output is replaced atomically, so a failure preserves the previous guidance. Existing built guidance and measured audio retain their historical provenance; no fabricated retrospective inspection is required for unchanged replay.

### Protect assembly inputs and collection identity

Assembly rejects mixed-book collections, duplicate source questions under different lesson IDs, ID reassignment, revision downgrades and changed same-version lesson metadata. It does not silently discard an incompatible existing collection; correct the intended input scope before retrying.

Lesson output, validation-report output and any merged app output must use distinct paths. They must not alias drafts, guidance, taxonomy, source evidence, source policy or the production ledger. Use the normal private batch defaults, or deliberate distinct paths. Unique temporary files and atomic replacement protect existing files from interrupted writes; assembly still does not mark a lesson produced or approve its clinical/visual quality.

### Bind the authored content to an actual source review

For a new question, its production-ledger record must contain a `sourceReview` with:

- `schemaVersion: 1`, an actual timezone-aware `reviewedAt`, the actual `reviewer`, and meaningful `notes` describing the source comparison.
- `sourceQuestionChecked`, `keyedAnswerChecked` and `explanationChecked`, each set to true only after that comparison occurred.
- `sourceRecordSha256` from the claim and `evidenceSha256`, the canonical hash of its complete `sourceEvidence` object.
- `authoredContentSha256` and `quizSha256`, computed from the reviewed draft by `source_policy.content_fingerprints(draft_lesson, authoring=True)`.
- For a lesson with a gallery/recap presentation, `visualSupplementSha256` from that same helper. It binds the complete `realImages` records (including captions and provenance) and the recap's nodes, edges and ordered phrase-to-node bindings. Actually review those visual teaching details before recording their hash.

The fingerprint helper calculates hashes only; it does not create a review or approve content. The authored fingerprint covers the title, locus, ordered scene identities, captions and narration, plus the quiz. The gate recomputes the equivalent public-lesson representation at completion. Changed teaching content invalidates the review. Copying `sourceEvidence` from a legitimate claim onto an unrelated draft does not satisfy this gate.

The separate visual fingerprint has the same value in an authored `presentationPlan` and its assembled `presentation`: measured recap timestamps are excluded, while image records, node labels, edges and `phraseId`/`nodeId` bindings remain exact. Deleting the gallery or recap cannot remove an existing review requirement. A display gallery must also exactly match the registered `realImages`. Timing remains subject to its independent measured-media checks.

`assemble_book_batch.py --prepare-audio` carries `realImages` and `presentationPlan` into the audio-authoring input so the same approval is enforced before narration. Adding those metadata fields to an already reviewed input does not alter spoken text or a guidance plan; existing measured audio need not be regenerated when those remain identical. Keep old audio provenance as the truthful record of the input used for its synthesis, and revalidate the prepared input against the current review. Do not rewrite old provenance to suggest that audio was synthesized again.

These records make source comparison explicit and detect later changes. They do not decide clinical correctness or establish that a reviewer performed an honest comparison. Record the actual work and preserve the source evidence for audit. The exact frozen starter lessons use their separately pinned historical reviews.

## Complete after the recorded asset and browser review

After the source, visual, audio-decode and browser-timeline checks, write a QA report. A single report can identify several reviewed lessons:

```json
{
  "schemaVersion": 1,
  "bookId": "shahzad-raja-2015-200-practice-questions",
  "reviewedAt": "2026-11-07T12:00:00Z",
  "sourceChecked": true,
  "visualInspected": true,
  "audioDecoded": true,
  "timelineBrowserTested": true,
  "physicalAndroidTested": false,
  "humanListeningReviewed": false,
  "lessons": [
    {"questionNumber": 54, "lessonId": "shahzad2015-q054"}
  ],
  "notes": [
    "Replace this example with the actual checks, evidence and limitations."
  ]
}
```

Use the real review timestamp. Set each boolean according to what occurred. An optional `lessonSha256` on each lesson entry binds the report to the canonical JSON hash produced by the validator. The report may instead identify one lesson with top-level `questionNumber` and `lessonId`.

```bash
python tools/production.py complete \
  --question 54 \
  --lesson web/data/lessons.json \
  --root web \
  --batch-id batch-2026-11-07-01 \
  --qa-report production/qa/starter-review.json
```

The lesson input may be a single lesson object, the app's lesson array or an object containing a `lessons` array. Exactly one lesson must match the selected book and source question number. An unclaimed ready record, such as a deliberately selected starter lesson, can be completed without `--batch-id`. A claimed record requires its owning batch ID.

`--qa-report` records the checks actually performed. The four asset/browser checks must be true; the Android-device and human-listening booleans must be explicitly present and may be false. The tool verifies the report's book, question and lesson identity, then saves its checks, notes and hash in the source record. False device/listening checks persist as `pendingDeviceQA: true` and `pendingHumanListeningQA: true`. The tool does not perform a visual review, listen to narration, or establish medical correctness on its own. It refuses completion without a matching report or for records still marked `needs_review`.

The technical gate checks:

- Source book/question identity, stable source ID when present, lesson identity and positive revision.
- A 60-90 second full lesson, a continuous scene sequence starting at zero, and an adjacent real-image outro ending at the declared duration.
- The final measured audio companion: matching scene IDs, timestamps and transcripts. The companion defaults to the audio filename with `.timing.json`; use `--timing PATH` for another location.
- Actual audio duration and an audio stream using `ffprobe`. Timeline comparisons allow 20 ms; container duration allows 250 ms for encoding/padding differences.
- A usable MCQ structure with unique answer options, a valid key and an explanation.
- Canonical active tag IDs and exact English labels, the declared taxonomy version, one learning focus and compatible specialty/domain scope.
- A stable locus and all referenced local audio, poster, scene and real-image files. Media paths must remain within the supplied web root.
- Real-image source and license URLs, attribution and explicit real-image provenance. The local image bytes must match the recorded SHA-256. Merely calling an asset a real image is insufficient.

For a reviewed record, the manifest may additionally contain `expectedTagIds`, `expectedCorrectIndex` or `expectedQuizSha256`. When present, these are exact checks against the final lesson. Without them, the tool validates quiz structure and registry membership; the operator remains responsible for the source-aligned answer and teaching content.

On success, the record becomes `produced` and stores the lesson/quiz hashes, media hashes, measured duration, taxonomy version and QA report. The produced count means verified lesson assets, not device certification or learner mastery. Repeating completion with identical lesson metadata, media, timing and QA report is idempotent. An already-produced record with changed content or a different QA report is not silently overwritten; it requires an explicit reviewed revision workflow. Pending device and listening checks are never erased by an idempotent completion call.

## Atomic checkpoints

Claims, releases and completions hold a per-manifest process lock. Updates are written to a temporary file in the same directory, flushed to disk and atomically replaced. Locks are kept outside the repository and are released if the process exits. The CLI rereads the manifest under the lock before changing a completion record, so another batch's claim is respected.

The tool preserves other manifest fields and never opens a learner database. Keep final lesson assets unchanged between review and completion; a changed asset needs another review and fresh validation.

## Build a data-only content pack

Once the lessons and referenced media are ready:

```bash
python tools/build_pack.py \
  --input web/data/lessons.json \
  --web-root web \
  --output dist/InstaAnki-Starter-Pack-v1.zip \
  --pack-id instaanki-starter-v1 \
  --version 1

python tools/build_pack.py --verify dist/InstaAnki-Starter-Pack-v1.zip
```

Use repeated `--lesson LESSON_ID` arguments to select specific lessons. The builder includes the lesson data and referenced local media, writes a schema-version-1 manifest with a SHA-256 for every payload file, and produces a checksum for the complete ZIP.

Packs contain no HTML, JavaScript, SVG, PDF, native code or raw source-book archive. Source identifiers, original paraphrased teaching content and required attribution remain in the lesson data. Checksums detect changes; they do not establish who published a pack.

The ZIP builder does not mark a source question produced and does not update learner state. It also does not upload a pack or publish a release. Keep any deliverable containing a private source archive in the user's private delivery channel.
