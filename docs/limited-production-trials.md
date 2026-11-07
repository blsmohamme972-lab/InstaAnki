# Limited production trials

A request for a small test batch authorizes only its recorded source questions.
It must not turn the general `newProductionEnabled` flag on. The source book,
readable private question evidence, content review, image provenance, measured
audio and honest QA requirements continue to apply.

## Finite authorization

The policy can contain one `productionTrial` record with schema version 1, an
`active`, `paused` or `completed` status, the original `bookId`, an exact safe
`batchId`, unique positive `questionNumbers`, and `maxNewLessons` equal to that
list's length. It must also record the actual user instruction in
`authorizationText` and an ISO `authorizedAt` timestamp with a timezone. The
general `newProductionEnabled` flag must remain `false` while this record exists.

Actual authorization text, source identities, review decisions and batch
checkpoints belong in the private production record. This code change does not
authorize a batch or enable general production. Do not substitute another ready
question if a selected question fails review, and do not include unrelated
historical media in a new trial package.

Inspect the scope without changing it:

```bash
python3 tools/production.py status
python3 tools/production.py next --count 10
```

`next` returns only ready questions from the finite active selection. A paused
or completed trial returns no new candidates. Claim the exact reviewed selection,
passing its count and batch ID. For example, a synthetic three-question fixture
uses:

```bash
python3 tools/production.py claim --count 3 --batch-id synthetic-three-question-trial
```

The CLI's ordinary default count of 10 is rejected whenever it differs from the
finite selection. Resuming the same batch cannot add or substitute source
questions. A hold, missing source record, changed evidence or other-batch claim
aborts the whole claim before writing the ledger.

## Narrated ending input

Both preparation commands require an explicit `--input` draft path. Guidance,
inspected-target and report paths default to named files beside that draft and
can be overridden explicitly. No production directory or trial checkpoint is
hardcoded in these tools.

New drafts for `tools/assemble_book_batch.py` require three to six distinct,
licensed `realImages`. Keep `realImage` equal to the first complete record: that
primary image also anchors the measured audio companion. Each record needs a
safe local media URL, title, caption, author, license, HTTPS source and license
URLs, attribution, `aiGenerated:false`, and the exact local image SHA-256.
Optimize and inspect final image bytes before preparing guidance.

The target-inspection record must bind each poster, primary clinical, scene and
target image to its actually inspected hash and dimensions, alongside the real
reviewer, timezone-aware review time and notes. `visuallyInspected` must be the
JSON boolean `true`; a nonempty string is not approval. See the
[target-inspection workflow](production-workflow.md#bind-target-coordinates-to-the-inspected-image)
for the required fields. Changing an image requires reinspection before guidance
can be rebuilt. A subset selection must use its own output when an existing
guidance file also contains other lessons.

Both `realImage` and every `realImages` record must already use the canonical
format before source review: an explicit `url` beginning with `media/` without a
leading slash, a nonempty string `license`, and an explicit HTTPS `licenseUrl`.
The assembler rejects `/media/` URLs, `publicPath`-only records, and license
objects with a clear input error. It preserves complete canonical provenance
without rewriting reviewed fields. If a reviewed draft needs these corrections,
review the corrected draft again; do not reuse its earlier fingerprints.

Add this shape to each draft, replacing the labels and IDs with the actual
source-reviewed final scene and phrases:

```json
{
  "presentationPlan": {
    "schemaVersion": 1,
    "endingSceneId": "s06",
    "recap": {
      "nodes": [
        {"id": "a", "label": "First reviewed point"},
        {"id": "b", "label": "Second reviewed point"},
        {"id": "c", "label": "Third reviewed point"}
      ],
      "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
      "cueBindings": [
        {"phraseId": "s06-p01", "nodeId": "a"},
        {"phraseId": "s06-p02", "nodeId": "b"},
        {"phraseId": "s06-p03", "nodeId": "c"}
      ]
    }
  }
}
```

Every node must have a phrase binding in the final narrated scene. Bindings
follow actual phrase order and contain only `phraseId` and `nodeId`. Do not put
estimated timestamps into the draft. The assembler derives gallery/recap start,
each node highlight and the effective ending from measured `voiceStart` and
`voiceEnd` boundaries. Playback finishes at the final spoken phrase even if the
encoded audio contains a legacy silent tail. Source review must also inspect
recap labels and image captions; a hash by itself is not a content review.

Production completion validates the resulting presentation and rejects a new
trial lesson that omits it. Do not append or modify gallery metadata after a
lesson's completion hash has been frozen.

## Closing the scope and later packaging

Complete only the recorded finite selection after the real source, image,
audio-decode and browser checks succeed. Record physical-device playback and
human listening as false unless actually performed. Completion freezes the
exact lesson, asset, source-review and audio-timing hashes in the ledger. The
batch checkpoint becomes `completed` when all selected questions are produced.

After all selected questions are produced, change only `productionTrial.status` to
`completed`; retain its authorization history and keep general production
disabled. The policy then blocks new claims and authoring/completion of every
unproduced question. It does not revoke exact produced lessons: the normal
pack builder can still verify and package them with their retained source
evidence, review and frozen assets. A missing private source or modified file
remains a real blocker unless separately reviewed immutable publication
evidence is available. A later request for more questions requires its own
explicit reviewed authorization; do not reuse this trial to expand the set.

For a Fresh data ZIP, select only the approved trial and its original-book publication.
Use a distinct pack ID for each additional batch. Reusing an installed pack ID
replaces that entire package rather than appending its lessons. A repair keeps
the original lesson IDs, uses a higher lesson revision, and carries the complete
intended contents of that package. Do not overwrite an earlier batch with a
different subset under the same pack ID.
Historical production counters may truthfully include older produced records;
the imported trial contains only its explicitly selected lessons. A catalog entry for Fresh
must declare `minAppVersionCode:4` and
`targetPackageNames:["com.instaanki.fresh"]`. Those are catalog fields, not
current `build_pack.py` arguments. Do not reuse the historical starter release
profile, which selects an older fixed collection. An explicit source-valid local import works
without another APK.

After completing a trial, synchronize the canonical publication counters and question statuses with the private ledger before rebuilding Fresh. `npm run build:web:fresh` can refresh an earlier generated stage whose cached progress predates that ledger. The old stage is checked for its exact Fresh identity, empty lessons, consistent metadata and allowed files; the current source and new output still require current-ledger validation. A stale generated preview does not require restoring historical lesson media.

The private worktree, recovered source hashes, raw book evidence and authoring
checkpoints must not be pushed publicly. Keep only separately reviewed safe
code changes in any public change set.

## Focused regression checks

```bash
PYTHONPATH=tests python3 -m unittest test_production_trial test_book_assembly_presentation test_presentation test_source_policy.SourceEvidenceTests -v
git diff --check
```

These tests use synthetic source fixtures for authorization and ending-boundary
failure cases. They do not claim clinical review, listening or phone testing.
