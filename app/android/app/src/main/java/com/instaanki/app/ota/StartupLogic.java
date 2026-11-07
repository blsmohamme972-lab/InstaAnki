package com.instaanki.app.ota;

import java.util.LinkedHashSet;
import java.util.Set;

/** Pure decisions of the updater (no Android types), unit-tested on the JVM. */
public final class StartupLogic {

    private StartupLogic() {}

    public interface BundleExists {
        boolean exists(String version);
    }

    /**
     * Decides which bundle to load at process start. Returns the version to run ("" = built-in).
     * A pending bundle gets exactly one launch: if it was already tried and never confirmed, it is
     * marked bad and the app goes back to the last good bundle.
     */
    public static String decideStartup(OtaState s, long binaryCode, BundleExists exists) {
        if (s.lastBinaryCode() != binaryCode) {
            s.resetForNewBinary(binaryCode);
            return "";
        }
        if (!s.current().isEmpty() && !exists.exists(s.current())) s.setCurrent("");
        if (!s.previous().isEmpty() && !exists.exists(s.previous())) s.setPrevious("");

        String pending = s.pending();
        if (!pending.isEmpty()) {
            if (!exists.exists(pending)) {
                clearPending(s);
            } else if (s.pendingAttempts() >= 1) {
                rollback(s);
            } else {
                s.setPendingAttempts(1);
                return pending;
            }
        }
        return s.current();
    }

    /** A freshly downloaded bundle is about to be loaded; it counts as its one attempt. */
    public static void markApplied(OtaState s, String version) {
        s.setPending(version);
        s.setPendingAttempts(1);
        s.setRolledBackFrom("");
    }

    /** The pending bundle did not confirm in time (or crashed): give up on it. Returns the version to load. */
    public static String rollback(OtaState s) {
        String failed = s.pending();
        if (!failed.isEmpty()) {
            s.addBadVersion(failed);
            s.setRolledBackFrom(failed);
        }
        clearPending(s);
        return s.current();
    }

    /** notifyAppReady from the running bundle. Returns the versions that must stay on disk. */
    public static Set<String> confirm(OtaState s, String runningVersion) {
        if (!s.pending().isEmpty() && s.pending().equals(runningVersion)) {
            s.setPrevious(s.current());
            s.setCurrent(runningVersion);
            clearPending(s);
        }
        s.setRolledBackFrom("");
        Set<String> keep = new LinkedHashSet<>();
        if (!s.current().isEmpty()) keep.add(s.current());
        if (!s.previous().isEmpty()) keep.add(s.previous());
        if (!s.pending().isEmpty()) keep.add(s.pending());
        return keep;
    }

    /** Should an update to `latest` be offered while `running` is active? */
    public static boolean shouldOffer(OtaState s, String latest, String running, String builtinVersion) {
        String base = running.isEmpty() ? builtinVersion : running;
        return SemVer.isNewer(latest, base) && !s.badVersions().contains(latest);
    }

    private static void clearPending(OtaState s) {
        s.setPending("");
        s.setPendingAttempts(0);
    }
}
