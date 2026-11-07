#!/usr/bin/env python3
"""Build a signed offline InstaAnki APK with Google's SDK tools (no Gradle required).

The signing material is deliberately kept OUTSIDE this repository. Never commit it.
Use the same key for all future updates to preserve the installed app's identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android"


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
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    key = directory / "instaanki-release.p12"
    password = directory / "keystore-password.txt"
    if key.exists() != password.exists():
        raise SystemExit("Incomplete signing backup. Restore both the keystore and its password; do not generate a replacement key.")
    if not key.exists():
        password.write_text(secrets.token_urlsafe(36) + "\n", encoding="utf-8")
        password.chmod(0o600)
        run(["keytool", "-genkeypair", "-noprompt", "-keystore", key, "-storetype", "PKCS12",
             "-alias", "instaanki", "-keyalg", "RSA", "-keysize", "3072", "-validity", "12000",
             "-dname", "CN=InstaAnki Personal App, OU=Personal Learning, O=InstaAnki",
             "-storepass:file", password, "-keypass:file", password])
        key.chmod(0o600)
        (directory / "README.txt").write_text(
            "PRIVATE AND ESSENTIAL: Keep this directory in a private backup.\n"
            "It is the signing identity for Android package com.instaanki.app.\n"
            "Keystore: instaanki-release.p12 (PKCS12)\nAlias: instaanki\n"
            "The password file is used for both store and key.\n"
            "Every future APK must be signed with this key and use a higher versionCode.\n"
            "Never upload these files to a public Git repository or release.\n", encoding="utf-8")
    return key, password


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-dir", type=Path, default=Path(os.environ.get("INSTAANKI_SDK_DIR", ROOT.parent / "android-toolchain")))
    parser.add_argument("--web-dir", type=Path, default=ROOT / "web")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "InstaAnki-0.1.0.apk")
    parser.add_argument("--key-dir", type=Path, default=ROOT.parent / ".instaanki-signing")
    parser.add_argument("--version-code", default="1")
    parser.add_argument("--version-name", default="0.1.0")
    parser.add_argument("--include-private", action="store_true", help="Include private-content/app-assets/ (book cover only) in this PERSONAL APK.")
    args = parser.parse_args()
    if not (args.web_dir / "index.html").is_file():
        raise SystemExit(f"Missing offline entry point: {args.web_dir / 'index.html'}")
    platform, tools = sdk_locations(args.sdk_dir)
    stage = ROOT / "build" / "android"
    if stage.exists():
        shutil.rmtree(stage)
    for part in ["generated", "classes", "dex", "assets"]:
        (stage / part).mkdir(parents=True, exist_ok=True)
    shutil.copytree(args.web_dir, stage / "assets" / "www", ignore=shutil.ignore_patterns(".DS_Store", "*.map", "*.entry.js"))
    if args.include_private and (ROOT / "private-content" / "app-assets").is_dir():
        shutil.copytree(ROOT / "private-content" / "app-assets", stage / "assets" / "www" / "private-content", dirs_exist_ok=True)
    compiled = stage / "resources.zip"
    run([tools / "aapt2", "compile", "--dir", ANDROID / "res", "-o", compiled])
    linked = stage / "resources.apk"
    run([tools / "aapt2", "link", "-o", linked, "-I", platform,
         "--manifest", ANDROID / "AndroidManifest.xml", "--java", stage / "generated",
         "--version-code", args.version_code, "--version-name", args.version_name,
         "-A", stage / "assets", "-0", "mp3", "-0", "m4a", "-0", "mp4", "-0", "ogg", "-0", "opus", "-0", "wav", compiled])
    sources = sorted((ANDROID / "src").rglob("*.java")) + sorted((stage / "generated").rglob("*.java"))
    run(["java", "-m", "jdk.compiler/com.sun.tools.javac.Main", "-encoding", "UTF-8", "--release", "8",
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
    key, password = signing_key(args.key_dir.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
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
        "verification": "APK signature and alignment verified. Device/emulator testing must be reported separately.",
    }
    args.output.with_suffix(".apk.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
