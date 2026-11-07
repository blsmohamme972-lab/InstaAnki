# InstaAnki Android shell

This is an offline Android application. The APK contains the `web/` interface and the selected distribution's content. A Java `WebView` serves those assets from the reserved, intercepted `https://appassets.androidplatform.net/assets/` origin. Learning state is stored in native SQLite. App-private imported content is stored separately from the executable interface.

## Build

Requires Linux x86_64, Python 3.10+, Java 17 with `jdk.compiler`, and `keytool`. Prepare the SDK once with `python android/bootstrap_sdk.py`, or select an existing SDK using `--sdk-dir /path/to/sdk`.

There are two explicit application profiles. The default remains `legacy`.

| Profile | App label | Application ID | Initial builder version | Bundled lessons |
| --- | --- | --- | --- | --- |
| `legacy` | InstaAnki | `com.instaanki.app` | `0.2.0`, code 3 | Three verified Raja lessons |
| `fresh` | InstaAnki Fresh | `com.instaanki.fresh` | `0.3.0`, code 4 | None |

### Fresh application

The user's explicit fresh-start instruction authorizes the separate `fresh` profile. It installs alongside the original app and does not read, copy or migrate that app's progress or imported packages. It ships the repaired interface and native functionality, one approved Raja publication, and zero installed lessons. The historical production record remains 3/200; no new lessons are produced.

```bash
node tools/build_web.mjs --profile fresh
python android/build_apk.py --profile fresh --web-dir build/fresh-web --unsigned
python android/build_apk.py --profile fresh --web-dir build/fresh-web --key-dir /private/fresh-signing-backup --version-code 5 --version-name 0.3.1
```

The first command stages the reviewed empty distribution and compiles the current learning code into `build/fresh-web`. The unsigned command checks native compilation without a signing key and writes `dist/InstaAnki-Fresh-0.3.0-unsigned.apk`, which cannot be installed. Version 0.3.0/code 4 has been signed and delivered. The signed command shows the next update: it uses the existing backed-up Fresh signing key and writes `dist/InstaAnki-Fresh-0.3.1.apk` with code 5. The private directory must contain `instaanki-fresh-release.p12` (alias `instaanki-fresh`) and `keystore-password.txt`. Its public certificate must match `android/signing-identity-fresh.json`. The builder does not create, replace or recover keys and rejects a signed version code that does not exceed the recorded delivered version.

Fresh preparation calls the shared `prepare_fresh_web` helper, which copies only approved runtime files into a separate directory, writes an empty lesson list and the reviewed distribution marker, and removes cover references. With an explicitly prepared `--web-dir`, the Android builder validates and uses that exact runtime, preserving its compiled learning code. Without that option, it prepares an isolated temporary bundle from canonical `web/` inputs. The fresh source gate requires the exact reviewed empty distribution. The builder rejects any lesson or media reference and disallows `--include-private`. It does not require, download or restore the old lesson media. Canonical lesson JSON and the historical ledger remain unchanged for legacy builds and QA.

The fresh manifest uses explicit `com.instaanki.app` Java class names with the new application ID, and a separate `com.instaanki.fresh.feedback` provider authority. Android auto-backup is disabled. Future fresh-app updates must retain `com.instaanki.fresh`, the pinned fresh certificate and private key, and an increasing version code. Preserve that key's private backup permanently; losing it would prevent an in-place update of this new app too.

### Legacy application

```bash
python android/build_apk.py --profile legacy --key-dir /private/original-signing-backup
```

The optional `--include-private` flag is for a personal legacy APK only. It copies the known `book-cover.jpeg` from `private-content/app-assets/` or `private-content/` to `assets/www/private-content/book-cover.jpeg`. It does not copy other private files. Do not publish personal book material or a personal binary as a public release without checking its content and the user's instruction.

The result is `dist/InstaAnki-0.2.0.apk`. The builder verifies APK signatures, zip alignment, and writes a SHA-256 checksum plus a machine-readable build report. It stages only the active lessons' referenced media. Archived or unfinished media is retained in the workspace but excluded from the app.

Signing fails closed when the original backup is missing or its certificate differs from `android/signing-identity.json`. It never creates a replacement identity for an update. For a compilation-only check without the key, run `python android/build_apk.py --unsigned`; the resulting `-unsigned.apk` cannot be installed as an update. Device playback must still be tested separately.

Future legacy versions must keep package ID `com.instaanki.app`, use its original signing key, and increase `--version-code`. The separate fresh profile is never an automatic fallback for a missing legacy key. Legacy signing files default to the sibling `.instaanki-signing/` directory; fresh signing files default to `.instaanki-fresh-signing/`. Both remain outside the repository. **Back them up privately before this workspace expires. Never commit or publish them.**

Both profiles validate the selected manifest and pinned public certificate before signing. Build reports record the profile, package ID, label, active lesson and media counts, and whether the output is a signed fresh installation, a signed legacy update, or an unsigned compilation artifact. Signature and alignment verification do not establish phone playback or installation; report device checks separately.

## JavaScript bridge

All bridge methods except pickers/export are synchronous. Browser previews should use an equivalent browser store as a development fallback.

