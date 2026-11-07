# Temporary delivery of the three existing Raja lessons

This workflow prepares and uploads a **data-only ZIP of the existing Q5, Q54 and Q182 lessons**, then opens a pull request for the app's update catalog. It does not create lessons, narration, images, videos, or another publication. The original book remains at **3/200**.

The workflow is prepared in this repository. Preparing the code or passing local tests does not mean a GitHub release has been uploaded, the workflow has been run, or the phone has received an update. Those are separate observable steps.

## What the phone receives

The stable pack ID is `instaanki-starter-shahzad2015-v1`. The three lesson IDs stay `shahzad2015-q005`, `shahzad2015-q054` and `shahzad2015-q182`. A corrected lesson keeps its ID and increases its integer lesson version; a changed ZIP receives a new `major.minor.patch` content version. Review history and notes stay attached to the lesson ID.

The archive contains `manifest.json`, `lessons.json`, and only referenced public lesson media. It contains no source PDF, private extraction, backup, review history, notes, signing key, HTML, JavaScript, or native code. The package builder checks every payload checksum; the delivery tool also records the complete ZIP's SHA-256 and byte size, including its manifest.

Content delivery updates lesson data and media. Interface changes, new native feedback export, immersive playback, and other APK features require a compatible APK signed with the original signing identity. A content ZIP does not install those features. Keep the current app installed and retain a learning backup.

The current presentation update requires **InstaAnki 0.2.0, app version code 3**. Earlier apps can understand the ZIP container, but cannot apply the new narration endpoint, multi-image gallery or narrated recap. The delivery tool therefore records `minAppVersionCode: 3` and publishes offers only through `content/catalog-v2.json`, with the `app-v3` channel marker. The repaired player checks that minimum before offering or starting a download, and the native downloader checks it again before network or cache writes.

The old 0.1.1 app does not enforce minimum app versions. Its `content/catalog.json` must keep `packs: []`; changing a minimum-version field in that legacy catalog would not protect the old app. The legacy catalog can later advertise a verified same-key APK through `latestApp`. Both catalogs are currently empty of lesson offers. Importing the new content ZIP into an old app must not be described as installing the player repair.

## Before the first run

1. Review and merge the app/source-check changes and this workflow through the normal code-review process. A manually dispatched workflow must exist on the default branch. Run it from that branch.
2. Check that the repository permits Actions to create pull requests with its normal `GITHUB_TOKEN`. This workflow requests `contents: write` and `pull-requests: write` only for the publish/retire job. The retirement-check job is read-only. It does not require a personal token, signing secret, or private source archive.
3. Check the source and media review evidence for the existing three lessons. The workflow uses `tools/prepare_existing_media.py --download-sources` before source checks or packaging. That script restores the pinned reviewed public images and verifies the exact expected output bytes. It pins Pillow 13.0.0 and verifies the encoder; it does not generate art. See [media reproduction](media-reproduction.md).
4. Choose a new stable content version when bytes have changed. The currently prepared three-lesson content pack is version `1.2.0`, with integer lesson versions `3`. Use the actual reviewed pack version for its first publication; use a later version for a later changed archive. Never reuse a version to repair a URL, replace bytes, or revive a retired release.

The saved version `1.2.0` is bound by `repairPack` in [the verification report](verification-0.2.0-app.json): pack ID `instaanki-starter-shahzad2015-v1`, manifest title **Raja existing lessons — presentation repair**, **12,167,118 bytes**, SHA-256 `2ad35dabeced0bdf320df0a34a315f3d53aa0032ecc4890e257ceabd7a28d801`. The workflow preserves that exact title, including the em dash. The delivery helper rejects a lower version, or a different identity or complete ZIP fingerprint under `1.2.0`, even before the first GitHub release exists. A higher explicit version still undergoes all source, media and delivery-history checks. This prepared-artifact record does not claim that a release was uploaded or a catalog entry activated.

