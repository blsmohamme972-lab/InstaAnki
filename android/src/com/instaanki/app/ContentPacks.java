package com.instaanki.app;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashSet;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
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
    private static final String IDENTITY_INDEX = ".lesson-identities.json";
    private static final int MAX_IDENTITY_BYTES = 16 * 1024 * 1024;
    private static final Set<String> ALLOWED = new HashSet<>(Arrays.asList(
        "json", "jpg", "jpeg", "png", "webp", "gif", "avif", "mp3", "m4a", "aac",
        "ogg", "opus", "wav", "mp4", "webm", "vtt", "txt"));
    private final File root;
    private final Map<String, JSONObject> approvedBooks = new HashMap<>();

    ContentPacks(File root, JSONArray trustedBooks) throws IOException {
        this.root = root;
        if (trustedBooks == null || trustedBooks.length() == 0) throw new IOException("The app's approved source collection is unavailable.");
        try {
            for (int i = 0; i < trustedBooks.length(); i++) {
                JSONObject book = trustedBooks.optJSONObject(i);
                if (book == null || !text(book.opt("id")) || !integer(book.opt("totalQuestions"), 1, 10000000, -1)
                    || approvedBooks.containsKey(book.getString("id"))) throw new IOException("The app's approved source collection is invalid.");
                approvedBooks.put(book.getString("id"), new JSONObject(book.toString()));
            }
        } catch (org.json.JSONException invalid) { throw new IOException("The app's approved source collection is invalid.", invalid); }
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
            JSONArray lessonData = readLessons(staging, manifest);
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
            validatePublications(manifest);
            validateLessons(lessonData, staging);
            File installed = new File(root, id);
            File[] installedPackages = root.listFiles();
            if (installedPackages == null) throw new IOException("The installed collection could not be checked. Nothing was installed.");
            // Source identity is independent of whether a lesson is currently
            // installed: an empty withdrawal must not free its ID for reuse.
            JSONObject identities = lessonIdentities(installedPackages, lessonData);
            JSONObject retainedHashes = new JSONObject();
            for (File folder : installedPackages) {
                if (validId(folder.getName()) && folder.isDirectory()) validateReplacement(folder, staging, lessonData, folder.getName().equals(id), retainedHashes);
            }
            if (retainedHashes.length() > 0) {
                // An otherwise identical legacy reimport must not erase a
                // known pin and allow a later silent same-version asset edit.
                if (hashes == null) hashes = new JSONObject();
                java.util.Iterator<String> paths = retainedHashes.keys();
                while (paths.hasNext()) { String path = paths.next(); hashes.put(path, retainedHashes.getString(path)); }
                byte[] metadata = manifest.put("sha256", hashes).toString().getBytes(StandardCharsets.UTF_8);
                if (metadata.length > 5 * 1024 * 1024) throw new IOException("The package manifest is too large. Nothing was installed.");
                try (FileOutputStream output = new FileOutputStream(manifestFile)) { output.write(metadata); }
            }
            // Persist bindings before activating content. If installation is
            // interrupted, retaining a reserved ID is safer than losing the
            // source identity while an independent learner record survives.
            saveLessonIdentities(identities);
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

    private void validatePublications(JSONObject manifest) throws IOException {
        JSONArray books = manifest.optJSONArray("books");
        if (!manifest.has("books")) return;
        if (books == null) throw new IOException("The package contains invalid publication metadata. Nothing was installed.");
        for (int i = 0; i < books.length(); i++) {
            JSONObject book = books.optJSONObject(i);
            JSONObject original = book == null ? null : approvedBooks.get(book.optString("id"));
            if (original == null) throw new IOException("This package is from a different book. Only the app's approved source collection can be imported.");
            for (String key : new String[]{"title", "author", "year", "totalQuestions"}) {
                Object value = book.opt(key);
                if (value != null && value != JSONObject.NULL && !String.valueOf(value).equals(String.valueOf(original.opt(key)))) {
                    throw new IOException("The package publication details differ from the approved source. Nothing was installed.");
                }
            }
        }
    }

    private void validateLessons(JSONArray lessons, File directory) throws IOException {
        validateLessons(lessons, directory, true);
    }

    private void validateLessons(JSONArray lessons, File directory, boolean requireFiles) throws IOException {
        if (lessons == null || lessons.length() > 20000) throw new IOException("The package must contain a valid lesson list.");
        Set<String> ids = new HashSet<>();
        for (int i = 0; i < lessons.length(); i++) {
            JSONObject lesson = lessons.optJSONObject(i);
            Object value = lesson == null ? null : lesson.opt("id");
            if (!validLessonId(value) || !ids.add((String) value)) {
                throw new IOException("The package contains an invalid or duplicate lesson ID. Nothing was installed.");
            }
            if (!text(lesson.opt("title")) || !integer(lesson.opt("version"), 1, 1000000000, 1)) {
                throw new IOException("The package contains an invalid lesson title or revision. Nothing was installed.");
            }
            JSONObject source = lesson.optJSONObject("source");
            JSONObject book = source == null ? null : approvedBooks.get(source.optString("bookId"));
            if (book == null || !integer(source.opt("questionNumber"), 1, book.optInt("totalQuestions"), -1)) {
                throw new IOException("Each lesson must identify its source book and question. Nothing was installed.");
            }
            media(directory, lesson.opt("audioUrl"), false, requireFiles);
            media(directory, lesson.opt("poster"), true, requireFiles);
            JSONArray scenes = lesson.optJSONArray("scenes");
            if (scenes == null || scenes.length() == 0) throw new IOException("A lesson has no playable scenes. Nothing was installed.");
            double previousEnd = 0;
            for (int j = 0; j < scenes.length(); j++) {
                JSONObject scene = scenes.optJSONObject(j);
                if (scene == null || !number(scene.opt("start")) || !number(scene.opt("end"))) {
                    throw new IOException("A lesson contains invalid scene metadata. Nothing was installed.");
                }
                double start = ((Number) scene.opt("start")).doubleValue(), end = ((Number) scene.opt("end")).doubleValue();
                if (start < 0 || end <= start || start < previousEnd - .001) {
                    throw new IOException("A lesson contains invalid scene timing. Nothing was installed.");
                }
                previousEnd = end;
                media(directory, scene.opt("image"), true, requireFiles);
            }
            JSONObject quiz = lesson.optJSONObject("quiz");
            JSONArray choices = quiz == null ? null : quiz.optJSONArray("options");
            if (quiz == null || !text(quiz.opt("prompt")) || choices == null || choices.length() < 2
                || !integer(quiz.opt("correctIndex"), 0, choices.length() - 1, -1)) {
                throw new IOException("A lesson contains an invalid question or answer. Nothing was installed.");
            }
            for (int j = 0; j < choices.length(); j++) if (!text(choices.opt(j))) {
                throw new IOException("A lesson contains an invalid answer option. Nothing was installed.");
            }
            JSONArray images = lesson.optJSONArray("realImages");
            if (lesson.has("realImages") && images == null) throw new IOException("A lesson contains invalid clinical-image metadata. Nothing was installed.");
            validateImages(images, directory, requireFiles);
            JSONObject presentation = lesson.optJSONObject("presentation");
            if (lesson.has("presentation") && presentation == null) throw new IOException("A lesson contains invalid presentation metadata. Nothing was installed.");
            if (presentation != null) {
                JSONObject gallery = presentation.optJSONObject("clinicalGallery");
                if (gallery != null) validateImages(gallery.optJSONArray("images"), directory, requireFiles);
            }
        }
    }

    private static void validateImages(JSONArray images, File directory, boolean requireFiles) throws IOException {
        if (images == null) return;
        for (int i = 0; i < images.length(); i++) {
            JSONObject image = images.optJSONObject(i);
            if (image == null) throw new IOException("A lesson contains invalid image metadata. Nothing was installed.");
            media(directory, image.opt("url"), true, requireFiles);
        }
    }

    private static void media(File directory, Object value, boolean image, boolean requireFiles) throws IOException {
        if (!text(value)) throw new IOException("A lesson is missing a required media reference. Nothing was installed.");
        String path = (String) value;
        String ext = extension(path);
        boolean supported = image ? Arrays.asList("jpg", "jpeg", "png", "webp", "gif", "avif").contains(ext)
            : Arrays.asList("mp3", "m4a", "aac", "ogg", "opus", "wav", "mp4", "webm").contains(ext);
        File file = safeChild(directory, path);
        if (!supported || (requireFiles && (!file.isFile() || file.length() == 0))) {
            throw new IOException("A lesson media file is missing or unsupported: " + path + ". Nothing was installed.");
        }
    }

    private static boolean text(Object value) { return value instanceof String && !((String) value).trim().isEmpty(); }
    private static boolean validLessonId(Object value) {
        return value instanceof String && ((String) value).matches("[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
            && !value.equals("__proto__") && !value.equals("constructor") && !value.equals("prototype");
    }
    private static boolean number(Object value) { return value instanceof Number && Double.isFinite(((Number) value).doubleValue()); }
    private static boolean integer(Object value, int min, int max, int missing) {
        if (value == null) value = missing;
        if (!number(value)) return false;
        double n = ((Number) value).doubleValue();
        return Math.floor(n) == n && n >= min && n <= max;
    }

    private static JSONArray readLessons(File directory, JSONObject manifest) throws Exception {
        JSONArray lessons = manifest.optJSONArray("lessons");
        if (lessons != null) return lessons;
        File file = safeChild(directory, manifest.optString("lessonsFile", "lessons.json"));
        if (!file.isFile()) throw new IOException("Package must contain its lessons JSON file.");
        String json = readText(file, 5 * 1024 * 1024).trim();
        return json.startsWith("[") ? new JSONArray(json) : new JSONObject(json).optJSONArray("lessons");
    }

    private void validateReplacement(File installed, File staging, JSONArray incoming, boolean replacingSamePackage, JSONObject retainedHashes) throws Exception {
        // Explicit empty correction packs still withdraw a collection. They do
        // not rewrite any stable lesson or personal learning record.
        if (incoming.length() == 0) return;
        JSONArray previous;
        JSONObject manifest;
        try {
            manifest = new JSONObject(readText(new File(installed, "manifest.json"), 5 * 1024 * 1024));
            previous = readLessons(installed, manifest);
        } catch (Exception unreadable) {
            // A valid new package can repair an already unreadable installation.
            // Only readable old identities can establish a revision floor.
            return;
        }
        if (previous == null) return;
        Map<String, JSONObject> byId = new HashMap<>();
        for (int i = 0; i < previous.length(); i++) {
            JSONObject old = previous.optJSONObject(i);
            if (old == null) continue;
            JSONObject known = byId.get(old.optString("id"));
            if (known == null || old.optInt("version", 1) > known.optInt("version", 1)) byId.put(old.optString("id"), old);
        }
        for (int i = 0; i < incoming.length(); i++) {
            JSONObject replacement = incoming.getJSONObject(i);
            JSONObject old = byId.get(replacement.getString("id"));
            if (old == null) continue;
            JSONObject before = old.optJSONObject("source"), after = replacement.getJSONObject("source");
            if (before != null && ((before.has("bookId") && !before.optString("bookId").equals(after.getString("bookId")))
                || (before.has("questionNumber") && before.optInt("questionNumber", -1) != after.getInt("questionNumber")))) {
                throw new IOException("An existing lesson ID points to a different source question. The installed lesson was preserved.");
            }
            if (replacingSamePackage && replacement.optInt("version", 1) < old.optInt("version", 1)) {
                throw new IOException("This package contains an older revision of an installed lesson. The newer lesson was preserved.");
            }
            if (replacement.optInt("version", 1) == old.optInt("version", 1)) {
                boolean readable = true;
                try { validateLessons(new JSONArray().put(old), installed, false); }
                catch (IOException invalid) { readable = false; }
                if (readable && !sameJson(old, replacement)) {
                    throw new IOException("This lesson changed without a higher revision number. The installed lesson was preserved.");
                }
                validatePinnedMedia(manifest, replacement, staging, retainedHashes);
            }
        }
    }

    /** Compare JSON meaning, not serialized object-key order or numeric spelling. */
    private static boolean sameJson(Object first, Object second) {
        if (first == null || first == JSONObject.NULL) return second == null || second == JSONObject.NULL;
        if (first instanceof JSONObject && second instanceof JSONObject) {
            JSONObject a = (JSONObject) first, b = (JSONObject) second;
            if (a.length() != b.length()) return false;
            java.util.Iterator<String> keys = a.keys();
            while (keys.hasNext()) { String key = keys.next(); if (!b.has(key) || !sameJson(a.opt(key), b.opt(key))) return false; }
            return true;
        }
        if (first instanceof JSONArray && second instanceof JSONArray) {
            JSONArray a = (JSONArray) first, b = (JSONArray) second;
            if (a.length() != b.length()) return false;
            for (int i = 0; i < a.length(); i++) if (!sameJson(a.opt(i), b.opt(i))) return false;
            return true;
        }
        if (first instanceof Number && second instanceof Number) {
            return new BigDecimal(first.toString()).compareTo(new BigDecimal(second.toString())) == 0;
        }
        return first.equals(second);
    }

    private static void validatePinnedMedia(JSONObject manifest, JSONObject lesson, File staging, JSONObject retainedHashes) throws Exception {
        JSONObject hashes = manifest.optJSONObject("sha256");
        if (hashes == null) return; // Legacy hashless media has no trustworthy byte baseline.
        Set<String> paths = new HashSet<>();
        for (String key : new String[]{"audioUrl", "poster", "videoUrl"}) if (text(lesson.opt(key))) paths.add(lesson.getString(key));
        JSONArray scenes = lesson.getJSONArray("scenes");
        for (int i = 0; i < scenes.length(); i++) paths.add(scenes.getJSONObject(i).getString("image"));
        addImagePaths(paths, lesson.optJSONArray("realImages"));
        JSONObject presentation = lesson.optJSONObject("presentation");
        JSONObject gallery = presentation == null ? null : presentation.optJSONObject("clinicalGallery");
        if (gallery != null) addImagePaths(paths, gallery.optJSONArray("images"));
        for (String path : paths) {
            String expected = hashes.optString(path, "").toLowerCase(Locale.ROOT);
            if (!expected.matches("[a-f0-9]{64}")) continue;
            File file = safeChild(staging, path);
            if (!file.isFile() || !expected.equals(sha256(file))) {
                throw new IOException("Lesson media changed without a higher revision number. The installed lesson was preserved.");
            }
            retainedHashes.put(path, expected);
        }
    }

    private static void addImagePaths(Set<String> paths, JSONArray images) throws Exception {
        if (images != null) for (int i = 0; i < images.length(); i++) paths.add(images.getJSONObject(i).getString("url"));
    }

    private JSONObject lessonIdentities(File[] installedPackages, JSONArray incoming) throws Exception {
        JSONObject identities = new JSONObject();
        File index = new File(root, IDENTITY_INDEX);
        if (index.exists()) {
            try {
                JSONObject saved = new JSONObject(readText(index, MAX_IDENTITY_BYTES));
                if (!integer(saved.opt("schemaVersion"), 1, 1, -1)) throw new IOException("Unsupported identity index.");
                identities = saved.getJSONObject("lessons");
                java.util.Iterator<String> ids = identities.keys();
                while (ids.hasNext()) {
                    String id = ids.next();
                    JSONObject binding = identities.optJSONObject(id);
                    if (!validLessonId(id) || !(ambiguousBinding(binding) || (validBinding(binding) && !binding.has("ambiguous")))) throw new IOException("Invalid identity record.");
                }
            } catch (Exception unreadable) {
                throw new IOException("The saved lesson identity index could not be read. Nothing was installed; your existing lessons and learning data were preserved.", unreadable);
            }
        }
        Set<String> savedIds = new HashSet<>();
        java.util.Iterator<String> saved = identities.keys();
        while (saved.hasNext()) savedIds.add(saved.next());
        // Bootstrap only identities that can actually be read. An older broken
        // installation cannot establish invented mappings for unseen history.
        // Saved bindings remain authoritative. Conflicting pre-index records
        // establish only a denied ID, never a source chosen by folder order.
        // That lets empty corrections remove broken legacy packs safely.
        for (File folder : installedPackages) {
            if (!validId(folder.getName()) || !folder.isDirectory()) continue;
            JSONArray lessons;
            try { lessons = readLessons(folder, new JSONObject(readText(new File(folder, "manifest.json"), 5 * 1024 * 1024))); }
            catch (Exception unreadable) { continue; }
            if (lessons == null) continue;
            for (int i = 0; i < lessons.length(); i++) {
                JSONObject lesson = lessons.optJSONObject(i);
                if (lesson != null && validLessonId(lesson.opt("id")) && validBinding(lesson.optJSONObject("source"))) {
                    String id = lesson.getString("id");
                    if (savedIds.contains(id)) continue;
                    JSONObject known = identities.optJSONObject(id), source = lesson.getJSONObject("source");
                    if (known == null) rememberIdentity(identities, id, source);
                    else if (!ambiguousBinding(known) && !sameBinding(known, source)) identities.put(id, new JSONObject().put("ambiguous", true));
                }
            }
        }
        for (int i = 0; i < incoming.length(); i++) {
            JSONObject lesson = incoming.getJSONObject(i);
            rememberIdentity(identities, lesson.getString("id"), lesson.getJSONObject("source"));
        }
        return identities;
    }

    private static boolean validBinding(JSONObject source) {
        return source != null && text(source.opt("bookId")) && integer(source.opt("questionNumber"), 1, 10000000, -1);
    }

    private static boolean ambiguousBinding(JSONObject source) {
        return source != null && source.length() == 1 && Boolean.TRUE.equals(source.opt("ambiguous"));
    }

    private static boolean sameBinding(JSONObject first, JSONObject second) {
        return first.optString("bookId").equals(second.optString("bookId")) && first.optInt("questionNumber", -1) == second.optInt("questionNumber", -1);
    }

    private static void rememberIdentity(JSONObject identities, String id, JSONObject source) throws Exception {
        JSONObject known = identities.optJSONObject(id);
        if (ambiguousBinding(known)) {
            throw new IOException("This lesson ID has conflicting source identities from an older installation. Its source cannot be chosen automatically; nothing was installed and learning data was preserved.");
        }
        if (known != null && !sameBinding(known, source)) {
            throw new IOException("An existing lesson ID points to a different source question. Existing lessons and learning data were preserved.");
        }
        identities.put(id, new JSONObject().put("bookId", source.getString("bookId")).put("questionNumber", source.getInt("questionNumber")));
    }

    private void saveLessonIdentities(JSONObject identities) throws IOException {
        File temporary = new File(root, ".staging-identities-" + UUID.randomUUID());
        try {
            byte[] bytes = new JSONObject().put("schemaVersion", 1).put("lessons", identities).toString().getBytes(StandardCharsets.UTF_8);
            if (bytes.length > MAX_IDENTITY_BYTES) throw new IOException("The identity index is too large.");
            try (FileOutputStream output = new FileOutputStream(temporary)) { output.write(bytes); output.getFD().sync(); }
            Files.move(temporary.toPath(), new File(root, IDENTITY_INDEX).toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } catch (Exception failure) {
            throw new IOException("Cannot save lesson identity history. Nothing was installed; your existing lessons and learning data were preserved.", failure);
        } finally { temporary.delete(); }
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
