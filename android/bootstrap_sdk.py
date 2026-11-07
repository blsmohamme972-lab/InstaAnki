#!/usr/bin/env python3
"""Fetch the official, pinned Android API 35 toolchain for Linux x86_64.

Read https://developer.android.com/studio/terms before using the Android SDK.
This script does not install a system service or modify global environment variables.
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import urllib.request
import zipfile

PACKAGES = [
    ("platform-35_r02.zip", "0988cacad01b38a18a47bac14a0695f246bc76c1b06c0eeb8eb0dc825ab0c8e0", "platforms"),
    ("build-tools_r35_linux.zip", "bd3a4966912eb8b30ed0d00b0cda6b6543b949d5ffe00bea54c04c81e1561d88", "build-tools"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-dir", type=Path, default=Path(__file__).resolve().parents[2] / "android-toolchain")
    args = parser.parse_args()
    args.sdk_dir.mkdir(parents=True, exist_ok=True)
    for name, digest, destination in PACKAGES:
        archive = args.sdk_dir / name
        if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            print(f"Downloading official Android SDK package {name}…", flush=True)
            with urllib.request.urlopen("https://dl.google.com/android/repository/" + name, timeout=90) as response:
                with archive.open("wb") as out:
                    while chunk := response.read(1024 * 1024):
                        out.write(chunk)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            raise SystemExit("Android SDK archive checksum verification failed.")
        target = args.sdk_dir / destination
        with zipfile.ZipFile(archive) as zipped:
            for entry in zipped.infolist():
                path = target / entry.filename
                if not path.resolve().is_relative_to(target.resolve()):
                    raise SystemExit("Unsafe SDK archive path.")
                zipped.extract(entry, target)
                if not entry.is_dir():
                    path.chmod((entry.external_attr >> 16) or 0o644)
    print(f"Android toolchain ready: {args.sdk_dir}")


if __name__ == "__main__":
    main()
