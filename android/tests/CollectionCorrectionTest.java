package com.instaanki.app;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.FilterInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Arrays;
import java.util.Enumeration;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.zip.ZipOutputStream;

/** Executes the actual production importer on a JVM, not an Android device. */
public final class CollectionCorrectionTest {
    private static final String TARGET = "instaanki-medical-foundations-2026-v1";
    private static final String OTHER = "unrelated-content-fixture";
    private static final JSONArray checks = new JSONArray();

    private static void check(boolean value, String name) {
        if (!value) throw new AssertionError(name);
        checks.put(new JSONObject().put("name", name).put("passed", true));
    }

    private static String hash(Path file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = Files.newInputStream(file)) {
            byte[] buffer = new byte[65536]; int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        StringBuilder text = new StringBuilder();
        for (byte value : digest.digest()) text.append(String.format("%02x", value & 255));
        return text.toString();
    }

    private static JSONObject importFile(ContentPacks packs, Path file) throws Exception {
        try (InputStream input = Files.newInputStream(file)) { return packs.importZip(input); }
    }

    private static Path lessons(ContentPacks packs) throws Exception {
        return packs.resolve(TARGET + "/lessons.json").toPath();
    }

    private static int lessonCount(ContentPacks packs) throws Exception {
        return new JSONArray(Files.readString(lessons(packs))).length();
    }

    private static void snapshot(ContentPacks packs, Path output, String phase) throws Exception {
        Files.writeString(output.resolve(phase + "-packs.json"), packs.list().toString(2) + "\n");
        Files.write(output.resolve(phase + "-lessons.json"), Files.readAllBytes(lessons(packs)));
    }

    private static void stored(ZipOutputStream output, String name, byte[] bytes) throws Exception {
        CRC32 crc = new CRC32(); crc.update(bytes);
        ZipEntry entry = new ZipEntry(name);
        entry.setMethod(ZipEntry.STORED); entry.setSize(bytes.length);
        entry.setCompressedSize(bytes.length); entry.setCrc(crc.getValue());
        output.putNextEntry(entry); output.write(bytes); output.closeEntry();
    }