GitHub documents [manual workflow dispatch](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow), [the automatic workflow token](https://docs.github.com/en/actions/concepts/security/github_token), and [repository Actions settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository). A PR opened by the normal Actions token may require a repository writer to approve its checks. Review the PR's actual check state before merging.

Publication remains queued until the reviewed merge is approved and completed. Do not add a branch-push publisher or retarget a tag to work around that approval. GitHub also requires workflow-write authority when a release target changes workflow files relative to the default branch; its ordinary `GITHUB_TOKEN` cannot receive that authority. The [release API documentation](https://docs.github.com/en/rest/releases/releases#create-a-release) describes this restriction.

## Publish a temporary ZIP

In GitHub, open **Actions → Temporary existing-lesson delivery → Run workflow** on the default branch.

| Input | Value |
| --- | --- |
| `operation` | `publish` |
| `version` | The reviewed stable content version, such as `1.2.0` for the current prepared pack |
| `retention_days` | 1–90 days; default 30 |

The workflow performs these steps:

1. Restores only pinned existing media into the runner's workspace, runs the original-book source check and delivery tests, and builds a ZIP containing exactly the three existing lessons.
2. Compares the archive against current reviewed public lessons, source bindings, truthful publication counts, and every referenced media hash. Extra files, wrong source IDs, another publication, changed unreviewed teaching, and inflated lesson counts stop the run.
3. Creates a draft GitHub release named `content-raja-VERSION` and uploads one asset, `InstaAnki-Raja-Starter-VERSION.zip`. A content release is not marked as the latest app release. If an asset of that name already exists, the workflow downloads and checks it; it never overwrites it.
4. Downloads the actual remote asset. Its byte size and whole-file SHA-256 must match the prepared ZIP, and GitHub's asset metadata and reported digest must agree. Only then is the release published.
5. Creates `delivery/content-raja-VERSION` and opens a reviewable PR. The only committed paths are `content/catalog-v2.json` and `content/deliveries/content-raja-VERSION.json`. It verifies that the legacy catalog was not changed. Images and ZIPs are never committed to Git history. The PR contains the URL, complete ZIP checksum, byte size, stable IDs, lesson versions, minimum app version, source commit and retention date.
6. Retains the proposal, diff, verification metadata and ZIP as a temporary Actions artifact for 30 days. This artifact retention is separate from the release asset's review date.

The workflow does **not** merge its PR or write directly to the default branch. The published release can exist before the catalog PR is merged. If the default branch changes during preparation, the job stops before pushing the proposed catalog; rerun from the new state. If the review branch already exists, review that branch/PR instead of overwriting it. If repository policy prevents token-created PRs, the job explains the block and leaves the branch available for an ordinary manual PR; it does not bypass the policy.

After reviewing the exact catalog diff, remote verification and source checks, merge the PR. In a compatible same-key app 0.2.0 installation, use **Settings → Check for updates → Download and install**. The repaired app verifies the catalog's minimum app version, exact byte size and complete ZIP hash, and avoids offering already-current lesson versions. A package that needs a later app is shown with an app-update requirement and cannot start downloading. The old app continues reading its separate empty lesson catalog. Actual phone import and playback still need a phone check.

The catalog change leaves `latestApp` alone. Do not advertise an unsigned verification APK or an APK signed by a different key as an installable upgrade.

### If a run stops

A failed build or verification does not change the app's catalog. A failure after release upload can leave an unreferenced draft or release asset. Keep it for review or rerun the same version only when its bytes are identical; do not use `--clobber`, rewrite its tag, or lower lesson versions. The tool checks catalog and delivery history so a retired version cannot be revived or bypassed with an older version.

For a ZIP that is incomplete on the phone, download it again. The importer verifies and stages the package before activation; its error message must not be treated as permission to clear app storage. Keep the learning backup and current app installation.

## Retention and safe retirement

`expiresAt` is a **retention review date**, not an automatic deletion deadline. A release asset stays available while the active catalog references it, even after that date. There is no scheduled cleanup job and no release-delete command in this workflow.

To retire an older delivery:

1. Run the workflow with `operation: retire` and that older version. It proposes removal of references to that exact asset and changes its delivery record to `status: retired`. It preserves a newer version under the same stable pack ID. Any additional catalog reference to the old asset or release blocks retirement until reviewed.
2. Review and merge the retirement PR. This changes no installed lesson media or learning records; it removes the download offer from the catalog.
3. After the retention date has passed, run `operation: check-retirement`. It reads both catalogs from the merged default branch, rechecks the live head, and refuses stale evidence, an active delivery record, unelapsed retention, or remaining asset/release URLs in either catalog. It checks nested fields, query strings, encoded paths and the asset API URL as well as the normal download URL.
4. Only a successful current check makes the asset eligible for a **separate manual deletion**. Immediately before doing so, recheck [catalog-v2.json](https://raw.githubusercontent.com/blsmohamme972-lab/InstaAnki/main/content/catalog-v2.json), the [legacy catalog.json](https://raw.githubusercontent.com/blsmohamme972-lab/InstaAnki/main/content/catalog.json), and any other place where you published that URL. Do not delete while any active catalog references it. Delete only the named retired asset; avoid deleting a release that contains other needed assets. Keep the small retired delivery record in Git so the version cannot later be reused accidentally.

The read-only check never deletes a file and cannot predict later catalog changes. Its report identifies the checked default-branch commit and catalog hash so the manual decision is reviewable. If the repository's default branch or the app's catalog URL changes, update and review this delivery procedure before using it again.

## Local checks without publishing

These commands prepare a review folder only. They make no GitHub writes. Run them in a clean checkout of the reviewed commit so `--source-commit` truthfully identifies the public content being packaged.

```bash
python3 -m pip install 'Pillow==13.0.0'
python3 tools/prepare_existing_media.py --download-sources
python3 tools/check_source_scope.py
python3 -m unittest discover -s tests -p 'test_update_release.py' -v
python3 tools/build_pack.py \
  --pack-id instaanki-starter-shahzad2015-v1 \
  --version 1.2.0 \
  --title 'Raja existing lessons — presentation repair' \
  --output dist/InstaAnki-Raja-Starter-1.2.0.zip
python3 tools/prepare_update_release.py prepare \
  --pack dist/InstaAnki-Raja-Starter-1.2.0.zip \
  --catalog content/catalog-v2.json \
  --legacy-catalog content/catalog.json \
  --output-dir dist/update-release \
  --retention-days 30 \
  --source-commit "$(git rev-parse HEAD)"
```

If you already have the exact reviewed current ZIP, media reproduction also supports `--from-pack PATH`; it extracts and verifies only the expected image outputs. It never extracts code, arbitrary paths or private files.

The release-upload implementation follows GitHub's [release REST API](https://docs.github.com/en/rest/releases/releases), [release asset API](https://docs.github.com/en/rest/releases/assets), and [GitHub CLI upload command](https://cli.github.com/manual/gh_release_upload). The automated tests cover actual source-gate enforcement with isolated synthetic records, archive corruption and scope, immutable versions, complete downloaded-byte verification, and retirement/reference checks. They do not claim an authenticated Actions run or a physical-phone test.
