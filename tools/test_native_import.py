#!/usr/bin/env python3
"""Run the real data-only ZIP importer tests on a desktop JVM.

The explicitly supplied org.json 20240303 jar must match the pinned artifact.
This runner never downloads dependencies or skips a missing prerequisite.
It requires a Java runtime and either javac or the installed jdk.compiler module;
no Android SDK, APK, old lesson media, or private source content is needed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
JSON_VERSION = "20240303"
JSON_JAR_SHA256 = "3cf6cd6892e32e2b4c1c39e0f52f5248a2f5b37646fdfbb79a66b46b618414ed"
SOURCES = ("android/src/com/instaanki/app/ContentPacks.java",
           "android/tests/ContentPacksTest.java")
TEST_CLASS = "com.instaanki.app.ContentPacksTest"
COMMAND_TIMEOUT_SECONDS = 120


class NativeImportTestError(ValueError):
    pass


def checked_json_jar(path):
    path = Path(path)
    if not path.is_file():
        raise NativeImportTestError(
            f"Missing org.json {JSON_VERSION} jar: {path}. Pass its local path with --json-jar; no tests ran.")
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != JSON_JAR_SHA256:
        raise NativeImportTestError(
            f"org.json {JSON_VERSION} jar SHA-256 mismatch: expected {JSON_JAR_SHA256}, received {actual}. "
            "The unverified jar was not used; no tests ran.")
    return data


def java_commands():
    java = shutil.which("java")
    if not java:
        raise NativeImportTestError("Java is missing from PATH. Install a JDK and rerun this required check; no tests ran.")
    javac = shutil.which("javac")
    if javac:
        return java, [javac]
    # Some JDK installations expose the compiler module without a javac launcher.
    compiler = [java, "-m", "jdk.compiler/com.sun.tools.javac.Main"]
    probe = subprocess.run(compiler + ["-version"], capture_output=True, text=True, timeout=15)
    if probe.returncode:
        raise NativeImportTestError(
            "No usable Java compiler: javac is missing and the installed Java runtime has no usable "
            "jdk.compiler module. Install a JDK and rerun this required check; no tests ran.")
    return java, compiler


def run(json_jar):
    # Validate before executing a compiler, and use only these verified bytes
    # afterward so an external jar replacement cannot change the test dependency.
    dependency = checked_json_jar(json_jar)
    java, compiler = java_commands()
    sources = []
    for relative in SOURCES:
        path = ROOT / relative
        if not path.is_file():
            raise NativeImportTestError(f"Required current source is missing: {relative}; no tests ran.")
        sources.append((path.name, path.read_bytes()))
    with tempfile.TemporaryDirectory(prefix="instaanki-native-import-") as directory:
        temporary = Path(directory)
        classes = temporary / "classes"
        runtime = temporary / "runtime"
        source_directory = temporary / "sources"
        for folder in (classes, runtime, source_directory):
            folder.mkdir()
        pinned_jar = temporary / f"json-{JSON_VERSION}.jar"
        pinned_jar.write_bytes(dependency)
        source_paths = []
        for name, data in sources:
            path = source_directory / name
            path.write_bytes(data)
            source_paths.append(str(path))
        print(f"Verified org.json {JSON_VERSION}: {JSON_JAR_SHA256}", flush=True)
        print("Compiling the current ContentPacks.java and ContentPacksTest.java...", flush=True)
        subprocess.run(compiler + ["-encoding", "UTF-8", "-cp", str(pinned_jar), "-d", str(classes),
                                   *source_paths], cwd=temporary, check=True, timeout=COMMAND_TIMEOUT_SECONDS)
        classpath = os.pathsep.join((str(classes), str(pinned_jar)))
        subprocess.run([java, "-ea", f"-Djava.io.tmpdir={runtime}", "-cp", classpath, TEST_CLASS],
                       cwd=temporary, check=True, timeout=COMMAND_TIMEOUT_SECONDS)
    print("Native importer JVM checks passed; temporary test files were removed.", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-jar", type=Path, required=True,
                        help=f"Local org.json {JSON_VERSION} jar with the pinned SHA-256")
    args = parser.parse_args(argv)
    try:
        run(args.json_jar)
    except subprocess.CalledProcessError as error:
        print(f"Native importer check failed (process exit {error.returncode}); see its output above.", file=sys.stderr)
        return error.returncode if error.returncode > 0 else 1
    except subprocess.TimeoutExpired as error:
        print(f"Native importer check exceeded its {error.timeout}-second process limit and failed.", file=sys.stderr)
        return 1
    except (OSError, NativeImportTestError) as error:
        print(f"Native importer check: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
