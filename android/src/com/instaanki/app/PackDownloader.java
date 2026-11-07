package com.instaanki.app;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/** Downloads public GitHub release assets without storing credentials or executing downloaded code. */
final class PackDownloader {
    private static final long MAX_DOWNLOAD = 512L * 1024 * 1024;
    private static final long MAX_DURATION_NANOS = 10L * 60 * 1000 * 1000 * 1000;
    private static final Set<String> ALLOWED_HOSTS = new HashSet<>(Arrays.asList(
        "github.com", "api.github.com", "raw.githubusercontent.com", "objects.githubusercontent.com",
        "release-assets.githubusercontent.com", "github-releases.githubusercontent.com"));

    interface Progress { void update(long received, long total); }

    static void requireCompatibleApp(double minimumAppVersionCode, int installedAppVersionCode) throws IOException {
        if (Double.isNaN(minimumAppVersionCode) || Double.isInfinite(minimumAppVersionCode)
                || minimumAppVersionCode < 1 || minimumAppVersionCode > Integer.MAX_VALUE
                || minimumAppVersionCode != Math.rint(minimumAppVersionCode)) {
            throw new IOException("The update catalog has an invalid minimum app version. Nothing was installed.");
        }
        if (installedAppVersionCode < 1) {
            throw new IOException("The installed app version could not be verified. Nothing was installed.");
        }
        if (installedAppVersionCode < minimumAppVersionCode) {
            throw new IOException("This lesson package needs a newer InstaAnki app. Update the app before downloading. Nothing was installed.");
        }
    }

    static File downloadCompatible(String address, String expectedHash, long catalogBytes,
                                   double minimumAppVersionCode, int installedAppVersionCode,
                                   File cache, Progress progress) throws Exception {
        // Check compatibility before URL handling, cache creation, or a network request.
        requireCompatibleApp(minimumAppVersionCode, installedAppVersionCode);
        return download(address, expectedHash, catalogBytes, cache, progress);
    }

    static File download(String address, String expectedHash, File cache, Progress progress) throws Exception {
        return download(address, expectedHash, -1, cache, progress);
    }

    static File download(String address, String expectedHash, long catalogBytes, File cache, Progress progress) throws Exception {
        if (expectedHash == null || !expectedHash.matches("(?i)[a-f0-9]{64}")) {
            throw new IOException("The catalog must provide the package's SHA-256 checksum.");
        }
        if (catalogBytes == 0 || catalogBytes < -1 || catalogBytes > MAX_DOWNLOAD) {
            throw new IOException("The catalog package size is invalid or exceeds the 512 MiB limit.");
        }
        URL url = validate(address);
        if (!cache.isDirectory() && !cache.mkdirs()) throw new IOException("Unable to create download storage.");
        File target = File.createTempFile("instaanki-pack-", ".zip", cache);
        boolean complete = false;
        long started = System.nanoTime();
        try {
            for (int redirects = 0; redirects <= 5; redirects++) {
                HttpURLConnection connection = (HttpURLConnection) url.openConnection();
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(15000);
                connection.setReadTimeout(30000);
                connection.setRequestProperty("User-Agent", "InstaAnki-Android/0.1");
                connection.setRequestProperty("Accept", "application/octet-stream");
                connection.setRequestProperty("Accept-Encoding", "identity");
                try {
                    int code = connection.getResponseCode();
                    if (code == 301 || code == 302 || code == 303 || code == 307 || code == 308) {
                        String location = connection.getHeaderField("Location");
                        if (location == null || redirects == 5) throw new IOException("The download has too many redirects.");
                        url = validate(new URL(url, location).toString());
                        continue;
                    }
                    if (code != 200) {
                        if (code == 401 || code == 403 || code == 404) {
                            throw new IOException("This GitHub package is unavailable. This version supports public release assets; use local ZIP import for private content.");
                        }
                        throw new IOException("The content server returned HTTP " + code + ".");
                    }
                    long expectedBytes = connection.getContentLengthLong();
                    if (expectedBytes > MAX_DOWNLOAD) throw new IOException("This package exceeds the 512 MiB download limit.");
                    if (catalogBytes > 0 && expectedBytes >= 0 && catalogBytes != expectedBytes) throw new IOException("The download size does not match the update catalog. Nothing was installed.");
                    long progressBytes = catalogBytes > 0 ? catalogBytes : expectedBytes;
                    MessageDigest digest = MessageDigest.getInstance("SHA-256");
                    long received = 0;
                    long previousReport = 0;
                    progress.update(0, progressBytes);
                    try (InputStream input = connection.getInputStream(); FileOutputStream output = new FileOutputStream(target)) {
                        byte[] buffer = new byte[64 * 1024]; int count;
                        while ((count = input.read(buffer)) != -1) {
                            received += count;
                            if (received > MAX_DOWNLOAD || System.nanoTime() - started > MAX_DURATION_NANOS) {
                                throw new IOException("The download exceeded its size or time limit.");
                            }
                            if (catalogBytes > 0 && received > catalogBytes) throw new IOException("The downloaded file is larger than the update catalog specifies. Nothing was installed.");
                            digest.update(buffer, 0, count); output.write(buffer, 0, count);
                            long now = System.nanoTime();
                            if (now - previousReport >= 350_000_000L) { progress.update(received, progressBytes); previousReport = now; }
                        }
                        output.getFD().sync();
                    }
                    if (expectedBytes >= 0 && expectedBytes != received) throw new IOException("The download was interrupted. Please try again.");
                    if (catalogBytes > 0 && received != catalogBytes) throw new IOException("The download is incomplete or differs from the update catalog. Nothing was installed. Try downloading it again.");
                    StringBuilder hex = new StringBuilder();
                    for (byte b : digest.digest()) hex.append(String.format(Locale.ROOT, "%02x", b & 255));
                    if (!hex.toString().equalsIgnoreCase(expectedHash)) throw new IOException("The package checksum does not match the catalog. Nothing was installed.");
                    progress.update(received, received);
                    complete = true;
                    return target;
                } finally { connection.disconnect(); }
            }
            throw new IOException("Unable to resolve the download URL.");
        } finally { if (!complete) target.delete(); }
    }

    static URL validate(String address) throws Exception {
        if (address == null || address.length() > 16384 || address.matches("(?s).*\\p{Cntrl}.*")) {
            throw new IOException("The download URL is invalid.");
        }
        URL url = new URL(address);
        if (!"https".equalsIgnoreCase(url.getProtocol()) || url.getUserInfo() != null || url.getRef() != null
            || (url.getPort() != -1 && url.getPort() != 443)
            || !ALLOWED_HOSTS.contains(url.getHost().toLowerCase(Locale.ROOT))) {
            throw new IOException("Use an HTTPS public GitHub release URL. Other download hosts are not enabled in this version.");
        }
        return url;
    }
}
