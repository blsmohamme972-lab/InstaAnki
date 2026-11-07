package com.instaanki.app;

/** Tests the downloader's real URL gate without contacting third-party endpoints. */
public final class PackDownloaderTest {
    public static void main(String[] args) throws Exception {
        String[] valid = {
            "https://github.com/example/repo/releases/download/v1/pack.zip",
            "https://api.github.com/repos/example/repo/releases/assets/123",
            "https://release-assets.githubusercontent.com/github-production-release-asset/pack?signature=test",
            "https://raw.githubusercontent.com/example/repo/main/pack.zip",
        };
        String[] invalid = {
            "http://github.com/example/pack.zip",
            "https://github.com.evil.example/pack.zip",
            "https://github.com@evil.example/pack.zip",
            "https://user:password@github.com/example/pack.zip",
            "https://github.com:8443/example/pack.zip",
            "https://github.com/example/pack.zip#fragment",
            "https://127.0.0.1/pack.zip",
            "file:///data/data/com.instaanki.app/state",
            "https://github.com/example/pack.zip\nInjected: yes",
        };
        for (String address : valid) {
            PackDownloader.validate(address);
            System.out.println("PASS allowed HTTPS release URL");
        }
        for (String address : invalid) {
            boolean rejected = false;
            try { PackDownloader.validate(address); } catch (Exception expected) { rejected = true; }
            if (!rejected) throw new AssertionError("Unsafe URL was accepted: " + address);
            System.out.println("PASS unsafe URL rejected");
        }
        System.out.println("All " + (valid.length + invalid.length) + " URL validation assertions passed.");
    }
}
