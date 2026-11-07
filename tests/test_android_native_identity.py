"""Run the actual bridge method with small Android package-manager test doubles."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
A = "{http://schemas.android.com/apk/res/android}"


class AndroidNativeIdentityTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("java"), "Java is required for native bridge execution")
    def test_app_info_uses_installed_application_label_package_and_version(self):
        source = (ROOT / "android/src/com/instaanki/app/MainActivity.java").read_text()
        start = source.index("@JavascriptInterface public String getAppInfo()")
        end = source.index("@JavascriptInterface public void importZip()", start)
        method = source[start:end]
        cases = []
        for filename in ("AndroidManifest.xml", "AndroidManifest.fresh.xml"):
            manifest = ET.parse(ROOT / "android" / filename).getroot()
            cases.append((manifest.get("package"), manifest.find("application").get(A + "label"),
                          manifest.get(A + "versionName"), manifest.get(A + "versionCode")))
        # A changed installed label must be read from PackageManager too.
        cases.append(("com.instaanki.fresh", "Custom installed label", "0.3.1", "5"))
        invocation = "\n".join('check("%s", "%s", "%s", %s);' % case for case in cases)
        fixture = r'''
import java.util.LinkedHashMap;
import java.util.Map;
public final class AppInfoHarness {
    @interface JavascriptInterface {}
    static final class Build { static final class VERSION { static final String RELEASE = "fixture"; } }
    static final class PackageInfo { String versionName; int versionCode; }
    static final class PackageManager {
        PackageInfo info = new PackageInfo(); String expectedPackage; String label;
        PackageInfo getPackageInfo(String name, int flags) {
            if (!expectedPackage.equals(name)) throw new IllegalArgumentException("Wrong package requested");
            return info;
        }
    }
    final class ApplicationInfo {
        CharSequence loadLabel(PackageManager manager) {
            if (manager != packages) throw new IllegalArgumentException("Wrong package manager");
            return manager.label;
        }
    }
    static final class JSONObject {
        static JSONObject latest;
        final Map<String, Object> values = new LinkedHashMap<>();
        JSONObject() { latest = this; }
        JSONObject put(String key, Object value) { values.put(key, value); return this; }
        public String toString() { return "bridge-result"; }
    }
    final PackageManager packages = new PackageManager();
    PackageManager getPackageManager() { return packages; }
    String getPackageName() { return packages.expectedPackage; }
    ApplicationInfo getApplicationInfo() { return new ApplicationInfo(); }
    final class NativeBridge { METHOD }
    static void require(boolean value) { if (!value) throw new AssertionError("Incorrect app identity"); }
    static void check(String name, String label, String version, int code) {
        AppInfoHarness app = new AppInfoHarness();
        app.packages.expectedPackage = name; app.packages.label = label;
        app.packages.info.versionName = version; app.packages.info.versionCode = code;
        require("bridge-result".equals(app.new NativeBridge().getAppInfo()));
        Map<String, Object> actual = JSONObject.latest.values;
        require(label.equals(actual.get("name")));
        require(name.equals(actual.get("packageName")));
        require(version.equals(actual.get("version")));
        require(Integer.valueOf(code).equals(actual.get("versionCode")));
        require(Boolean.TRUE.equals(actual.get("downloadCompatibilityVerification")));
        require(Boolean.TRUE.equals(actual.get("feedbackExport")));
        require(Boolean.TRUE.equals(actual.get("immersiveFeed")));
    }
    public static void main(String[] args) { INVOCATION System.out.println("3 installed identity cases passed"); }
}
'''.replace("METHOD", method).replace("INVOCATION", invocation)
        with tempfile.TemporaryDirectory() as temporary:
            java = Path(temporary) / "AppInfoHarness.java"
            java.write_text(fixture)
            compile_result = subprocess.run(["java", "-m", "jdk.compiler/com.sun.tools.javac.Main",
                                             "-source", "8", "-target", "8", "-Xlint:-options",
                                             "-d", temporary, str(java)], capture_output=True, text=True)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run(["java", "-cp", temporary, "AppInfoHarness"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "3 installed identity cases passed")


if __name__ == "__main__":
    unittest.main()
