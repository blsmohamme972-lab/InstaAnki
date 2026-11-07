package com.instaanki.app;

import org.json.JSONObject;
import org.json.JSONArray;
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

    private static JSONObject lesson(String id, int version) throws Exception {
        return new JSONObject().put("id", id).put("version", version).put("title", "Synthetic lesson " + id)
            .put("audioUrl", "media/audio.mp3").put("poster", "media/poster.png")
            .put("source", new JSONObject().put("bookId", "synthetic-source").put("questionNumber", 1))
            .put("scenes", new JSONArray().put(new JSONObject().put("start", 0).put("end", 1).put("image", "media/poster.png")))
            .put("quiz", new JSONObject().put("prompt", "Synthetic question").put("options", new JSONArray().put("A").put("B")).put("correctIndex", 0));
    }

    private static JSONArray trustedBooks() throws Exception {
        return new JSONArray().put(new JSONObject().put("id", "synthetic-source").put("title", "Synthetic source")
            .put("author", "Fixture author").put("year", 2026).put("totalQuestions", 10));
    }

    private static void setLesson(Map<String, byte[]> files, JSONObject lesson) {
        files.put("lessons.json", new JSONArray().put(lesson).toString().getBytes(StandardCharsets.UTF_8));
    }

    private static Map<String, byte[]> valid() throws Exception {
        Map<String, byte[]> files = new LinkedHashMap<>();
        files.put("manifest.json", "{\"schemaVersion\":1,\"id\":\"test-pack\",\"title\":\"Test\",\"lessonsFile\":\"lessons.json\"}".getBytes(StandardCharsets.UTF_8));
        setLesson(files, lesson("a", 2));
        // Nonempty synthetic bytes test file presence; decoding is separate QA.
        files.put("media/audio.mp3", new byte[]{1, 2, 3});
        files.put("media/poster.png", new byte[]{4, 5, 6});
        return files;
    }

    private static Map<String, byte[]> withHashes(Map<String, byte[]> files) throws Exception {
        JSONObject hashes = new JSONObject();
        for (Map.Entry<String, byte[]> entry : files.entrySet()) {
            if (entry.getKey().equals("manifest.json")) continue;
            StringBuilder hex = new StringBuilder();
            for (byte b : java.security.MessageDigest.getInstance("SHA-256").digest(entry.getValue())) hex.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
            hashes.put(entry.getKey(), hex.toString());
        }
        JSONObject manifest = new JSONObject(new String(files.get("manifest.json"), StandardCharsets.UTF_8));
        files.put("manifest.json", manifest.put("sha256", hashes).toString().getBytes(StandardCharsets.UTF_8));
        return files;
    }

    private static void assertTrue(boolean condition, String name) {
        if (!condition) throw new AssertionError(name);
        passed++;
        System.out.println("PASS " + name);
    }

    private static String rejects(ContentPacks manager, Map<String, byte[]> files, String name) throws Exception {
        int installedBefore = manager.list().length();
        byte[] before = Files.readAllBytes(manager.resolve("test-pack/lessons.json").toPath());
        File audio = manager.resolve("test-pack/media/audio.mp3");
        byte[] audioBefore = audio.isFile() ? Files.readAllBytes(audio.toPath()) : null;
        byte[] identitiesBefore = Files.readAllBytes(manager.resolve(".lesson-identities.json").toPath());
        Exception rejection = null;
        try { manager.importZip(new ByteArrayInputStream(zip(files))); } catch (Exception expected) { rejection = expected; }
        assertTrue(rejection != null, name);
        assertTrue(manager.list().length() == installedBefore, name + " preserves installed content");
        assertTrue(java.util.Arrays.equals(before, Files.readAllBytes(manager.resolve("test-pack/lessons.json").toPath())), name + " preserves installed lesson bytes");
        if (audioBefore != null) assertTrue(java.util.Arrays.equals(audioBefore, Files.readAllBytes(audio.toPath())), name + " preserves installed narration bytes");
        assertTrue(java.util.Arrays.equals(identitiesBefore, Files.readAllBytes(manager.resolve(".lesson-identities.json").toPath())), name + " preserves stable source bindings");
        return rejection.getMessage();
    }

    private static Map<String, byte[]> sourcePack(String id, int question) throws Exception {
        Map<String, byte[]> files = valid();
        JSONObject item = lesson("a", 2); item.getJSONObject("source").put("questionNumber", question); setLesson(files, item);
        files.put("manifest.json", new JSONObject().put("schemaVersion", 1).put("id", id).put("lessonsFile", "lessons.json").toString().getBytes(StandardCharsets.UTF_8));
        return files;
    }

    private static Map<String, byte[]> withdrawal(String id) throws Exception {
        Map<String, byte[]> files = new LinkedHashMap<>();
        files.put("manifest.json", new JSONObject().put("schemaVersion", 1).put("id", id).put("lessonsFile", "lessons.json").toString().getBytes(StandardCharsets.UTF_8));
        files.put("lessons.json", "[]".getBytes(StandardCharsets.UTF_8));
        return files;
    }

    private static void legacyPack(File root, String id, int question) throws Exception {
        // Deliberately bypass current admission to model already-installed
        // pre-upgrade collisions; the current importer must never create them.
        File directory = new File(root, id);
        for (Map.Entry<String, byte[]> entry : sourcePack(id, question).entrySet()) {
            File file = new File(directory, entry.getKey()); file.getParentFile().mkdirs(); Files.write(file.toPath(), entry.getValue());
        }
    }

    private static JSONObject binding(ContentPacks manager) throws Exception {
        return new JSONObject(new String(Files.readAllBytes(manager.resolve(".lesson-identities.json").toPath()), StandardCharsets.UTF_8)).getJSONObject("lessons").getJSONObject("a");
    }

    private static void legacyConflictWithdrawals(File parent) throws Exception {
        for (int order = 0; order < 2; order++) {
            File root = new File(parent, "legacy-order-" + order);
            // Reverse which source each directory contains, so neither package
            // order can establish an arbitrary authoritative source.
            legacyPack(root, "test-pack", order == 0 ? 1 : 2);
            legacyPack(root, "legacy-other", order == 0 ? 2 : 1);
            ContentPacks manager = new ContentPacks(root, trustedBooks());
            manager.importZip(new ByteArrayInputStream(zip(withdrawal("test-pack"))));
            assertTrue(new JSONArray(new String(Files.readAllBytes(manager.resolve("test-pack/lessons.json").toPath()), StandardCharsets.UTF_8)).length() == 0, "legacy collision can be withdrawn in order " + order);
            assertTrue(binding(manager).optBoolean("ambiguous") && !binding(manager).has("bookId"), "legacy conflict records a denied ID without choosing a source in order " + order);
            for (int question : new int[]{1, 2}) {
                String message = rejects(manager, sourcePack("test-pack", question), "ambiguous legacy ID rejects source " + question + " after first withdrawal in order " + order);
                assertTrue(message.contains("conflicting source identities"), "ambiguous legacy import explains why its source cannot be chosen");
            }
            manager.importZip(new ByteArrayInputStream(zip(withdrawal("legacy-other"))));
            manager = new ContentPacks(root, trustedBooks());
            assertTrue(binding(manager).optBoolean("ambiguous"), "withdrawing both conflicting packs and restarting retains the denied ID in order " + order);
            for (int question : new int[]{1, 2}) rejects(manager, sourcePack("test-pack", question), "ambiguous legacy ID remains denied after complete withdrawal for source " + question + " in order " + order);

            root = new File(parent, "trusted-order-" + order);
            manager = new ContentPacks(root, trustedBooks());
            manager.importZip(new ByteArrayInputStream(zip(valid()))); // Trusted a/Q1 binding.
            legacyPack(root, "test-pack", order == 0 ? 1 : 2);
            legacyPack(root, "legacy-other", order == 0 ? 2 : 1);
            manager.importZip(new ByteArrayInputStream(zip(withdrawal(order == 0 ? "legacy-other" : "test-pack"))));
            assertTrue(binding(manager).getInt("questionNumber") == 1 && !binding(manager).has("ambiguous"), "legacy conflict withdrawal preserves the trusted source binding in order " + order);
            rejects(manager, sourcePack("test-pack", 2), "legacy withdrawal cannot reassign a trusted source binding in order " + order);
            manager.importZip(new ByteArrayInputStream(zip(sourcePack("test-pack", 1))));
            assertTrue(binding(manager).getInt("questionNumber") == 1, "trusted same-source reimport remains valid after legacy conflict withdrawal in order " + order);
        }
    }

    public static void main(String[] args) throws Exception {
        File parent = Files.createTempDirectory("instaanki-import-test-").toFile();
        ContentPacks manager = new ContentPacks(new File(parent, "packs"), trustedBooks());
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
        files = valid(); files.put("lessons.json", "{\"unexpected\":[]}".getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "non-lesson object rejected before replacement");
        files = valid(); files.put("lessons.json", "[{\"id\":\"a\"},{\"id\":\"a\"}]".getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "duplicate stable lesson IDs rejected before replacement");
        for (String field : new String[]{"title", "audioUrl", "poster", "scenes", "quiz", "source"}) {
            files = valid(); JSONObject invalid = lesson("a", 3); invalid.remove(field); setLesson(files, invalid);
            rejects(manager, files, "missing " + field + " rejected before replacement");
        }
        files = valid(); files.put("lessons.json", "[{\"id\":\"a\",\"version\":3}]".getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "ID-only replacement cannot erase a playable lesson");
        files = valid(); files.remove("media/audio.mp3");
        rejects(manager, files, "missing packaged narration rejected before replacement");
        files = valid(); files.remove("media/poster.png");
        rejects(manager, files, "missing packaged image rejected before replacement");
        files = valid(); JSONObject badScene = lesson("a", 3); badScene.getJSONArray("scenes").getJSONObject(0).put("end", 0); setLesson(files, badScene);
        rejects(manager, files, "invalid scene timing rejected before replacement");
        files = valid(); JSONObject badAnswer = lesson("a", 3); badAnswer.getJSONObject("quiz").put("correctIndex", .5); setLesson(files, badAnswer);
        rejects(manager, files, "fractional answer index rejected before replacement");
        files = valid(); JSONObject badSource = lesson("a", 3); badSource.getJSONObject("source").put("questionNumber", 2); setLesson(files, badSource);
        rejects(manager, files, "same lesson ID cannot switch source question");
        files = valid(); badSource = lesson("a", 3); badSource.getJSONObject("source").put("bookId", "another-source"); setLesson(files, badSource);
        rejects(manager, files, "same lesson ID cannot switch source book");
        files = valid(); badSource = lesson("new-id", 3); badSource.getJSONObject("source").put("bookId", "another-source"); setLesson(files, badSource);
        rejects(manager, files, "new lesson ID cannot replace an approved package with a foreign book");
        files = valid(); badSource = lesson("new-id", 3); badSource.getJSONObject("source").put("questionNumber", 11); setLesson(files, badSource);
        rejects(manager, files, "question beyond approved book range rejected before replacement");
        files = valid(); badSource = lesson("a", 3); badSource.getJSONObject("source").put("questionNumber", 2); setLesson(files, badSource);
        files.put("manifest.json", "{\"schemaVersion\":1,\"id\":\"another-pack\",\"lessonsFile\":\"lessons.json\"}".getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "another package cannot reassign an installed stable lesson ID");
        files = valid(); JSONObject changedBook = trustedBooks().getJSONObject(0).put("title", "Incorrect source title");
        files.put("manifest.json", new JSONObject(new String(files.get("manifest.json"), StandardCharsets.UTF_8)).put("books", new JSONArray().put(changedBook)).toString().getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "conflicting publication identity rejected before replacement");
        files = valid();
        files.put("manifest.json", new JSONObject(new String(files.get("manifest.json"), StandardCharsets.UTF_8)).put("books", new JSONArray().put(new JSONObject().put("id", "foreign-source").put("totalQuestions", 10))).toString().getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "imported metadata cannot grant itself a new approved book");
        files = valid(); setLesson(files, lesson("a", 1));
        rejects(manager, files, "older lesson revision rejected before replacement");
        byte[] unchanged = Files.readAllBytes(manager.resolve("test-pack/lessons.json").toPath());
        manager.importZip(new ByteArrayInputStream(zip(valid())));
        assertTrue(java.util.Arrays.equals(unchanged, Files.readAllBytes(manager.resolve("test-pack/lessons.json").toPath())), "same-version idempotent reimport remains valid");
        files = valid(); JSONObject changed = lesson("a", 2).put("title", "Changed without a revision"); setLesson(files, changed);
        rejects(manager, files, "changed same-version lesson metadata rejected before replacement");
        files = valid(); changed = lesson("a", 2); changed.getJSONObject("quiz").put("correctIndex", 1); setLesson(files, changed);
        rejects(manager, files, "changed same-version keyed answer rejected before replacement");
        files = valid(); changed = lesson("a", 2).put("title", "Same revision in another pack"); setLesson(files, changed);
        files.put("manifest.json", "{\"schemaVersion\":1,\"id\":\"another-pack\",\"lessonsFile\":\"lessons.json\"}".getBytes(StandardCharsets.UTF_8));
        rejects(manager, files, "same revision cannot change content through another package");
        files = valid();
        String numeric = new String(files.get("lessons.json"), StandardCharsets.UTF_8).replace("\"version\":2", "\"version\":2.0").replace("\"start\":0", "\"start\":0e0");
        files.put("lessons.json", numeric.getBytes(StandardCharsets.UTF_8));
        manager.importZip(new ByteArrayInputStream(zip(files)));
        assertTrue(java.util.Arrays.equals(files.get("lessons.json"), Files.readAllBytes(manager.resolve("test-pack/lessons.json").toPath())), "semantic JSON comparison accepts equivalent numeric spelling");
        files = valid(); files.put("media/audio.mp3", new byte[]{9, 8, 7});
        manager.importZip(new ByteArrayInputStream(zip(files)));
        assertTrue(java.util.Arrays.equals(files.get("media/audio.mp3"), Files.readAllBytes(manager.resolve("test-pack/media/audio.mp3").toPath())), "legacy hashless same-version media recovery does not invent an unavailable pin");
        Map<String, byte[]> pinned = withHashes(valid());
        manager.importZip(new ByteArrayInputStream(zip(pinned)));
        files = valid(); files.put("media/audio.mp3", new byte[]{7, 8, 9}); withHashes(files);
        rejects(manager, files, "same-version narration cannot replace a previously pinned asset even with a new self-consistent hash");
        files = valid(); files.put("media/poster.png", new byte[]{9, 8, 7}); withHashes(files);
        rejects(manager, files, "same-version image cannot replace a previously pinned asset");
        Files.write(manager.resolve("test-pack/media/audio.mp3").toPath(), new byte[]{0});
        manager.importZip(new ByteArrayInputStream(zip(pinned)));
        assertTrue(java.util.Arrays.equals(pinned.get("media/audio.mp3"), Files.readAllBytes(manager.resolve("test-pack/media/audio.mp3").toPath())), "same-version reinstall repairs corrupt audio to the original pinned hash");
        Files.delete(manager.resolve("test-pack/media/poster.png").toPath());
        manager.importZip(new ByteArrayInputStream(zip(pinned)));
        assertTrue(java.util.Arrays.equals(pinned.get("media/poster.png"), Files.readAllBytes(manager.resolve("test-pack/media/poster.png").toPath())), "same-version reinstall repairs a missing pinned image");
        manager.importZip(new ByteArrayInputStream(zip(valid())));
        assertTrue(manager.list().getJSONObject(0).getJSONObject("manifest").getJSONObject("sha256").has("media/audio.mp3"), "identical hashless reimport retains earlier media pins");
        files = valid(); files.put("media/audio.mp3", new byte[]{7, 8, 9});
        rejects(manager, files, "a hashless reimport cannot discard pins to permit a later same-version asset edit");
        files = valid(); setLesson(files, lesson("a", 3)); manager.importZip(new ByteArrayInputStream(zip(files)));
        assertTrue(new JSONArray(new String(Files.readAllBytes(manager.resolve("test-pack/lessons.json").toPath()), StandardCharsets.UTF_8)).getJSONObject(0).getInt("version") == 3, "newer lesson revision installs");
        rejects(manager, valid(), "older revision cannot roll back a later correction");
        byte[] complete = zip(valid());boolean friendly = false;
        int firstData = 30 + (complete[26] & 255) + ((complete[27] & 255) << 8)
            + (complete[28] & 255) + ((complete[29] & 255) << 8);
        try { manager.importZip(new ByteArrayInputStream(java.util.Arrays.copyOf(complete, firstData + 2))); }
        catch (Exception expected) { friendly = expected.getMessage().contains("incomplete or damaged"); }
        assertTrue(friendly, "truncated ZIP reports a friendly recovery instruction");
        assertTrue(manager.list().length() == 1, "truncated ZIP preserves installed package");
        files = valid(); setLesson(files, lesson("b", 1));
        manager.importZip(new ByteArrayInputStream(zip(files)));
        assertTrue(manager.list().length() == 1, "same id updates in place");
        assertTrue(new String(Files.readAllBytes(manager.resolve("test-pack/lessons.json").toPath()), StandardCharsets.UTF_8).contains("\"b\""), "updated files activated");
        Map<String, byte[]> withdrawn = new LinkedHashMap<>();
        withdrawn.put("manifest.json", "{\"schemaVersion\":1,\"id\":\"test-pack\",\"lessonsFile\":\"lessons.json\",\"books\":[]}".getBytes(StandardCharsets.UTF_8));
        withdrawn.put("lessons.json", "[]".getBytes(StandardCharsets.UTF_8));
        // Simulate a pre-index installation: a withdrawal must first bootstrap
        // the readable installed source identity, then retain it across restart.
        Files.delete(manager.resolve(".lesson-identities.json").toPath());
        manager.importZip(new ByteArrayInputStream(zip(withdrawn)));
        assertTrue(new JSONArray(new String(Files.readAllBytes(manager.resolve("test-pack/lessons.json").toPath()), StandardCharsets.UTF_8)).length() == 0, "explicit empty correction still withdraws lessons without requiring media");
        manager = new ContentPacks(new File(parent, "packs"), trustedBooks());
        Map<String, byte[]> reassigned = valid(); changed = lesson("b", 3); changed.getJSONObject("source").put("questionNumber", 2); setLesson(reassigned, changed);
        rejects(manager, reassigned, "withdrawal and restart cannot free a stable lesson ID for a different source");
        manager.importZip(new ByteArrayInputStream(zip(files)));
        assertTrue(new JSONArray(new String(Files.readAllBytes(manager.resolve("test-pack/lessons.json").toPath()), StandardCharsets.UTF_8)).getJSONObject(0).getString("id").equals("b"), "withdrawn lesson can be re-added for the same source");
        Files.write(manager.resolve("test-pack/lessons.json").toPath(), "unreadable metadata".getBytes(StandardCharsets.UTF_8));
        manager.importZip(new ByteArrayInputStream(zip(files)));
        assertTrue(new String(Files.readAllBytes(manager.resolve("test-pack/lessons.json").toPath()), StandardCharsets.UTF_8).contains("\"b\""), "valid package can repair already unreadable installed metadata");
        JSONObject invalidPrior = lesson("b", 1); invalidPrior.remove("title");
        Files.write(manager.resolve("test-pack/lessons.json").toPath(), new JSONArray().put(invalidPrior).toString().getBytes(StandardCharsets.UTF_8));
        manager.importZip(new ByteArrayInputStream(zip(files)));
        assertTrue(new JSONArray(new String(Files.readAllBytes(manager.resolve("test-pack/lessons.json").toPath()), StandardCharsets.UTF_8)).getJSONObject(0).has("title"), "same-version repair can replace unusable legacy lesson metadata");
        byte[] identityIndex = Files.readAllBytes(manager.resolve(".lesson-identities.json").toPath());
        Files.write(manager.resolve(".lesson-identities.json").toPath(), "{\"schemaVersion\":1,\"lessons\":\"damaged\"}".getBytes(StandardCharsets.UTF_8));
        manager = new ContentPacks(new File(parent, "packs"), trustedBooks());
        assertTrue(manager.list().length() == 1, "corrupt identity index does not prevent startup or installed collection access");
        String indexError = rejects(manager, files, "corrupt identity index blocks import without altering installed files");
        assertTrue(indexError.contains("identity index could not be read"), "corrupt identity index explains the import failure clearly");
        Files.write(manager.resolve(".lesson-identities.json").toPath(), identityIndex);
        File[] leftovers = new File(parent, "packs").listFiles((dir, name) -> name.startsWith(".staging-") || name.startsWith(".previous-"));
        assertTrue(leftovers != null && leftovers.length == 0, "staging is cleaned after failures and updates");
        File root = new File(parent, "packs");
        assertTrue(new File(root, "test-pack").renameTo(new File(root, ".previous-interrupted-fixture")), "simulate interruption after old package is staged aside");
        new File(root, ".staging-abandoned-fixture").mkdirs();
        manager = new ContentPacks(root, trustedBooks());
        assertTrue(manager.list().length() == 1, "cold start recovers interrupted package replacement");
        assertTrue(new String(Files.readAllBytes(manager.resolve("test-pack/lessons.json").toPath()), StandardCharsets.UTF_8).contains("\"b\""), "recovery retains the previous complete lesson version");
        assertTrue(!new File(root, ".staging-abandoned-fixture").exists(), "cold start removes abandoned staging data only");
        legacyConflictWithdrawals(parent);
        System.out.println("All " + passed + " importer assertions passed.");
    }
}
