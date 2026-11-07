# InstaAnki Android shell

This is a real offline Android application, not an online URL wrapper. The APK contains the `web/` interface and media. A Java `WebView` serves those assets from the reserved, intercepted `https://appassets.androidplatform.net/assets/` origin. Learning state is stored in native SQLite. App-private imported content is stored separately from the executable interface.

## Build

Requires Linux x86_64, Python 3.10+, Java 17 with `jdk.compiler`, and `keytool`.

```bash
python android/bootstrap_sdk.py
python android/build_apk.py --include-private
```

`--include-private` is for the user's personal APK only. It copies only `private-content/app-assets/` (currently the book cover) to `/assets/private-content/`. It does not include the extracted source questions, the original PDF, or signing secrets. Do not publish personal book material or a personal binary as a public release without checking its content and the user's instruction.

The result is `dist/InstaAnki-0.2.0.apk`. The builder verifies APK signatures, zip alignment, and writes a SHA-256 checksum plus a machine-readable build report. It stages only the active lessons' referenced media. Archived or unfinished media is retained in the workspace but excluded from the app.

Signing fails closed when the original backup is missing or its certificate differs from `android/signing-identity.json`. It never creates a replacement identity for an update. For a compilation-only check without the key, run `python android/build_apk.py --unsigned`; the resulting `-unsigned.apk` cannot be installed as an update. Device playback must still be tested separately.

Future versions must keep package ID `com.instaanki.app`, use the same signing key, and increase `--version-code`. Signing files live in the sibling `.instaanki-signing/` directory, outside this repository. **Back them up privately before this workspace expires. Never commit or publish them.** To use an existing identity, provide `--key-dir /private/signing/folder`.

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
