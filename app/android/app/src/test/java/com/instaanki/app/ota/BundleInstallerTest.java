package com.instaanki.app.ota;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class BundleInstallerTest {

    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private final Map<String, String> remote = new HashMap<>(); // sha -> content
    private final List<String> downloads = new ArrayList<>();

    private BundleInstaller.Fetcher fetcher() {
        return sha -> {
            downloads.add(sha);
            String c = remote.get(sha);
            if (c == null) throw new IOException("404");
            return new ByteArrayInputStream(c.getBytes(StandardCharsets.UTF_8));
        };
    }

    private static BundleInstaller.LocalSource local(Map<String, String> files) {
        return path -> files.containsKey(path) ? new ByteArrayInputStream(files.get(path).getBytes(StandardCharsets.UTF_8)) : null;
    }

    private OtaManifest manifest(String version, String... pathAndContent) throws OtaException {
        for (int i = 0; i < pathAndContent.length; i += 2) remote.put(OtaLogicTest.sha(pathAndContent[i + 1]), pathAndContent[i + 1]);
        return OtaManifest.parse(OtaLogicTest.manifestJson(version, 1, pathAndContent).getBytes(StandardCharsets.UTF_8));
    }

    private static String read(File f) throws IOException {
        return new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
    }

    @Test
    public void downloadsOnlyChangedFiles() throws Exception {
        BundleInstaller inst = new BundleInstaller(tmp.newFolder("bundles"));
        Map<String, String> running = new HashMap<>();
        running.put("index.html", "<html>v1</html>");
        running.put("assets/vendor.js", "vendor");
        running.put("assets/app-1.js", "app v1");

        OtaManifest m = manifest("0.2.0", "index.html", "<html>v2</html>", "assets/vendor.js", "vendor", "assets/app-2.js", "app v2");
        assertEquals("<html>v2</html>".length() + "app v2".length(), inst.bytesToDownload(m, local(running)));

        List<String> progress = new ArrayList<>();
        File dir = inst.install(m, local(running), fetcher(), (d, t) -> progress.add(d + "/" + t));
        assertEquals(inst.dirFor("0.2.0"), dir);
        assertEquals("<html>v2</html>", read(new File(dir, "index.html")));
        assertEquals("vendor", read(new File(dir, "assets/vendor.js")));
        assertEquals("app v2", read(new File(dir, "assets/app-2.js")));
        assertEquals(2, downloads.size()); // vendor.js was copied locally
        assertEquals(Arrays.asList("1/3", "2/3", "3/3"), progress);
        assertTrue(inst.exists("0.2.0"));
        assertFalse(new File(dir.getParentFile(), "0.2.0.tmp").exists());
    }

    @Test
    public void corruptedDownloadLeavesNothingBehind() throws Exception {
        BundleInstaller inst = new BundleInstaller(tmp.newFolder("bundles"));
        OtaManifest m = manifest("0.2.0", "index.html", "<html>", "a.js", "real");
        remote.put(OtaLogicTest.sha("real"), "tampered!");
        try {
            inst.install(m, local(new HashMap<>()), fetcher(), null);
            fail("expected a hash mismatch");
        } catch (OtaException expected) {
            assertTrue(expected.getMessage().contains("hash mismatch"));
        }
        assertFalse(inst.exists("0.2.0"));
        assertFalse(inst.dirFor("0.2.0").exists());
        assertFalse(new File(inst.dirFor("0.2.0").getParentFile(), "0.2.0.tmp").exists());
    }

    @Test
    public void localFileWithWrongContentIsDownloadedInstead() throws Exception {
        BundleInstaller inst = new BundleInstaller(tmp.newFolder("bundles"));
        Map<String, String> running = new HashMap<>();
        running.put("index.html", "stale");
        File dir = inst.install(manifest("0.3.0", "index.html", "fresh"), local(running), fetcher(), null);
        assertEquals("fresh", read(new File(dir, "index.html")));
        assertEquals(1, downloads.size());
    }

    @Test
    public void retainOnlyKeepsTheGivenVersions() throws Exception {
        BundleInstaller inst = new BundleInstaller(tmp.newFolder("bundles"));
        for (String v : new String[] { "0.1.0", "0.2.0", "0.3.0" }) {
            inst.install(manifest(v, "index.html", "html " + v), local(new HashMap<>()), fetcher(), null);
        }
        inst.retainOnly(new HashSet<>(Arrays.asList("0.3.0", "0.2.0")));
        assertFalse(inst.exists("0.1.0"));
        assertTrue(inst.exists("0.2.0"));
        assertTrue(inst.exists("0.3.0"));
    }
}
