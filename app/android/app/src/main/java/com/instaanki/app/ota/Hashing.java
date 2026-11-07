package com.instaanki.app.ota;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** SHA-256 helpers and a minimal Base64 decoder (java.util.Base64 needs API 26, minSdk is 24). */
public final class Hashing {

    private Hashing() {}

    public static MessageDigest sha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    public static String hex(byte[] bytes) {
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) sb.append(String.format("%02x", b & 0xff));
        return sb.toString();
    }

    public static String sha256Hex(byte[] data) {
        return hex(sha256().digest(data));
    }

    /** Copies `in` to `out` (out may be null) and returns {sha256 hex, byte count}. */
    public static Result copyAndHash(InputStream in, OutputStream out, long maxBytes) throws IOException {
        MessageDigest md = sha256();
        byte[] buf = new byte[64 * 1024];
        long total = 0;
        int n;
        while ((n = in.read(buf)) != -1) {
            total += n;
            if (total > maxBytes) throw new IOException("file exceeds " + maxBytes + " bytes");
            md.update(buf, 0, n);
            if (out != null) out.write(buf, 0, n);
        }
        return new Result(hex(md.digest()), total);
    }

    public static final class Result {

        public final String sha256;
        public final long size;

        Result(String sha256, long size) {
            this.sha256 = sha256;
            this.size = size;
        }
    }

    private static final String ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

    /** Standard Base64 (with or without padding/whitespace). */
    public static byte[] base64Decode(String s) throws OtaException {
        String clean = s.replaceAll("\\s+", "");
        while (clean.endsWith("=")) clean = clean.substring(0, clean.length() - 1);
        if (clean.length() % 4 == 1) throw new OtaException("invalid base64 length");
        byte[] out = new byte[clean.length() * 3 / 4];
        int buffer = 0;
        int bits = 0;
        int pos = 0;
        for (int i = 0; i < clean.length(); i++) {
            int v = ALPHABET.indexOf(clean.charAt(i));
            if (v < 0) throw new OtaException("invalid base64 character");
            buffer = (buffer << 6) | v;
            bits += 6;
            if (bits >= 8) {
                bits -= 8;
                out[pos++] = (byte) ((buffer >> bits) & 0xff);
            }
        }
        if (pos == out.length) return out;
        byte[] trimmed = new byte[pos];
        System.arraycopy(out, 0, trimmed, 0, pos);
        return trimmed;
    }
}
