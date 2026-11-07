package com.instaanki.app.ota;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Set;

/**
 * Builds a bundle folder from a manifest: files whose hash matches a local copy (the running
 * bundle) are copied, the rest are downloaded. Every file is hash-checked; the folder only
 * appears under its final name once complete.
 */
public final class BundleInstaller {

    /** Remote content by SHA-256. */
    public interface Fetcher {
        InputStream open(String sha256) throws IOException;
    }

    /** Files of the running bundle by relative path; null when missing. */
    public interface LocalSource {
        InputStream open(String path) throws IOException;
    }

    public interface Progress {
        void onFile(int done, int total);
    }

    static final long MAX_FILE_BYTES = 50L * 1024 * 1024;

    private final File root;

    public BundleInstaller(File root) {
        this.root = root;
    }

    public File dirFor(String version) {
        return new File(root, version);
    }

    public boolean exists(String version) {
        return !version.isEmpty() && new File(dirFor(version), "index.html").isFile();
    }

    /** Bytes that would have to be downloaded (files not available locally with the same hash). */
    public long bytesToDownload(OtaManifest m, LocalSource local) {
        long total = 0;
        for (OtaManifest.FileEntry f : m.files) {
            if (!localMatches(local, f)) total += f.size;
        }
        return total;
    }

    private static boolean localMatches(LocalSource local, OtaManifest.FileEntry f) {
        try (InputStream in = local.open(f.path)) {
            return in != null && Hashing.copyAndHash(in, null, MAX_FILE_BYTES).sha256.equals(f.sha256);
        } catch (IOException e) {
            return false;
        }
    }

    public File install(OtaManifest m, LocalSource local, Fetcher remote, Progress progress) throws IOException, OtaException {
        File tmp = new File(root, m.bundleVersion + ".tmp");
        File dest = dirFor(m.bundleVersion);
        deleteRecursive(tmp);
        if (!tmp.mkdirs()) throw new IOException("cannot create " + tmp);
        try {
            int done = 0;
            for (OtaManifest.FileEntry f : m.files) {
                File target = new File(tmp, f.path);
                File parent = target.getParentFile();
                if (parent != null && !parent.isDirectory() && !parent.mkdirs()) throw new IOException("cannot create " + parent);
                if (!copyIfMatches(local, f, target)) download(remote, f, target);
                done++;
                if (progress != null) progress.onFile(done, m.files.size());
            }
            deleteRecursive(dest);
            if (!tmp.renameTo(dest)) throw new IOException("cannot move bundle into place");
            return dest;
        } catch (IOException | OtaException e) {
            deleteRecursive(tmp);
            throw e;
        }
    }

    private static boolean copyIfMatches(LocalSource local, OtaManifest.FileEntry f, File target) throws IOException {
        Hashing.Result r;
        try (InputStream in = local.open(f.path)) {
            if (in == null) return false;
            try (OutputStream out = new FileOutputStream(target)) {
                r = Hashing.copyAndHash(in, out, MAX_FILE_BYTES);
            }
        } catch (IOException e) {
            if (target.exists() && !target.delete()) throw e;
            return false;
        }
        if (r.sha256.equals(f.sha256)) return true;
        if (!target.delete()) throw new IOException("cannot delete " + target);
        return false;
    }

    private static void download(Fetcher remote, OtaManifest.FileEntry f, File target) throws IOException, OtaException {
        Hashing.Result r;
        try (InputStream in = remote.open(f.sha256); OutputStream out = new FileOutputStream(target)) {
            r = Hashing.copyAndHash(in, out, MAX_FILE_BYTES);
        }
        if (!r.sha256.equals(f.sha256) || r.size != f.size) {
            throw new OtaException("hash mismatch for " + f.path);
        }
    }

    /** Deletes every bundle folder except the given versions. */
    public void retainOnly(Set<String> keep) {
        File[] children = root.listFiles();
        if (children == null) return;
        for (File c : children) {
            if (!keep.contains(c.getName())) deleteRecursive(c);
        }
    }

    static void deleteRecursive(File f) {
        if (!f.exists()) return;
        File[] children = f.listFiles();
        if (children != null) for (File c : children) deleteRecursive(c);
        //noinspection ResultOfMethodCallIgnored
        f.delete();
    }
}
