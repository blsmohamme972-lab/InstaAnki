package com.instaanki.app;

import org.json.JSONObject;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** JVM checks for the actual data-only ZIP importer. Android UI tests are separate. */
public final class ContentPacksTest {
    private static int passed;

    private static byte[] zip(Map<String, byte[]> entries) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ZipOutputStream out = new ZipOutputStream(bytes)) {
            for (Map.Entry<String, byte[]> entry : entries.entrySet()) {
                out.putNextEntry(new ZipEntry(entry.getKey())); out.write(entry.getValue()); out.closeEntry();
            }
        }
        return bytes.toByteArray();
    }

    private static Map<String, byte[]> valid() {
        Map<String, byte[]> files = new LinkedHashMap<>();
        files.put("manifest.json", "{\"schemaVersion\":1,\"id\":\"test-pack\",\"title\":\"Test\",\"lessonsFile\":\"lessons.json\"}".getBytes(StandardCharsets.UTF_8));
        files.put("lessons.json", "[{\"id\":\"a\",\"title\":\"A lesson\"}]".getBytes(StandardCharsets.UTF_8));
        return files;
    }

    private static void assertTrue(boolean condition, String name) {
        if (!condition) throw new AssertionError(name);
        passed++;
        System.out.println("PASS " + name);
    }

    private static void rejects(ContentPacks manager, Map<String, byte[]> files, String name) throws Exception {
        boolean rejected = false;
        try { manager.importZip(new ByteArrayInputStream(zip(files))); } catch (Exception expected) { rejected = true; }
        assertTrue(rejected, name);
        assertTrue(manager.list().length() == 1, name + " preserves installed content");
    }

    public static void main(String[] args) throws Exception {
        File parent = Files.createTempDirectory("instaanki-import-test-").toFile();
        ContentPacks manager = new ContentPacks(new File(parent, "packs"));
        JSONObject result = manager.importZip(new ByteArrayInputStream(zip(valid())));
        assertTrue(result.getString("packId").equals("test-pack"), "valid pack imports");
        assertTrue(manager.list().length() == 1, "installed pack lists");
        Map<String, byte[]> files = valid(); files.put("../escape.txt", "bad".getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "zip-slip rejected");
        assertTrue(!new File(parent, "escape.txt").exists(), "no path escape");
        files = valid(); files.put("payload.html", "<script>bad()</script>".getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "HTML executable content rejected");
        files = valid(); files.put("payload.js", "bad()".getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "JavaScript executable content rejected");
        files = valid(); files.put("asset.svg", "<svg/>".getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "active SVG content rejected");
        files = valid(); files.put("LESSONS.JSON", "[]".getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "case-colliding duplicate rejected");
        files = valid(); files.put("manifest.json", "{\"schemaVersion\":99,\"id\":\"test-pack\",\"lessons\":[]}".getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "unknown schema rejected");
        files = valid(); files.put("manifest.json", "{\"schemaVersion\":1,\"id\":\"../escape\",\"lessons\":[]}".getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "unsafe id rejected");
        files = valid(); files.put("manifest.json", "{\"schemaVersion\":1,\"id\":\"test-pack\",\"lessons\":[],\"sha256\":{\"lessons.json\":\"0000000000000000000000000000000000000000000000000000000000000000\"}}".getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "invalid SHA-256 rejected");
        files = valid(); files.put("large.json", new byte[5 * 1024 * 1024 + 1]);
        rejects(manager, files, "expanded JSON size enforced");
        files = valid(); files.put("lessons.json", "[{\"id\":\"b\"}]".getBytes(StandardCharsets.UTF_8));
        manager.importZip(new ByteArrayInputStream(zip(files)));
        assertTrue(manager.list().length() == 1, "same id updates in place");
        assertTrue(new String(Files.readAllBytes(manager.resolve("test-pack/lessons.json").toPath()), StandardCharsets.UTF_8).contains("\"b\""), "updated files activated");
        File[] leftovers = new File(parent, "packs").listFiles((dir, name) -> name.startsWith("."));
        assertTrue(leftovers != null && leftovers.length == 0, "staging is cleaned after failures and updates");
        System.out.println("All " + passed + " importer assertions passed.");
    }
}
