package com.instaanki.app.ota;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Strict MAJOR.MINOR.PATCH versions for web bundles. */
public final class SemVer implements Comparable<SemVer> {

    private static final Pattern PATTERN = Pattern.compile("^(0|[1-9]\\d{0,8})\\.(0|[1-9]\\d{0,8})\\.(0|[1-9]\\d{0,8})$");

    public final int major;
    public final int minor;
    public final int patch;

    private SemVer(int major, int minor, int patch) {
        this.major = major;
        this.minor = minor;
        this.patch = patch;
    }

    public static boolean isValid(String s) {
        return s != null && PATTERN.matcher(s).matches();
    }

    public static SemVer parse(String s) throws OtaException {
        Matcher m = s == null ? null : PATTERN.matcher(s);
        if (m == null || !m.matches()) throw new OtaException("invalid version: " + s);
        return new SemVer(Integer.parseInt(m.group(1)), Integer.parseInt(m.group(2)), Integer.parseInt(m.group(3)));
    }

    /** a > b ? (invalid versions are never newer) */
    public static boolean isNewer(String a, String b) {
        try {
            return parse(a).compareTo(parse(b)) > 0;
        } catch (OtaException e) {
            return false;
        }
    }

    @Override
    public int compareTo(SemVer o) {
        if (major != o.major) return Integer.compare(major, o.major);
        if (minor != o.minor) return Integer.compare(minor, o.minor);
        return Integer.compare(patch, o.patch);
    }

    @Override
    public String toString() {
        return major + "." + minor + "." + patch;
    }
}
