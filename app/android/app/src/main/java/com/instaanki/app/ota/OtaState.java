package com.instaanki.app.ota;

import java.util.LinkedHashSet;
import java.util.Set;

/**
 * Persistent updater state. Version "" means the bundle built into the APK.
 *
 * current  - last bundle that started correctly (notifyAppReady)
 * previous - the one before it (kept on disk for rollback)
 * pending  - a newly applied bundle that has not confirmed yet
 */
public final class OtaState {

    /** Tiny key-value abstraction: SharedPreferences on Android, a map in tests. */
    public interface Store {
        String get(String key, String fallback);

        void put(String key, String value);
    }

    private static final String K_CURRENT = "current";
    private static final String K_PREVIOUS = "previous";
    private static final String K_PENDING = "pending";
    private static final String K_ATTEMPTS = "pendingAttempts";
    private static final String K_BAD = "badVersions";
    private static final String K_ROLLED_BACK = "rolledBackFrom";
    private static final String K_BINARY = "lastBinaryCode";

    private final Store store;

    public OtaState(Store store) {
        this.store = store;
    }

    public String current() {
        return store.get(K_CURRENT, "");
    }

    public void setCurrent(String v) {
        store.put(K_CURRENT, v);
    }

    public String previous() {
        return store.get(K_PREVIOUS, "");
    }

    public void setPrevious(String v) {
        store.put(K_PREVIOUS, v);
    }

    public String pending() {
        return store.get(K_PENDING, "");
    }

    public void setPending(String v) {
        store.put(K_PENDING, v);
    }

    public int pendingAttempts() {
        try {
            return Integer.parseInt(store.get(K_ATTEMPTS, "0"));
        } catch (NumberFormatException e) {
            return 0;
        }
    }

    public void setPendingAttempts(int n) {
        store.put(K_ATTEMPTS, Integer.toString(n));
    }

    public String rolledBackFrom() {
        return store.get(K_ROLLED_BACK, "");
    }

    public void setRolledBackFrom(String v) {
        store.put(K_ROLLED_BACK, v);
    }

    public long lastBinaryCode() {
        try {
            return Long.parseLong(store.get(K_BINARY, "-1"));
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    public void setLastBinaryCode(long code) {
        store.put(K_BINARY, Long.toString(code));
    }

    public Set<String> badVersions() {
        Set<String> out = new LinkedHashSet<>();
        for (String s : store.get(K_BAD, "").split(",")) if (!s.isEmpty()) out.add(s);
        return out;
    }

    public void addBadVersion(String v) {
        Set<String> bad = badVersions();
        bad.add(v);
        store.put(K_BAD, String.join(",", bad));
    }

    /** A new APK was installed: its built-in bundle replaces every downloaded one. */
    public void resetForNewBinary(long binaryCode) {
        setCurrent("");
        setPrevious("");
        setPending("");
        setPendingAttempts(0);
        setRolledBackFrom("");
        store.put(K_BAD, "");
        setLastBinaryCode(binaryCode);
    }
}
