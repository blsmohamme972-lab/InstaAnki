#!/usr/bin/env python3
"""Build a signed offline InstaAnki APK with Google's SDK tools (no Gradle required).

The signing material is deliberately kept OUTSIDE this repository. Never commit it.
Use the same key for all future updates to preserve the installed app's identity.
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
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android"
sys.path.insert(0, str(ROOT / "tools"))
from check_source_scope import check_catalog


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


def signing_key(directory: Path) -> tuple[Path, Path]:
    """An update must use the already delivered app's certificate, never a new key."""
    key = directory / "instaanki-release.p12"
    password = directory / "keystore-password.txt"
    if key.exists() != password.exists():
        raise SystemExit("Incomplete signing backup. Restore both the keystore and its password; do not generate a replacement key.")
    if not key.exists():
        raise SystemExit(
            "Original Android signing backup is missing. Restore instaanki-release.p12 and "
            "keystore-password.txt privately. A replacement key cannot update the installed app. "
            "Use --unsigned only for compilation checks; it does not produce an installable update.")
    identity = json.loads((ANDROID / "signing-identity.json").read_text())
    certificate = subprocess.run(
        ["keytool", "-exportcert", "-keystore", str(key), "-alias", "instaanki",
         "-storepass:file", str(password)], check=True, capture_output=True).stdout
    actual = hashlib.sha256(certificate).hexdigest()
    if actual != identity["certificateSha256"]:
        raise SystemExit("Signing certificate differs from the installed InstaAnki identity. Restore the original backup; do not uninstall the app.")
    return key, password


def stage_web_bundle(web_root: Path, destination: Path) -> dict:
    """Copy runtime files and only media referenced by the active collection."""
    from build_pack import collect_media, checked_path, IMAGE_EXTENSIONS
    web_root = web_root.resolve()
    lessons_data = json.loads((web_root / "data/lessons.json").read_text())
    lessons = lessons_data.get("lessons") if isinstance(lessons_data, dict) else lessons_data
    media = collect_media(copy.deepcopy(lessons), web_root)
    for book in json.loads((web_root / "data/books.json").read_text()):
        cover = book.get("coverUrl", "").lstrip("/")
        if cover.startswith("media/"):
            checked_path(cover)
            source = (web_root / cover).resolve()
            if source.suffix.lower() not in IMAGE_EXTENSIONS or not source.is_relative_to(web_root) or not source.is_file():
                raise ValueError("Invalid publication cover media")
            media[cover] = source
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-dir", type=Path, default=Path(os.environ.get("INSTAANKI_SDK_DIR", ROOT.parent / "android-toolchain")))
    parser.add_argument("--web-dir", type=Path, default=ROOT / "web")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "InstaAnki-0.2.0.apk")
    parser.add_argument("--key-dir", type=Path, default=ROOT.parent / ".instaanki-signing")
    parser.add_argument("--version-code", type=int, default=3)
    parser.add_argument("--version-name", default="0.2.0")
    parser.add_argument("--unsigned", action="store_true", help="Compile and align a QA artifact only. This cannot be installed as an update.")
    parser.add_argument("--include-private", action="store_true", help="Include private-content/app-assets/ (book cover only) in this PERSONAL APK.")
    args = parser.parse_args()
    args.web_dir = args.web_dir.resolve()
    if not (args.web_dir / "index.html").is_file():
        raise SystemExit(f"Missing offline entry point: {args.web_dir / 'index.html'}")
    # Validate the exact selected bundle before SDK work, staging or signing.
    # The policy and production ledger always come from this repository.
    try:
        check_catalog(ROOT, args.web_dir)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise SystemExit(f"Source scope check failed: {error}") from error
    if args.version_code <= 2:
        raise SystemExit("An update must use versionCode greater than the delivered version 2.")
    key = password = None
    if not args.unsigned:
        key, password = signing_key(args.key_dir.resolve())
    platform, tools = sdk_locations(args.sdk_dir)
    stage = ROOT / "build" / "android"
    if stage.exists():
        shutil.rmtree(stage)
    for part in ["generated", "classes", "dex", "assets"]:
        (stage / part).mkdir(parents=True, exist_ok=True)
    bundle = stage_web_bundle(args.web_dir, stage / "assets" / "www")
    private_assets = stage_private_cover(stage / "assets/www") if args.include_private else []
    compiled = stage / "resources.zip"
    run([tools / "aapt2", "compile", "--dir", ANDROID / "res", "-o", compiled])
    linked = stage / "resources.apk"
    run([tools / "aapt2", "link", "-o", linked, "-I", platform,
         "--manifest", ANDROID / "AndroidManifest.xml", "--java", stage / "generated",
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
        run(["java", "-jar", tools / "lib" / "apksigner.jar", "sign", "--ks", key, "--ks-key-alias", "instaanki",
             "--ks-pass", "file:" + str(password),
             "--v1-signing-enabled", "true", "--v2-signing-enabled", "true", "--v3-signing-enabled", "true",
             "--v4-signing-enabled", "false", "--out", args.output, aligned])
        run(["java", "-jar", tools / "lib" / "apksigner.jar", "verify", "--verbose", "--print-certs", args.output])
    run([tools / "zipalign", "-c", "-P", "16", "4", args.output])
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(".apk.sha256").write_text(f"{digest}  {args.output.name}\n", encoding="utf-8")
    metadata = {
        "file": args.output.name, "packageName": "com.instaanki.app", "version": args.version_name,
        "versionCode": int(args.version_code), "minSdk": 26, "targetSdk": 35,
        "bytes": args.output.stat().st_size, "sha256": digest, "includesPrivateContent": args.include_private,
        "signed": not args.unsigned, "installableUpdate": not args.unsigned, "bundle": bundle,
        "privateAssets": private_assets,
        "verification": ("Unsigned compilation and alignment checked; NOT installable. " if args.unsigned else "APK signature and alignment verified. ") + "Device/emulator testing must be reported separately.",
    }
    args.output.with_suffix(".apk.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
