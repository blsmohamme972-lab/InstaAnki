package com.instaanki.app;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipException;
import java.io.EOFException;

/** Imports data-only packages. Imported files can never replace executable UI assets. */
final class ContentPacks {
    static final long MAX_TOTAL_BYTES = 512L * 1024 * 1024;
    static final long MAX_FILE_BYTES = 192L * 1024 * 1024;
    static final int MAX_ENTRIES = 3000;
    static final String CONTENT_ORIGIN = "https://appassets.androidplatform.net/content/";
    private static final Set<String> ALLOWED = new HashSet<>(Arrays.asList(
        "json", "jpg", "jpeg", "png", "webp", "gif", "avif", "mp3", "m4a", "aac",
        "ogg", "opus", "wav", "mp4", "webm", "vtt", "txt"));
    private final File root;

    ContentPacks(File root) throws IOException {
        this.root = root;
        if (!root.isDirectory() && !root.mkdirs()) throw new IOException("Cannot create content directory.");
        recoverInterruptedInstall();
    }

    synchronized JSONArray list() {
        JSONArray packs = new JSONArray();
        File[] folders = root.listFiles();
        if (folders == null) return packs;
        Arrays.sort(folders, (a, b) -> a.getName().compareToIgnoreCase(b.getName()));
        for (File folder : folders) {
            if (!validId(folder.getName()) || !folder.isDirectory()) continue;
            try {
                JSONObject manifest = new JSONObject(readText(new File(folder, "manifest.json"), 5 * 1024 * 1024));
                packs.put(describe(folder.getName(), manifest));
            } catch (Exception ignored) { /* Ignore incomplete staging data, never discard learning state. */ }
        }
        return packs;
    }

    synchronized JSONObject importZip(InputStream input) throws Exception {
        File staging = new File(root, ".staging-" + UUID.randomUUID());
        if (!staging.mkdirs()) throw new IOException("Cannot stage the content package.");
        boolean committed = false;
        try {
            long totalBytes = 0;
            int entries = 0;
            Set<String> names = new HashSet<>();
            try (ZipInputStream zip = new ZipInputStream(input)) {
                ZipEntry entry;
                byte[] buffer = new byte[64 * 1024];
                while ((entry = zip.getNextEntry()) != null) {
                    if (++entries > MAX_ENTRIES) throw new IOException("Package contains too many files (maximum 3000).");
                    String name = entry.getName();
                    if (name == null || name.length() > 320 || name.startsWith("/") || name.contains("\\")
                        || name.indexOf('\u0000') >= 0 || name.contains(":")) {
                        throw new IOException("Package contains an unsafe file path.");
                    }
                    File output = safeChild(staging, name);
                    if (entry.isDirectory()) { if (!output.isDirectory() && !output.mkdirs()) throw new IOException("Cannot create package directory."); continue; }
                    if (!names.add(name.toLowerCase(Locale.ROOT))) throw new IOException("Package contains duplicate file names.");
                    String extension = extension(name);
                    if (!ALLOWED.contains(extension)) throw new IOException("Unsupported package file: " + name + ". Packages may contain media and JSON, not executable code.");
                    if (entry.getSize() > MAX_FILE_BYTES) throw new IOException("A package file is too large.");
                    if ("json".equals(extension) && entry.getSize() > 5 * 1024 * 1024) throw new IOException("A JSON file is too large.");
                    File parent = output.getParentFile();
                    if (!parent.isDirectory() && !parent.mkdirs()) throw new IOException("Cannot create package directory.");
                    long fileBytes = 0;
                    try (FileOutputStream out = new FileOutputStream(output)) {
                        int count;
                        while ((count = zip.read(buffer)) != -1) {
                            fileBytes += count; totalBytes += count;
                            if (fileBytes > MAX_FILE_BYTES || totalBytes > MAX_TOTAL_BYTES
                                || ("json".equals(extension) && fileBytes > 5 * 1024 * 1024)) {
                                throw new IOException("Package exceeds the import size limit.");
                            }
                            out.write(buffer, 0, count);
                        }
                    }
                    zip.closeEntry();
                }
            }
            File manifestFile = new File(staging, "manifest.json");
            if (!manifestFile.isFile()) throw new IOException("Package must contain manifest.json at its root.");
            JSONObject manifest = new JSONObject(readText(manifestFile, 5 * 1024 * 1024));
            String id = manifest.optString("packId", manifest.optString("id", ""));
            if (!validId(id)) throw new IOException("The package needs a valid id (letters, numbers, dots, underscores and hyphens).");
            int schema = manifest.optInt("schemaVersion", 1);
            if (schema != 1) throw new IOException("This package requires a newer app version.");
            JSONArray lessonData = manifest.optJSONArray("lessons");
            if (lessonData == null) {
                String lessonsPath = manifest.optString("lessonsFile", "lessons.json");
                File lessons = safeChild(staging, lessonsPath);
                if (!lessons.isFile()) throw new IOException("Package must contain its lessons JSON file.");
                String json = readText(lessons, 5 * 1024 * 1024).trim();
                lessonData = json.startsWith("[") ? new JSONArray(json) : new JSONObject(json).optJSONArray("lessons");
            }
            // Optional SHA-256 map provides corruption detection. It is not a publisher signature.
            JSONObject hashes = manifest.optJSONObject("sha256");
            if (hashes != null) {
                java.util.Iterator<String> it = hashes.keys();
                while (it.hasNext()) {
                    String path = it.next();
                    File f = safeChild(staging, path);
                    String expected = hashes.getString(path).toLowerCase(Locale.ROOT);
                    if (!expected.matches("[a-f0-9]{64}") || !f.isFile() || !sha256(f).equals(expected)) {
                        throw new IOException("Integrity check failed for " + path + ".");
                    }
                }
            }
            validateLessons(lessonData);
            File installed = new File(root, id);
            File previous = new File(root, ".previous-" + UUID.randomUUID());
            boolean hadPrevious = installed.exists();
            if (hadPrevious && !installed.renameTo(previous)) throw new IOException("Cannot update the existing package.");
            if (!staging.renameTo(installed)) {
                if (hadPrevious && !previous.renameTo(installed)) throw new IOException("The package update was interrupted. The previous package is retained and will be recovered when you reopen the app.");
                throw new IOException("Cannot finish installing the package.");
            }
            committed = true;
            if (hadPrevious) deleteTree(previous);
            return describe(id, manifest).put("uncompressedBytes", totalBytes);
        } catch (ZipException | EOFException incomplete) {
            throw new IOException("This ZIP is incomplete or damaged. Download the file again, then import it. Your installed lessons and learning data were preserved.", incomplete);
        } catch (org.json.JSONException invalid) {
            throw new IOException("This package has invalid lesson metadata. Choose a complete InstaAnki lesson ZIP. Your installed lessons and learning data were preserved.", invalid);
        } finally {
            if (!committed) deleteTree(staging);
        }
    }

