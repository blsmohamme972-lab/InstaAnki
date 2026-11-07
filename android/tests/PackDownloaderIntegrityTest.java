package com.instaanki.app;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLConnection;
import java.net.URLStreamHandler;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;

/** Deterministic transport fixtures exercise the real downloader; no external network request is made. */
public final class PackDownloaderIntegrityTest {
    private static byte[] body;
    private static long declared;
    private static int status = 200;
    private static int passed;
    private static int connections;
    private static class Response extends HttpURLConnection {
        Response(URL url) { super(url); }
        @Override public void connect() { }
        @Override public void disconnect() { }
        @Override public boolean usingProxy() { return false; }
        @Override public int getResponseCode() { return status; }
        @Override public long getContentLengthLong() { return declared; }
        @Override public InputStream getInputStream() { return new ByteArrayInputStream(body); }
        @Override public String getHeaderField(String name) { return "Location".equals(name) ? "https://unexpected.example/asset.zip" : null; }
    }
    private static String sha(byte[] bytes) throws Exception {
        StringBuilder out = new StringBuilder();for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes)) out.append(String.format("%02x", value & 255));return out.toString();
    }
    private static void ok(boolean result, String label) { if (!result) throw new AssertionError(label); passed++; System.out.println("PASS " + label); }
    private static void rejects(File cache, String hash, long bytes, String label) throws Exception {
        boolean refused = false;try { PackDownloader.download("https://github.com/example/repo/releases/download/v1/pack.zip", hash, bytes, cache, (got, total) -> {}); } catch (Exception expected) { refused = true; }
        ok(refused, label);ok(cache.listFiles().length == 0, label + " removes the partial file");
    }
    private static void rejectsVersion(File cache, String hash, long bytes, double minimum, int installed, String label) throws Exception {
        int before = connections;
        boolean refused = false;
        try { PackDownloader.downloadCompatible("https://github.com/example/repo/releases/download/v1/pack.zip", hash, bytes,
                minimum, installed, cache, (got, total) -> {}); }
        catch (java.io.IOException expected) { refused = expected.getMessage().contains("app version") || expected.getMessage().contains("newer InstaAnki app"); }
        ok(refused, label);
        ok(connections == before && !cache.exists(), label + " makes no network request or cache directory");
    }
    public static void main(String[] args) throws Exception {
        URL.setURLStreamHandlerFactory(protocol -> "https".equals(protocol) ? new URLStreamHandler() {
            @Override protected URLConnection openConnection(URL url) { connections++;return new Response(url); }
        } : null);
        File cache = Files.createTempDirectory("instaanki-download-integrity-").toFile();
        byte[] original = "complete fixture download".getBytes(StandardCharsets.UTF_8);String hash = sha(original);
        body = original;declared = original.length;
        File incompatibleCache = new File(cache, "must-not-create");
        rejectsVersion(incompatibleCache, hash, original.length, 3, 2, "version 2 cannot download version 3 presentation");
        rejectsVersion(incompatibleCache, hash, original.length, 4, 3, "current app cannot download future-version presentation");
        for (double invalid : new double[] {0, -1, 3.5, Double.NaN, Double.POSITIVE_INFINITY, (double)Integer.MAX_VALUE + 1}) {
            rejectsVersion(incompatibleCache, hash, original.length, invalid, 3, "invalid minimum " + invalid + " rejected");
        }
        rejectsVersion(incompatibleCache, hash, original.length, 3, 0, "unknown installed app version rejected");
        File compatible = PackDownloader.downloadCompatible("https://github.com/example/repo/releases/download/v1/pack.zip", hash,
                original.length, 3, 3, cache, (got, total) -> {});
        ok(java.util.Arrays.equals(Files.readAllBytes(compatible.toPath()), original), "matching app version downloads the verified bytes");compatible.delete();
        File received = PackDownloader.download("https://github.com/example/repo/releases/download/v1/pack.zip", hash, original.length, cache, (got, total) -> {});
        ok(java.util.Arrays.equals(Files.readAllBytes(received.toPath()), original), "matching catalog size and checksum return the exact bytes");received.delete();
        rejects(cache, hash, original.length + 1, "catalog/header size mismatch rejected");
        body = java.util.Arrays.copyOf(original, original.length - 3);declared = -1;
        rejects(cache, hash, original.length, "truncated body rejected when HTTP length is absent");
        body = original;declared = -1;
        rejects(cache, hash, original.length - 1, "body larger than catalog rejected");
        body = java.util.Arrays.copyOf(original, original.length - 2);declared = original.length;
        rejects(cache, hash, original.length, "interrupted declared-length response rejected");
        body = original.clone();body[0] ^= 1;declared = original.length;
        rejects(cache, hash, original.length, "same-length corrupted body rejected by SHA-256");
        status = 302;body = original;
        rejects(cache, hash, original.length, "redirect to unapproved host rejected");
        System.out.println("All " + passed + " downloader integrity assertions passed.");
    }
}
