#!/usr/bin/env python3
"""Build a signed offline InstaAnki APK with Google's SDK tools (no Gradle required).

The signing material is deliberately kept OUTSIDE this repository. Never commit it.
Legacy updates retain their original identity. The explicitly selected fresh
profile has its own identity and must retain that separate key for future updates.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android"
sys.path.insert(0, str(ROOT / "tools"))
from check_source_scope import check_catalog

PROFILES = {
    "legacy": {"packageName": "com.instaanki.app", "label": "InstaAnki",
               "versionName": "0.2.0", "versionCode": 3, "minimumVersionCode": 3,
               "manifest": "AndroidManifest.xml", "identity": "signing-identity.json",
               "keyFile": "instaanki-release.p12", "keyAlias": "instaanki",
               "keyDirectory": ".instaanki-signing", "outputPrefix": "InstaAnki"},
    "fresh": {"packageName": "com.instaanki.fresh", "label": "InstaAnki Fresh",
              "versionName": "0.3.2", "versionCode": 6, "minimumVersionCode": 4,
              "manifest": "AndroidManifest.fresh.xml", "identity": "signing-identity-fresh.json",
              "keyFile": "instaanki-fresh-release.p12", "keyAlias": "instaanki-fresh",
              "keyDirectory": ".instaanki-fresh-signing", "outputPrefix": "InstaAnki-Fresh"},
}


def profile_manifest(profile: str) -> Path:
    """Check the fixed application identity before selecting keys or SDK work."""
    config = PROFILES[profile]
    path = ANDROID / config["manifest"]
    document = ET.parse(path).getroot()
    app = document.find("application")
    android = "{http://schemas.android.com/apk/res/android}"
    if document.get("package") != config["packageName"] or app is None or app.get(android + "label") != config["label"]:
        raise SystemExit("The selected manifest does not match the approved application identity.")
    provider, activity = app.find("provider"), app.find("activity")
    def full_name(element):
        value = element.get(android + "name", "") if element is not None else ""
        return config["packageName"] + value if value.startswith(".") else value
    if (full_name(activity) != "com.instaanki.app.MainActivity"
            or full_name(provider) != "com.instaanki.app.FeedbackProvider"
            or provider.get(android + "authorities") != config["packageName"] + ".feedback"):
        raise SystemExit("The selected manifest has an invalid native component or feedback authority.")
    return path


def run(args: list[str | Path]) -> None:
    subprocess.run([str(x) for x in args], check=True)


def sdk_locations(sdk: Path) -> tuple[Path, Path]:
    platform_candidates = [sdk / "platforms" / "android-35" / "android.jar"]
    for p in platform_candidates:
        if p.is_file():
            platform = p
            break
    else:
        raise SystemExit(f"Android API 35 platform missing in {sdk}. Run android/bootstrap_sdk.py first.")
    for folder in [sdk / "build-tools" / "35.0.0", sdk / "build-tools" / "android-15"]:
        if (folder / "aapt2").is_file():
            return platform, folder
    raise SystemExit(f"Android build tools 35.0.0 missing in {sdk}.")


def signing_key(directory: Path, profile: str = "legacy", version_code: int | None = None) -> tuple[Path, Path]:
    """Use only a pre-existing, pinned profile key; this function never creates one."""
    config = PROFILES[profile]
    key = directory / config["keyFile"]
    password = directory / "keystore-password.txt"
    if key.exists() != password.exists():
        raise SystemExit("Incomplete signing backup. Restore both the keystore and its password; do not generate a replacement key.")
    if not key.exists():
        if profile == "fresh":
            raise SystemExit(
                "Fresh Android signing backup is missing. Prepare and durably back up "
                "instaanki-fresh-release.p12 and keystore-password.txt privately, then register "
                "its public certificate. The builder never generates or substitutes a signing key. "
                "Use --profile fresh --unsigned only for compilation checks.")
        raise SystemExit(
            "Original Android signing backup is missing. Restore instaanki-release.p12 and "
            "keystore-password.txt privately. A replacement key cannot update the installed app. "
            "Use --unsigned only for compilation checks; it does not produce an installable update.")
    try:
        identity = json.loads((ANDROID / config["identity"]).read_text())
    except (OSError, ValueError) as error:
        raise SystemExit("The selected app's public signing identity is missing or unreadable. Register the verified backup's certificate first.") from error
    expected = identity.get("certificateSha256")
    if (identity.get("schemaVersion") != 1 or identity.get("packageName") != config["packageName"]
            or not isinstance(expected, str) or len(expected) != 64
            or any(character not in "0123456789abcdef" for character in expected)):
        raise SystemExit("The public signing identity does not match the selected application profile.")
    delivered = identity.get("lastDeliveredVersionCode", 0)
    if type(delivered) is not int or delivered < 0:
        raise SystemExit("The signing identity has an invalid delivered version code.")
    if version_code is not None and version_code <= delivered:
        raise SystemExit("A signed build must increase versionCode beyond the delivered version for this app identity.")
    certificate = subprocess.run(
        ["keytool", "-exportcert", "-keystore", str(key), "-alias", config["keyAlias"],
         "-storepass:file", str(password)], check=True, capture_output=True).stdout
    actual = hashlib.sha256(certificate).hexdigest()
    if actual != identity["certificateSha256"]:
        if profile == "fresh":
            raise SystemExit("Signing certificate differs from the pinned InstaAnki Fresh identity. Restore its private backup; never regenerate its key.")
        raise SystemExit("Signing certificate differs from the installed InstaAnki identity. Restore the original backup; do not uninstall the app.")
    return key, password


def stage_web_bundle(web_root: Path, destination: Path, profile: str = "legacy") -> dict:
    """Copy runtime files and only media referenced by the active collection."""
    from build_pack import collect_media, checked_path, IMAGE_EXTENSIONS
    web_root = web_root.resolve()
    lessons_data = json.loads((web_root / "data/lessons.json").read_text())
    lessons = lessons_data.get("lessons") if isinstance(lessons_data, dict) else lessons_data
    if not isinstance(lessons, list) or (profile == "fresh" and lessons):
        raise ValueError("The fresh application requires an empty lesson collection" if profile == "fresh" else "Active lessons must be a list")
    media = collect_media(copy.deepcopy(lessons), web_root)
    for book in json.loads((web_root / "data/books.json").read_text()):
        cover = book.get("coverUrl", "").lstrip("/")
        if cover.startswith("media/"):
            checked_path(cover)
            source = (web_root / cover).resolve()
            if source.suffix.lower() not in IMAGE_EXTENSIONS or not source.is_relative_to(web_root) or not source.is_file():
                raise ValueError("Invalid publication cover media")
            media[cover] = source
    if profile == "fresh" and media:
        raise ValueError("The fresh application must not bundle old lesson or cover media")
    for source in sorted(web_root.rglob("*")):
        relative = source.relative_to(web_root)
        if relative.parts[0] in {"media", "private-content"} or not source.is_file():
            continue
        if source.name == ".DS_Store" or source.name.endswith((".map", ".entry.js")):
            continue
        if not source.resolve().is_relative_to(web_root):
            raise ValueError(f"Runtime file escapes selected web root: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for name, source in sorted(media.items()):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return {"activeLessons": len(lessons), "mediaFiles": len(media),
            "mediaBytes": sum(path.stat().st_size for path in media.values())}


def stage_private_cover(destination: Path) -> list[str]:
    """Only the known authorized cover belongs in a personal APK."""
    candidates = [ROOT / "private-content/app-assets/book-cover.jpeg",
                  ROOT / "private-content/book-cover.jpeg"]
    source = next((path for path in candidates if path.is_file() and not path.is_symlink()), None)
    if source is None:
        raise SystemExit("Personal cover is missing. Restore book-cover.jpeg privately or omit --include-private; no other private files are copied.")
    target = destination / "private-content/book-cover.jpeg"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return ["private-content/book-cover.jpeg"]


def build_validated(args, config, source_scope) -> None:
    """Build only after the selected distribution's source check succeeded."""
    if args.profile == "fresh" and source_scope.get("activeLessons") != 0:
        raise SystemExit("The approved fresh application must contain zero active lessons.")
    manifest = profile_manifest(args.profile)
    key = password = None
    if not args.unsigned:
        key, password = signing_key(args.key_dir.resolve(), args.profile, args.version_code)
    platform, tools = sdk_locations(args.sdk_dir)
    stage = ROOT / "build" / ("android-fresh" if args.profile == "fresh" else "android")
    if stage.exists():
        shutil.rmtree(stage)
    for part in ["generated", "classes", "dex", "assets"]:
        (stage / part).mkdir(parents=True, exist_ok=True)
    bundle = stage_web_bundle(args.web_dir, stage / "assets" / "www", args.profile)
    private_assets = stage_private_cover(stage / "assets/www") if args.include_private else []
    compiled = stage / "resources.zip"
    run([tools / "aapt2", "compile", "--dir", ANDROID / "res", "-o", compiled])
    linked = stage / "resources.apk"
    run([tools / "aapt2", "link", "-o", linked, "-I", platform,
         "--manifest", manifest, "--java", stage / "generated",
         "--version-code", args.version_code, "--version-name", args.version_name,
         "-A", stage / "assets", "-0", "mp3", "-0", "m4a", "-0", "mp4", "-0", "ogg", "-0", "opus", "-0", "wav", compiled])
    sources = sorted((ANDROID / "src").rglob("*.java")) + sorted((stage / "generated").rglob("*.java"))
    # Keep Java 8 bytecode on trimmed JREs without ct.sym. Android's stub
    # LambdaMetafactory cannot be used as javac's boot classpath; D8 handles
    # desugaring against the Android library below.
    run(["java", "-m", "jdk.compiler/com.sun.tools.javac.Main", "-encoding", "UTF-8", "-source", "8", "-target", "8", "-Xlint:-options",
         "-classpath", platform, "-d", stage / "classes", *sources])
    classes_jar = stage / "classes.jar"
    with zipfile.ZipFile(classes_jar, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((stage / "classes").rglob("*.class")):
            archive.write(path, path.relative_to(stage / "classes").as_posix())
    run(["java", "-cp", tools / "lib" / "d8.jar", "com.android.tools.r8.D8", "--release", "--min-api", "26",
         "--lib", platform, "--output", stage / "dex", classes_jar])
    unsigned = stage / "unsigned.apk"
    shutil.copyfile(linked, unsigned)
    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as archive:
        for dex in sorted((stage / "dex").glob("*.dex")):
            archive.write(dex, dex.name)
    aligned = stage / "aligned.apk"
    run([tools / "zipalign", "-f", "-P", "16", "4", unsigned, aligned])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.unsigned:
        # The filename makes the limitation visible even outside its sidecar.
        if not args.output.stem.endswith("-unsigned"):
            args.output = args.output.with_name(args.output.stem + "-unsigned.apk")
        shutil.copyfile(aligned, args.output)
    else:
        run(["java", "-jar", tools / "lib" / "apksigner.jar", "sign", "--ks", key, "--ks-key-alias", config["keyAlias"],
             "--ks-pass", "file:" + str(password),
             "--v1-signing-enabled", "true", "--v2-signing-enabled", "true", "--v3-signing-enabled", "true",
             "--v4-signing-enabled", "false", "--out", args.output, aligned])
        run(["java", "-jar", tools / "lib" / "apksigner.jar", "verify", "--verbose", "--print-certs", args.output])
    run([tools / "zipalign", "-c", "-P", "16", "4", args.output])
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(".apk.sha256").write_text(f"{digest}  {args.output.name}\n", encoding="utf-8")
    metadata = {
        "file": args.output.name, "packageName": config["packageName"], "applicationLabel": config["label"],
        "buildProfile": args.profile, "version": args.version_name,
        "versionCode": int(args.version_code), "minSdk": 26, "targetSdk": 35,
        "bytes": args.output.stat().st_size, "sha256": digest, "includesPrivateContent": args.include_private,
        "signed": not args.unsigned, "installableUpdate": not args.unsigned and args.profile == "legacy",
        "installableFreshApp": not args.unsigned and args.profile == "fresh", "bundle": bundle,
        "sourceScope": source_scope,
        "privateAssets": private_assets,
        "verification": ("Unsigned compilation and alignment checked; NOT installable. " if args.unsigned else "APK signature and alignment verified. ") + "Device/emulator testing must be reported separately.",
    }
    args.output.with_suffix(".apk.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILES), default="legacy",
                        help="Legacy keeps its original app/key; fresh selects the explicitly approved empty new app.")
    parser.add_argument("--sdk-dir", type=Path, default=Path(os.environ.get("INSTAANKI_SDK_DIR", ROOT.parent / "android-toolchain")))
    parser.add_argument("--web-dir", type=Path, default=ROOT / "web")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--key-dir", type=Path)
    parser.add_argument("--version-code", type=int)
    parser.add_argument("--version-name")
    parser.add_argument("--unsigned", action="store_true", help="Compile and align a QA artifact only. This cannot be installed.")
    parser.add_argument("--include-private", action="store_true", help="Legacy PERSONAL APK only: include the known private book cover.")
    args = parser.parse_args()
    config = PROFILES[args.profile]
    args.version_code = config["versionCode"] if args.version_code is None else args.version_code
    args.version_name = config["versionName"] if args.version_name is None else args.version_name
    args.key_dir = args.key_dir or ROOT.parent / config["keyDirectory"]
    args.output = args.output or ROOT / "dist" / f"{config['outputPrefix']}-{args.version_name}.apk"
    args.web_dir = args.web_dir.resolve()
    if not (args.web_dir / "index.html").is_file():
        raise SystemExit(f"Missing offline entry point: {args.web_dir / 'index.html'}")
    if args.version_code < config["minimumVersionCode"]:
        raise SystemExit(f"The {args.profile} profile requires versionCode {config['minimumVersionCode']} or later.")
    if args.profile == "fresh" and args.include_private:
        raise SystemExit("The fresh application ships no private content or old media. Omit --include-private.")
    if args.profile == "fresh":
        marker = args.web_dir / "data/distribution.json"
        if marker.exists() or marker.is_symlink():
            # A compiled fresh web build already carries its reviewed marker.
            # Validate it directly so its compiled learning.js is preserved.
            try:
                source_scope = check_catalog(ROOT, args.web_dir, profile="fresh")
            except (OSError, ValueError, TypeError, KeyError) as error:
                raise SystemExit(f"Source scope check failed: {error}") from error
            build_validated(args, config, source_scope)
            return
        from check_source_scope import prepare_fresh_web
        # The isolated input is discarded after the APK is built. Canonical
        # legacy lessons and their historical ledger remain untouched.
        with tempfile.TemporaryDirectory(prefix="instaanki-fresh-web-") as temporary:
            selected = Path(temporary) / "www"
            try:
                source_scope = prepare_fresh_web(ROOT, args.web_dir, selected)
            except (OSError, ValueError, TypeError, KeyError) as error:
                raise SystemExit(f"Source scope check failed: {error}") from error
            args.web_dir = selected
            build_validated(args, config, source_scope)
    else:
        # The default keeps the original nonempty source check and key guard.
        try:
            source_scope = check_catalog(ROOT, args.web_dir)
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise SystemExit(f"Source scope check failed: {error}") from error
        build_validated(args, config, source_scope)


if __name__ == "__main__":
    main()