    File resolve(String path) throws IOException { return safeChild(root, path); }

    private static void validateLessons(JSONArray lessons) throws IOException {
        if (lessons == null || lessons.length() > 20000) throw new IOException("The package must contain a valid lesson list.");
        Set<String> ids = new HashSet<>();
        for (int i = 0; i < lessons.length(); i++) {
            JSONObject lesson = lessons.optJSONObject(i);
            Object value = lesson == null ? null : lesson.opt("id");
            if (!(value instanceof String) || !((String) value).matches("[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
                || value.equals("__proto__") || value.equals("constructor") || value.equals("prototype") || !ids.add((String) value)) {
                throw new IOException("The package contains an invalid or duplicate lesson ID. Nothing was installed.");
            }
        }
    }

    /** Recover a process stop between moving the old directory aside and activating its replacement. */
    private void recoverInterruptedInstall() throws IOException {
        File[] previous = root.listFiles((dir, name) -> name.startsWith(".previous-"));
        if (previous != null) {
            Arrays.sort(previous, (a, b) -> Long.compare(b.lastModified(), a.lastModified()));
            for (File backup : previous) {
                if (!backup.isDirectory()) continue;
                try {
                    JSONObject manifest = new JSONObject(readText(new File(backup, "manifest.json"), 5 * 1024 * 1024));
                    String id = manifest.optString("packId", manifest.optString("id", ""));
                    if (!validId(id)) continue;
                    File installed = new File(root, id);
                    if (!installed.exists()) {
                        // If storage is temporarily unavailable, keep the recovery copy and
                        // let the app open its other lessons and independent learning store.
                        if (!backup.renameTo(installed)) continue;
                    } else if (new File(installed, "manifest.json").isFile()) deleteTree(backup);
                } catch (Exception invalid) { /* Retain an unreadable backup for recovery; never touch SQLite. */ }
            }
        }
        File[] stages = root.listFiles((dir, name) -> name.startsWith(".staging-"));
        if (stages != null) for (File stage : stages) deleteTree(stage);
    }

    private static JSONObject describe(String id, JSONObject manifest) throws Exception {
        return new JSONObject().put("packId", id).put("baseUrl", CONTENT_ORIGIN + id + "/").put("manifest", manifest);
    }

    private static boolean validId(String id) {
        return id != null && id.matches("[A-Za-z0-9][A-Za-z0-9._-]{0,79}") && !id.equals(".") && !id.equals("..");
    }

    static File safeChild(File base, String path) throws IOException {
        if (path == null || path.isEmpty() || path.startsWith("/") || path.contains("\\") || path.indexOf('\u0000') >= 0) {
            throw new IOException("Unsafe file path.");
        }
        File file = new File(base, path).getCanonicalFile();
        String prefix = base.getCanonicalPath() + File.separator;
        if (!file.getPath().startsWith(prefix)) throw new IOException("Package contains an unsafe file path.");
        return file;
    }

    private static String extension(String path) {
        int dot = path.lastIndexOf('.');
        return dot < 0 ? "" : path.substring(dot + 1).toLowerCase(Locale.ROOT);
    }

    private static String readText(File file, int limit) throws IOException {
        if (file.length() > limit) throw new IOException("Metadata file is too large.");
        return new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
    }

    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new FileInputStream(file)) {
            byte[] buffer = new byte[64 * 1024]; int count;
            while ((count = in.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        StringBuilder hex = new StringBuilder();
        for (byte b : digest.digest()) hex.append(String.format(Locale.ROOT, "%02x", b & 255));
        return hex.toString();
    }

    private static void deleteTree(File file) {
        if (file.isDirectory()) {
            File[] children = file.listFiles();
            if (children != null) for (File child : children) deleteTree(child);
        }
        file.delete();
    }
}