    private static byte[] unrelated() throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ZipOutputStream output = new ZipOutputStream(bytes)) {
            String manifest = new JSONObject().put("schemaVersion", 1).put("id", OTHER)
                .put("lessons", new JSONArray()).put("books", new JSONArray()).toString();
            stored(output, "manifest.json", manifest.getBytes(StandardCharsets.UTF_8));
            stored(output, "keep.txt", "Unrelated content must remain intact.\n".getBytes(StandardCharsets.UTF_8));
        }
        return bytes.toByteArray();
    }

    private static byte[] corruptPayload(Path correction) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ZipFile source = new ZipFile(correction.toFile()); ZipOutputStream output = new ZipOutputStream(bytes)) {
            Enumeration<? extends ZipEntry> entries = source.entries();
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                byte[] data;
                try (InputStream input = source.getInputStream(entry)) { data = input.readAllBytes(); }
                if (entry.getName().equals("lessons.json")) data = "[{}]\n".getBytes(StandardCharsets.UTF_8);
                stored(output, entry.getName(), data);
            }
        }
        return bytes.toByteArray();
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 3) throw new IllegalArgumentException("original-pack.zip correction.zip output-directory");
        Path original = Path.of(args[0]).toAbsolutePath(), correction = Path.of(args[1]).toAbsolutePath();
        Path output = Path.of(args[2]).toAbsolutePath(); Files.createDirectories(output);
        Path working = Files.createTempDirectory(output, "native-run-");
        JSONArray fixtureBooks;
        // This historical recovery harness explicitly chooses the archive's
        // publication as its synthetic trust baseline. The Android app reads
        // its approved books only from signed, bundled www/data/books.json.
        try (ZipFile archive = new ZipFile(original.toFile()); InputStream input = archive.getInputStream(archive.getEntry("manifest.json"))) {
            fixtureBooks = new JSONObject(new String(input.readAllBytes(), StandardCharsets.UTF_8)).getJSONArray("books");
        }
        ContentPacks packs = new ContentPacks(working.resolve("packs").toFile(), fixtureBooks);
        // This is a filesystem isolation sentinel, not a substitute for Android SQLite testing.
        Path state = working.resolve("separate-learning-state-sentinel.json");
        Files.writeString(state, "{\"note\":\"Do not change learning storage\",\"reviews\":[1]}\n");
        String stateHash = hash(state), originalArchiveHash = hash(original);
        packs.importZip(new ByteArrayInputStream(unrelated()));
        Path otherFile = packs.resolve(OTHER + "/keep.txt").toPath();
        String otherHash = hash(otherFile);
        JSONObject initial = importFile(packs, original);
        check(initial.getString("packId").equals(TARGET), "Original archive uses the exact target pack ID");
        check(lessonCount(packs) == 20 && packs.list().length() == 2, "Original 20 lessons import alongside an unrelated pack");
        String originalLessonHash = hash(lessons(packs));
        snapshot(packs, output, "original");

        Exception corruptFailure = null;
        try { packs.importZip(new ByteArrayInputStream(corruptPayload(correction))); }
        catch (Exception error) { corruptFailure = error; }
        check(corruptFailure != null && corruptFailure.getMessage().contains("Integrity check failed"), "Corrupted correction payload is rejected by the actual SHA-256 verifier");
        check(originalLessonHash.equals(hash(lessons(packs))) && lessonCount(packs) == 20, "Hash failure preserves the previous 20-lesson install");
        Exception truncatedFailure = null;
        try { packs.importZip(new ByteArrayInputStream(Arrays.copyOf(Files.readAllBytes(correction), 200))); }
        catch (Exception error) { truncatedFailure = error; }
        check(truncatedFailure != null, "Correction truncated inside its first ZIP entry is rejected");
        check(originalLessonHash.equals(hash(lessons(packs))) && lessonCount(packs) == 20, "Truncated import preserves the previous 20-lesson install");

        JSONObject corrected;
        try (InputStream input = new FilterInputStream(Files.newInputStream(correction)) {
            @Override public int read(byte[] buffer, int offset, int length) throws java.io.IOException {
                return super.read(buffer, offset, Math.min(length, 97));
            }
        }) { corrected = packs.importZip(input); }
        JSONObject manifest = corrected.getJSONObject("manifest");
        check(corrected.getString("packId").equals(TARGET), "Correction replaces only the exact target ID");
        check(manifest.getString("type").equals("collection-correction"), "Correction has explicit corrective manifest type");
        check(lessonCount(packs) == 0 && manifest.getJSONArray("books").length() == 0, "Actual importer accepts zero lessons and zero books");
        check(packs.list().length() == 2 && hash(otherFile).equals(otherHash), "Unrelated pack remains byte-identical");
        check(hash(state).equals(stateHash), "Learning-state sibling is outside the importer mutation scope");
        try (java.util.stream.Stream<Path> files = Files.list(packs.resolve(TARGET + "/manifest.json").toPath().getParent())) {
            check(files.count() == 3, "Only the three correction files remain in the replaced pack folder");
        }
        snapshot(packs, output, "corrected");
        importFile(packs, correction);
        check(lessonCount(packs) == 0 && packs.list().length() == 2, "Repeated correction is idempotent");

        importFile(packs, original);
        check(lessonCount(packs) == 20 && hash(lessons(packs)).equals(originalLessonHash), "Reimporting the original archive restores all 20 unchanged lessons");
        check(hash(state).equals(stateHash) && hash(otherFile).equals(otherHash), "Reverse import preserves learning sibling and unrelated pack");
        check(hash(original).equals(originalArchiveHash), "Original delivered archive remains byte-identical");
        String[] residue = working.resolve("packs").toFile().list((directory, name) -> name.startsWith("."));
        check(residue != null && residue.length == 0, "No staging or previous-install folders remain after failure and replacement");
        snapshot(packs, output, "restored");
        JSONObject report = new JSONObject().put("schemaVersion", 1).put("reviewedAt", Instant.now().toString())
            .put("implementation", "Unmodified android/src/com/instaanki/app/ContentPacks.java with org.json 20240303 on desktop JVM")
            .put("javaVersion", System.getProperty("java.version")).put("physicalAndroidTested", false)
            .put("sqliteTested", false).put("learningStateEvidence", "Separate file isolation sentinel; browser suite exercises real Learning state through a persistent bridge fixture")
            .put("originalPackSha256", originalArchiveHash).put("correctionPackSha256", hash(correction))
            .put("correctionBytes", Files.size(correction)).put("restoredPackRoot", working.resolve("packs").toString())
            .put("checks", checks);
        Files.writeString(output.resolve("native-review.json"), report.toString(2) + "\n");
        System.out.println("PASS " + checks.length() + " actual-importer correction checks; report: " + output.resolve("native-review.json"));
    }
}
