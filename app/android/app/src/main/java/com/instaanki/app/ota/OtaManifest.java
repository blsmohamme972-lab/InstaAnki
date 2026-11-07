package com.instaanki.app.ota;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** latest.json: what the newest web bundle contains. Every file is addressed by its SHA-256. */
public final class OtaManifest {

    private static final Pattern SHA256 = Pattern.compile("^[0-9a-f]{64}$");
    private static final Pattern SAFE_SEGMENT = Pattern.compile("^[A-Za-z0-9._@+-]+$");

    public final String bundleVersion;
    public final int minShellVersion;
    public final String releasedAt;
    public final String notes;
    public final List<FileEntry> files;

    public static final class FileEntry {

        public final String path;
        public final String sha256;
        public final long size;

        public FileEntry(String path, String sha256, long size) {
            this.path = path;
            this.sha256 = sha256;
            this.size = size;
        }
    }

    private OtaManifest(String bundleVersion, int minShellVersion, String releasedAt, String notes, List<FileEntry> files) {
        this.bundleVersion = bundleVersion;
        this.minShellVersion = minShellVersion;
        this.releasedAt = releasedAt;
        this.notes = notes;
        this.files = Collections.unmodifiableList(files);
    }

    public long totalSize() {
        long total = 0;
        for (FileEntry f : files) total += f.size;
        return total;
    }

    public static boolean isSafePath(String path) {
        if (path == null || path.isEmpty() || path.length() > 512) return false;
        for (String seg : path.split("/", -1)) {
            if (seg.isEmpty() || seg.equals(".") || seg.equals("..") || !SAFE_SEGMENT.matcher(seg).matches()) return false;
        }
        return true;
    }

    public static OtaManifest parse(byte[] json) throws OtaException {
        try {
            JSONObject o = new JSONObject(new String(json, StandardCharsets.UTF_8));
            String version = o.getString("bundleVersion");
            if (!SemVer.isValid(version)) throw new OtaException("invalid bundleVersion: " + version);
            int minShell = o.getInt("minShellVersion");
            if (minShell < 1) throw new OtaException("invalid minShellVersion: " + minShell);

            JSONArray arr = o.getJSONArray("files");
            List<FileEntry> files = new ArrayList<>();
            Set<String> seen = new HashSet<>();
            for (int i = 0; i < arr.length(); i++) {
                JSONObject f = arr.getJSONObject(i);
                String path = f.getString("path");
                String sha = f.getString("sha256");
                long size = f.getLong("size");
                if (!isSafePath(path)) throw new OtaException("unsafe path in manifest: " + path);
                if (!SHA256.matcher(sha).matches()) throw new OtaException("invalid sha256 for " + path);
                if (size < 0) throw new OtaException("invalid size for " + path);
                if (!seen.add(path)) throw new OtaException("duplicate path in manifest: " + path);
                files.add(new FileEntry(path, sha, size));
            }
            if (!seen.contains("index.html")) throw new OtaException("manifest has no index.html");
            return new OtaManifest(version, minShell, o.optString("releasedAt", ""), o.optString("notes", ""), files);
        } catch (JSONException e) {
            throw new OtaException("invalid manifest JSON: " + e.getMessage(), e);
        }
    }
}
