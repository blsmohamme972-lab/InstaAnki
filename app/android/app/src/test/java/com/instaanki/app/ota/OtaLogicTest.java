package com.instaanki.app.ota;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Random;
import java.util.Set;
import org.junit.Test;

public class OtaLogicTest {

    // ------------------------------------------------------------ SemVer

    @Test
    public void semverOrdering() throws Exception {
        assertTrue(SemVer.isNewer("0.2.0", "0.1.9"));
        assertTrue(SemVer.isNewer("1.0.0", "0.99.99"));
        assertTrue(SemVer.isNewer("0.1.10", "0.1.9"));
        assertFalse(SemVer.isNewer("0.1.0", "0.1.0"));
        assertFalse(SemVer.isNewer("0.1.0", "0.2.0"));
        assertFalse(SemVer.isNewer("garbage", "0.0.1"));
        assertEquals("1.2.3", SemVer.parse("1.2.3").toString());
        for (String bad : new String[] { "1.2", "01.2.3", "1.2.3-beta", "v1.2.3", "", "1..3" }) {
            assertFalse(bad, SemVer.isValid(bad));
        }
    }

    // ------------------------------------------------------------ Hashing

    @Test
    public void base64MatchesJdk() throws Exception {
        Random rnd = new Random(42);
        for (int len = 0; len < 70; len++) {
            byte[] data = new byte[len];
            rnd.nextBytes(data);
            String enc = java.util.Base64.getEncoder().encodeToString(data);
            assertArrayEquals(data, Hashing.base64Decode(enc));
            assertArrayEquals(data, Hashing.base64Decode(enc.replace("=", "") + "\n"));
        }
        try {
            Hashing.base64Decode("ab$d");
            fail();
        } catch (OtaException expected) {
            // ok
        }
    }

    @Test
    public void sha256KnownVector() {
        assertEquals(
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            Hashing.sha256Hex("abc".getBytes(StandardCharsets.US_ASCII))
        );
    }

    // ------------------------------------------------------------ Manifest

    static String sha(String s) {
        return Hashing.sha256Hex(s.getBytes(StandardCharsets.UTF_8));
    }

    static String manifestJson(String version, int minShell, String... pathAndContent) {
        StringBuilder files = new StringBuilder();
        for (int i = 0; i < pathAndContent.length; i += 2) {
            if (files.length() > 0) files.append(',');
            String content = pathAndContent[i + 1];
            files
                .append("{\"path\":\"")
                .append(pathAndContent[i])
                .append("\",\"sha256\":\"")
                .append(sha(content))
                .append("\",\"size\":")
                .append(content.getBytes(StandardCharsets.UTF_8).length)
                .append('}');
        }
        return "{\"bundleVersion\":\"" + version + "\",\"minShellVersion\":" + minShell + ",\"notes\":\"n\",\"files\":[" + files + "]}";
    }

    @Test
    public void manifestParses() throws Exception {
        OtaManifest m = OtaManifest.parse(
            manifestJson("0.2.0", 1, "index.html", "<html>", "assets/index-AbC_1.js", "js").getBytes(StandardCharsets.UTF_8)
        );
        assertEquals("0.2.0", m.bundleVersion);
        assertEquals(1, m.minShellVersion);
        assertEquals(2, m.files.size());
        assertEquals(8, m.totalSize());
    }

    @Test
    public void manifestRejectsUnsafeOrBrokenInput() {
        String[] bad = {
            manifestJson("0.2.0", 1, "assets/a.js", "x"), // no index.html
            manifestJson("0.2.0", 1, "index.html", "x", "../evil.js", "y"),
            manifestJson("0.2.0", 1, "index.html", "x", "/abs.js", "y"),
            manifestJson("0.2.0", 1, "index.html", "x", "a//b.js", "y"),
            manifestJson("0.2.0", 1, "index.html", "x", "a\\\\b.js", "y"),
            manifestJson("0.2.0", 1, "index.html", "x", "index.html", "y"), // duplicate
            manifestJson("0.2", 1, "index.html", "x"),
            manifestJson("0.2.0", 0, "index.html", "x"),
            "{\"bundleVersion\":\"0.2.0\",\"minShellVersion\":1,\"files\":[{\"path\":\"index.html\",\"sha256\":\"ABC\",\"size\":1}]}",
            "not json",
        };
        for (String json : bad) {
            try {
                OtaManifest.parse(json.getBytes(StandardCharsets.UTF_8));
                fail("accepted: " + json);
            } catch (OtaException expected) {
                // ok
            }
        }
    }

