# Future-failure audit — 7 November 2026

## Scope

This audit reviewed the merged mnemonic-prompt checkpoint, original-source authoring, visual guidance, narration preparation, package assembly, Fresh checks, native imports and collection identity. It used isolated source fixtures, synthetic packages and the actual app code. No new teaching images, narration or lessons were generated, and the production policy, real ledgers, lesson data and live catalogs were not changed.

## Reproduced failure cases and repairs

| Failure | Repair and regression coverage |
| --- | --- |
| A private prompt could be written into `web/data` and accidentally bundled. | In-repository exports are confined to `private-content`, including checks of public symlink aliases. Explicit external workspaces remain the author's responsibility. See `test_image_prompt_gate.py`. |
| A localhost/private/reserved URL could count as a public visual reference; valid text saying “no placeholder text” could fail. | Public-reference syntax checks reject those obvious non-public targets. Finished negative wording is accepted while unfilled template markers still fail. These checks do not pretend to prove actual browsing. |
| A produced source question could be renamed before asset generation. | Source authoring preserves its canonical ledger lesson ID, rejects reuse for another question and rejects contradictory or duplicate source selections. Audio filename IDs now retain a separate canonical `lessonId`. See `test_source_policy.py` and `test_visual_source_review.py`. |
| String `"false"` could approve target inspection, and old coordinates could be silently rebound to a changed image. | Guidance requires an actual boolean review, reviewer/time/notes and the hashes/dimensions of the images actually inspected. Changed bytes, incorrect scene-image targets and clinical cropping fail before output. See `test_prepare_book_guidance.py`. |
| A mistyped selection could overwrite guidance with an empty list; faulty guidance was found after loading TTS. | Unknown/duplicate selections and destructive partial writes fail early. Narration verifies all guidance and canonical identities before importing the speech runtime. No TTS is used by these regressions. |
| Assembly could retain an unrelated book, duplicate a source question under another ID, or overwrite lesson JSON with its validation report. | Merge input must retain the original book, unique source questions and stable identities. Output paths must be distinct and cannot alias protected inputs. Unique atomic temporary files preserve existing files on write failure. See `test_book_assembly_presentation.py`. |
| An older or malformed ZIP could replace a working installed lesson. | Native preflight checks source admission, required playable metadata, quiz/scene structure, local file presence and revision floors before moving installed content. Trust comes from the signed app's bundled book metadata, not the incoming manifest. See `ContentPacksTest.java`. |
| A second pack could reuse a lesson ID for another question and inherit its notes/reviews. | Native and browser checks reject source-identity conflicts. The browser examines every conflicting ID, including multiple collisions in either package order. See `import-identity-browser.cjs`. |
| Withdrawing a package removed the only source binding while learning history remained. | Known stable-ID/source bindings persist in a private atomic importer index across withdrawals. Corruption blocks imports without making startup or existing playback depend on reading that index. Unknown pre-upgrade evidence is not fabricated. |
| Existing conflicting legacy packages could block their own corrective withdrawal. | Empty withdrawals remain possible. Saved source bindings remain authoritative; ambiguous pre-index IDs are recorded without choosing a source and cannot later be reassigned by an import. Both package orders and withdrawal/restart paths are covered. |
| Changed same-version metadata or media could masquerade as an identical reimport. | Same-version playable lesson metadata must match semantically. Existing pinned media hashes constrain incoming bytes and survive an identical hashless reimport, preserving repair back to the expected bytes. Changed delivered content requires a new revision. Missing historical pins remain an explicit evidence limit. |
| Fresh instructions invoked a legacy check, and the actual browser test assumed production would remain at 3/200. | Fresh has an explicit `source:check:fresh` command. Instructions and browser expectations read current verified ledger counts while keeping installed/bundled counts separate. An old APK or lesson ZIP is not a prerequisite for Fresh or synthetic authoring checks. |
| Native importer regressions were absent from CI. | The required `test_native_import.py` runner checks a pinned public test dependency, compiles current Java sources and propagates failures. CI runs this plus authoring and import-identity checks independently of legacy media restoration. |

## Verification on this revision

- 121 focused Python tests passed for prompts, source identity, guidance, assembly, trial controls and Fresh builds.
- 29 JavaScript unit tests passed for learning, feedback and topic behavior.
- Six Fresh browser scenarios and five import-identity browser scenarios passed.
- The actual Java importer passed 274 assertions through the pinned-dependency runner.
- The Fresh source check passed with one original publication and zero bundled lessons. The final Android sources compiled into an unsigned Fresh APK; this was a build check, not an installable delivery or device test.
- `git diff --check` passed. No production policy, real ledger, lesson data, catalog, private source or teaching media changed.

The focused local checks do not require old teaching media. The existing GitHub legacy job separately restores its pinned public test fixtures for its full regression suite.

## Checks for a later agent

For Fresh and browser identity checks:

```bash
npm run build:web:fresh
npm run source:check:fresh
npm test
npm run test:fresh
npm run test:imports
```

For source and authoring regressions:

```bash
PYTHONPATH=tests python3 -m unittest \
  test_image_prompt_gate test_production_trial \
  test_source_policy.SourceEvidenceTests test_visual_source_review \
  test_prepare_book_guidance test_book_assembly_presentation \
  test_native_import_runner test_fresh_distribution \
  test_android_fresh_profile test_android_native_identity test_source_scope_builds
```

For the actual native importer, use the pinned `org.json` dependency described in [android/README.md](../android/README.md):

```bash
python3 tools/test_native_import.py --json-jar /path/to/json-20240303.jar
```

An unsigned Fresh APK compilation checks the actual Android sources against the SDK. It is not an installable update and needs no signing key. An installable update must reuse the existing Fresh signing identity and advance the delivered version code; do not regenerate a key.

## Limits and deployment

These checks address reproduced software and workflow failures. They cannot certify medical correctness, actual reference inspection, artistic quality or human listening. New production still requires the user's authorization, current original-source evidence, adequate public visual examples, and the reviews required by [the production workflow](production-workflow.md).

A package replaces the entire installed package with the same pack ID. New batches need distinct pack IDs; repairs preserve lesson IDs and use increasing revisions. Do not use a partial unrelated batch as a replacement for a larger installed package.

Unreadable pre-upgrade source metadata or absent historical media hashes cannot establish facts that were never retained. Do not invent those bindings or clear learning data to suppress an import error. Existing readable bindings and pins are preserved where available.

An ID with conflicting legacy sources and no prior saved binding remains blocked for future imports, even after withdrawing both conflicting packages. Withdrawal is supported; choosing the historical source automatically is not supported.

Native and bundled UI repairs reach the phone through a new same-key APK. A Git merge or lesson ZIP alone does not update an installed Android application. Physical-device playback and human listening remain separate checks; this audit does not claim either.
