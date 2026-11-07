# InstaAnki Fresh 0.3.0

## What the user requested

On 2026-11-07, after reviewing the original APK, the user explicitly requested: “No need for old videos! Start fresh.” Earlier instructions paused all new lesson, narration, image and video production. This release therefore delivers an empty app with the existing repairs and the same approved source. It does not produce or migrate lessons.

| Item | Fresh installation |
| --- | --- |
| Launcher name | InstaAnki Fresh |
| Application ID | `com.instaanki.fresh` |
| Initial version | `0.3.0`, version code `4` |
| Installed lessons on first launch | `0` |
| Bundled lesson or cover media | None |
| Approved publication | Shahzad G. Raja, *200 Practice Questions in Cardiothoracic Surgery* (2015) |
| Historical production | `3/200`: Q5, Q54 and Q182 |
| New lesson production | Paused |

The original application has ID `com.instaanki.app`. The distinct Fresh application ID, feedback provider authority and private storage let both apps coexist. Fresh does not uninstall the original, clear its storage, restore its backup, or copy its imported packages. Android automatic backup is disabled for this distribution.

## Why the old APK was not enough for an in-place update

The supplied 0.1.1 APK was a valid, signed Android application. A distributed APK contains the public signing certificate, not the private signing key. Android requires a compatible signing identity when updating an existing installed application. The original private key was not available, so a normally signed in-place update could not be produced from that APK alone.

The explicit fresh-start instruction resolves that dependency by authorizing a separate application identity and one new signing key. **The fresh build does not need the old APK or old videos.** Future Fresh updates must reuse the Fresh key. Official background: [Android app signing](https://developer.android.com/studio/publish/app-signing).

## Build without old content

```bash
npm ci
npm run build:web:fresh
python3 -m unittest discover -s tests -p 'test_fresh_distribution.py' -v
python3 -m unittest discover -s tests -p 'test_android_fresh_profile.py' -v
npx playwright install --with-deps chromium --only-shell
npm run test:fresh
python3 android/bootstrap_sdk.py
python3 android/build_apk.py --profile fresh --web-dir build/fresh-web --unsigned
```

This sequence verifies a clean checkout and produces an unsigned compilation artifact. The delivered 0.3.0 APK was signed using a restore of the private Fresh backup. For a later installable update, build the compiled web bundle and package it with a higher version code:

```bash
npm run build:apk:fresh -- --key-dir /private/fresh-signing-backup --version-code 5 --version-name 0.3.1
```

Supply `--sdk-dir /path/to/sdk` when using an existing SDK. Signing requires Java with `keytool`; it never creates a new key automatically. The signed output is named for the selected version and has a checksum and machine-readable build report. Version code 4 is now recorded as delivered; it cannot be reused for a later signed update. The installed app reads its actual Android package version, including when the initial Fresh distribution marker retains the original 0.3.0 metadata.

The shared `prepare_fresh_web` helper copies an explicit list of runtime files, writes `data/lessons.json` as an empty array, omits cover references, and adds the reviewed distribution marker. It neither reads nor restores old lesson media. A second check validates the actual staged files before packaging. Extra media, private assets, an incorrect book, an altered marker, unpaused production and nonempty lesson lists are rejected. `--include-private` is unavailable for Fresh.

The canonical three-lesson catalog and historical ledger remain unchanged in the repository for legacy use and regression checks. Normal lesson-package validation still rejects empty packages. The constrained Fresh distribution is not a general source-policy bypass.

## Signing backup and later versions

The private backup is named `InstaAnki-Fresh-Signing-Backup.zip` and was saved durably before APK delivery. It contains:

- `instaanki-fresh-release.p12`, alias `instaanki-fresh`;
- `keystore-password.txt`;
- a copy of the public signing identity;
- private-backup instructions.

Keep this backup private and durable. It must never be committed to Git, included in an APK or content pack, or attached to a public issue or release. The public certificate metadata in `android/signing-identity-fresh.json` is safe to keep in the repository. The backup was restored into a separate private directory and its public certificate was compared with the original before the release build.

For every later Fresh update, retain `com.instaanki.fresh`, restore the same private key, and select a version code greater than the last delivered code. After delivery, record `lastDeliveredVersionCode` in the public identity and keep the release verification record current. The builder rejects certificates that do not match the pinned identity and versions that do not advance beyond a recorded delivered version. An unsigned compilation artifact is never an installable deliverable.

The original app retains its own signing guard and certificate. Selecting Fresh is deliberate; it is not an automatic fallback when a legacy build cannot find its original key.

## Content and application updates

Fresh uses the existing live `content/catalog-v2.json`. It does not depend on an unmerged branch URL or a new catalog endpoint. The current catalog has no downloadable lesson offers.

For a future source-reviewed content offer, include the usual package ID, version, HTTPS URL, exact ZIP size, SHA-256 and explicit minimum app version, and add:

```json
{
  "targetPackageNames": ["com.instaanki.fresh"]
}
```

The UI checks this audience before showing an automatic prompt, listing a package, or starting its download. A legacy or unscoped package cannot silently repopulate the empty Fresh app. The user may deliberately import a valid original-book ZIP from the device; import does not create new source evidence or authorize production.

For an APK offer, `latestApp.packageName` must equal `com.instaanki.fresh`. A matching entry in `catalog.apps` can also be used, as a list or a map keyed by application ID. The UI selects a higher integer version code with an HTTPS URL and checks the identity again before opening the update. A missing-package legacy notice is never offered to Fresh. Android handles APK installation; the app does not silently install executable updates.

The reviewed temporary-release workflow remains available for data-only lesson packages. Do not delete a release while a live catalog references its asset. New lesson production remains paused until the user explicitly changes that instruction.

## Verification boundaries

The Fresh tests cover an actual staged empty web bundle, phone and desktop layouts, no old-media requests, zero learning enrollment, empty review/saved states, the sole approved publication, and application-specific update filtering. Builder tests verify separate manifest/component identities, zero-content staging, signing-key guards and rejection of private-content inclusion. The CI Fresh job performs these checks without restoring old lesson media.

The delivered APK must additionally pass signature and alignment verification, an Android manifest inspection and a ZIP inventory check for zero lesson media and no signing secrets. Browser, JVM and APK checks do not establish a successful installation or playback on the user's physical phone. Report those checks separately and accurately.