    // ------------------------------------------------------------ StartupLogic

    static final class MapStore implements OtaState.Store {

        final Map<String, String> map = new HashMap<>();

        @Override
        public String get(String key, String fallback) {
            return map.containsKey(key) ? map.get(key) : fallback;
        }

        @Override
        public void put(String key, String value) {
            map.put(key, value);
        }
    }

    static OtaState state() {
        OtaState s = new OtaState(new MapStore());
        s.setLastBinaryCode(1);
        return s;
    }

    static StartupLogic.BundleExists existing(String... versions) {
        Set<String> set = new HashSet<>(Arrays.asList(versions));
        return set::contains;
    }

    @Test
    public void firstLaunchOfAnApkUsesTheBuiltInBundle() {
        OtaState s = new OtaState(new MapStore());
        s.setCurrent("0.5.0");
        assertEquals("", StartupLogic.decideStartup(s, 1, existing("0.5.0")));
        assertEquals("", s.current());
        assertEquals(1, s.lastBinaryCode());
    }

    @Test
    public void confirmedUpdateBecomesCurrentAndOldOnesArePruned() {
        OtaState s = state();
        s.setCurrent("0.2.0");
        s.setPrevious("0.1.0");
        StartupLogic.markApplied(s, "0.3.0");
        Set<String> keep = StartupLogic.confirm(s, "0.3.0");
        assertEquals("0.3.0", s.current());
        assertEquals("0.2.0", s.previous());
        assertEquals("", s.pending());
        assertEquals(new HashSet<>(Arrays.asList("0.3.0", "0.2.0")), keep);
        assertEquals("0.3.0", StartupLogic.decideStartup(s, 1, existing("0.3.0", "0.2.0")));
    }

    @Test
    public void unconfirmedUpdateIsRolledBackAtNextStartAndNeverOfferedAgain() {
        OtaState s = state();
        s.setCurrent("0.2.0");
        StartupLogic.markApplied(s, "0.3.0"); // loaded, then the process died before notifyAppReady
        assertEquals("0.2.0", StartupLogic.decideStartup(s, 1, existing("0.2.0", "0.3.0")));
        assertEquals("0.3.0", s.rolledBackFrom());
        assertTrue(s.badVersions().contains("0.3.0"));
        assertFalse(StartupLogic.shouldOffer(s, "0.3.0", "0.2.0", "0.1.0"));
        assertTrue(StartupLogic.shouldOffer(s, "0.3.1", "0.2.0", "0.1.0"));
        // the rolled-back bundle reads rolledBackFrom, then confirms: the flag is cleared
        StartupLogic.confirm(s, "0.2.0");
        assertEquals("", s.rolledBackFrom());
        assertEquals("0.2.0", s.current());
    }

    @Test
    public void runtimeTimeoutRollsBackToBuiltIn() {
        OtaState s = state();
        StartupLogic.markApplied(s, "0.2.0");
        assertEquals("", StartupLogic.rollback(s));
        assertEquals("0.2.0", s.rolledBackFrom());
        assertEquals("", s.pending());
    }

    @Test
    public void missingBundleFoldersFallBackSafely() {
        OtaState s = state();
        s.setCurrent("0.2.0");
        s.setPending("0.3.0");
        assertEquals("", StartupLogic.decideStartup(s, 1, existing()));
        assertEquals("", s.current());
        assertEquals("", s.pending());
    }

    @Test
    public void offersOnlyNewerVersions() {
        OtaState s = state();
        assertTrue(StartupLogic.shouldOffer(s, "0.1.1", "", "0.1.0")); // running built-in 0.1.0
        assertFalse(StartupLogic.shouldOffer(s, "0.1.0", "", "0.1.0"));
        assertFalse(StartupLogic.shouldOffer(s, "0.1.5", "0.2.0", "0.1.0"));
    }
}
