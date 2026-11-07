package com.instaanki.app.ota;

import java.io.ByteArrayOutputStream;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/** Downloads from the update channel (a GitHub Release; github.com redirects to its CDN over HTTPS). */
public final class HttpFetcher implements BundleInstaller.Fetcher {

    private final String baseUrl;

    public HttpFetcher(String baseUrl) {
        this.baseUrl = baseUrl.endsWith("/") ? baseUrl : baseUrl + "/";
    }

    public InputStream openName(String name) throws IOException {
        URL url = new URL(baseUrl + name);
        if (!"https".equals(url.getProtocol())) throw new IOException("update channel must use https");
        HttpURLConnection c = (HttpURLConnection) url.openConnection();
        c.setConnectTimeout(10_000);
        c.setReadTimeout(30_000);
        c.setInstanceFollowRedirects(true);
        c.setUseCaches(false);
        c.setRequestProperty("User-Agent", "InstaAnki-Shell");
        c.setRequestProperty("Cache-Control", "no-cache");
        int code = c.getResponseCode();
        if (code == 404) {
            c.disconnect();
            throw new NotFound(name);
        }
        if (code != 200) {
            c.disconnect();
            throw new IOException("HTTP " + code + " for " + name);
        }
        final HttpURLConnection conn = c;
        return new FilterInputStream(c.getInputStream()) {
            @Override
            public void close() throws IOException {
                try {
                    super.close();
                } finally {
                    conn.disconnect();
                }
            }
        };
    }

    public byte[] fetchBytes(String name, int maxBytes) throws IOException {
        try (InputStream in = openName(name)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[16 * 1024];
            int n;
            while ((n = in.read(buf)) != -1) {
                if (out.size() + n > maxBytes) throw new IOException(name + " is too large");
                out.write(buf, 0, n);
            }
            return out.toByteArray();
        }
    }

    @Override
    public InputStream open(String sha256) throws IOException {
        return openName(sha256);
    }

    /** The channel has no published manifest yet. */
    public static final class NotFound extends IOException {

        public NotFound(String name) {
            super("not found: " + name);
        }
    }
}