```js
AndroidNative.getItem(key);          // Stored string, or null
AndroidNative.setItem(key, json);    // Durable SQLite write
AndroidNative.removeItem(key);
JSON.parse(AndroidNative.getAppInfo());
JSON.parse(AndroidNative.listPacks());
AndroidNative.importZip();          // Android document picker
AndroidNative.exportBackup();       // Android save-document picker
AndroidNative.importBackup();       // Restore a validated backup transactionally
AndroidNative.downloadPack(httpsUrl, sha256); // Download + verify + install a public GitHub content ZIP
AndroidNative.downloadPackVerified(httpsUrl, sha256, sizeBytes); // Also check catalog size before installation
AndroidNative.downloadPackCompatible(httpsUrl, sha256, sizeBytes, minAppVersionCode); // Also enforce the minimum installed app version
AndroidNative.setImmersive(true);   // Feed only; restore system bars for other screens/dialogs
AndroidNative.openExternal(httpsUrl);
```

Package results have the shape `{ packId, baseUrl, manifest }`. `baseUrl` is `https://appassets.androidplatform.net/content/<pack-id>/`. After installation, fetch `new URL(manifest.lessonsFile || 'lessons.json', baseUrl)` or read inline `manifest.lessons`.

Events emitted on `window`:

- `instaanki:import-started`
- `instaanki:pack-imported`, with the result object in `event.detail`
- `instaanki:error`, with `{ message }` in `event.detail`
- `instaanki:backup-exported`, with `{ ok: true }`
- `instaanki:backup-imported`, with `{ ok: true, keysRestored }`; reload state from SQLite after this event.
- `instaanki:download-progress`, with `{ receivedBytes, totalBytes, percent }`; unknown totals/percent are `null`.
- `instaanki:background`, when the activity leaves the foreground; audio/video elements are also paused.

Optionally define `window.InstaAnkiBack = () => true` to handle the Android back button. Return `false` to allow WebView history or native exit.

## Content package version 1

Place `manifest.json` at the ZIP root. Use `schemaVersion: 1`, an `id` (or `packId`) of up to 80 letters/numbers/`.`/`_`/`-`, and either inline `lessons` or a `lessonsFile` pointing to JSON (`lessons.json` by default). Metadata paths are relative to that root.

Accepted imported extensions: JSON, JPG/JPEG, PNG, WebP, GIF, AVIF, MP3, M4A, AAC, OGG, Opus, WAV, MP4, WebM, VTT and TXT. HTML, JavaScript, native executables and imported SVG are rejected. Put animation instructions in JSON; trusted built-in SVG rendering belongs in the app code. Limits: 3,000 archive entries, 192 MiB per file, 5 MiB per JSON file and 512 MiB total extracted bytes.

The importer rejects unsafe paths, duplicate names, unsupported schema versions, oversized entries and executable content. Optional `sha256` maps are checked for corruption; they do **not** authenticate a publisher. The update stages files and then swaps the package directory. It never deletes SQLite learning state. The original selected ZIP is not copied into permanent app storage.

## Catalog downloads

`downloadPack(url, sha256)` requires the catalog to supply the complete ZIP's 64-character SHA-256 digest. It follows up to five HTTPS redirects only between the explicit GitHub/release-asset host allowlist, accepts no URL credentials, permits only the default HTTPS port, and rejects fragments and other schemes. It uses connection/read timeouts, a ten-minute overall bound while streaming, and a 512 MiB compressed-download limit. After downloading, it verifies the digest **before** calling the data-only ZIP importer. The temporary download is removed on success or failure.

This first version supports public GitHub release assets. Private GitHub content requires authentication not included in this version; import a local ZIP for personal/private material. A checksum detects changes relative to the selected catalog; it is not a publisher signature. The app must show a package's source and size before invoking download on a user action.

## Backup restore

The file picker accepts a UTF-8 JSON backup, capped at 32 MiB. `format` must be `instaanki-backup-v1`, and `state` must be a nonempty map of at most 5,000 string values with bounded keys/values. The complete document is validated before writing anything. Backed-up keys are restored in one SQLite transaction; unrelated local keys and all downloaded media remain. A failed validation or database write does not partially apply the backup. This restores the snapshot's values for matching keys; it does not merge individual review events inside an application's JSON state.

## Current boundaries

- The APK has no advertising, analytics, account system, or cloud progress sync.
- Native backup export saves learning state and preferences, not large media files.
- It does not yet implement signed OTA web-bundle updates or a native APK updater.
- Android's system WebView must be available and reasonably up to date.
- UI scripts load only from the bundled origin. External source links open in the browser. Remote image/data access is allowed by the UI's content security policy.
- Media responses support byte ranges so native WebView audio seeking does not require downloading a hosted video.

## Official API references

- https://developer.android.com/develop/ui/views/layout/webapps/load-local-content
- https://developer.android.com/reference/android/webkit/WebResourceResponse
- https://developer.android.com/tools/aapt2
- https://developer.android.com/tools/d8
- https://developer.android.com/tools/apksigner
- https://developer.android.com/google/play/app-updates
