"""Failure-path checks for the required JVM runner; the real Java suite runs separately."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import test_native_import as runner


class NativeImportRunnerTests(unittest.TestCase):
    def invoke(self, jar):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = runner.main(["--json-jar", str(jar)])
        return result, output.getvalue(), errors.getvalue()

    def test_missing_or_unverified_jar_fails_before_any_java_process(self):
        with tempfile.TemporaryDirectory() as directory:
            jar = Path(directory) / "json.jar"
            for content, expected in ((None, "Missing org.json"), (b"unverified jar", "SHA-256 mismatch")):
                if content is not None:
                    jar.write_bytes(content)
                with self.subTest(content=content), patch.object(runner, "java_commands") as commands:
                    result, output, errors = self.invoke(jar)
                self.assertEqual(result, 2)
                self.assertIn(expected, errors)
                self.assertNotIn("checks passed", output)
                commands.assert_not_called()

    def test_missing_runtime_or_compiler_is_an_error_not_a_skipped_test(self):
        # Only this isolated adapter test substitutes dependency bytes. The CLI
        # has no override for the pinned artifact and never creates a fake jar.
        with patch.object(runner, "checked_json_jar", return_value=b"synthetic test dependency"):
            with patch.object(runner.shutil, "which", return_value=None), patch.object(runner.subprocess, "run") as process:
                result, output, errors = self.invoke("synthetic.jar")
            self.assertEqual(result, 2)
            self.assertIn("Java is missing", errors)
            self.assertNotIn("checks passed", output)
            process.assert_not_called()
            with patch.object(runner.shutil, "which", side_effect=lambda name: "/installed/java" if name == "java" else None), \
                    patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)) as process:
                result, output, errors = self.invoke("synthetic.jar")
            self.assertEqual(result, 2)
            self.assertIn("No usable Java compiler", errors)
            self.assertNotIn("checks passed", output)
            self.assertEqual(process.call_count, 1)
            self.assertIn("-version", process.call_args.args[0])

    def test_installed_compiler_module_is_available_without_a_javac_launcher(self):
        with patch.object(runner.shutil, "which", side_effect=lambda name: "/installed/java" if name == "java" else None), \
                patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            java, compiler = runner.java_commands()
        self.assertEqual(java, "/installed/java")
        self.assertEqual(compiler, [java, "-m", "jdk.compiler/com.sun.tools.javac.Main"])

    def test_compilation_assertion_and_timeout_failures_propagate_and_clean_temporary_files(self):
        scenarios = (
            ([subprocess.CalledProcessError(7, ["javac"])], 7, 1),
            ([subprocess.CompletedProcess([], 0), subprocess.CalledProcessError(9, ["java"])], 9, 2),
            ([subprocess.TimeoutExpired(["javac"], 120)], 1, 1),
        )
        for results, expected_exit, expected_calls in scenarios:
            with self.subTest(expected_exit=expected_exit), \
                    patch.object(runner, "checked_json_jar", return_value=b"synthetic test dependency"), \
                    patch.object(runner, "java_commands", return_value=("/installed/java", ["/installed/javac"])), \
                    patch.object(runner.subprocess, "run", side_effect=results) as process:
                result, output, errors = self.invoke("synthetic.jar")
            self.assertEqual(result, expected_exit)
            self.assertTrue(errors)
            self.assertNotIn("checks passed", output)
            self.assertEqual(process.call_count, expected_calls)
            temporary = Path(process.call_args_list[0].kwargs["cwd"])
            self.assertFalse(temporary.exists())
            if expected_calls == 2:
                invocation = process.call_args_list[1].args[0]
                self.assertEqual(invocation[-1], "com.instaanki.app.ContentPacksTest")
                self.assertIn(f"-Djava.io.tmpdir={temporary / 'runtime'}", invocation)


if __name__ == "__main__":
    unittest.main()
