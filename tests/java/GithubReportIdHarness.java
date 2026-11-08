package com.instaanki.app;

/** JVM-only contract test for actual local/normalized feedback ID parsing. */
public final class GithubReportIdHarness {
    private static void require(String result, String expected) {
        if (!expected.equals(result)) throw new AssertionError("Wrong ID: " + result);
    }
    public static void main(String[] ignored) {
        require(GithubReportId.resolve("feedback-123", null), "feedback-123");
        require(GithubReportId.resolve(null, "feedback-123"), "feedback-123");
        require(GithubReportId.resolve("feedback-123", "feedback-123"), "feedback-123");
        boolean failed = false;
        try { GithubReportId.resolve("feedback-123", "feedback-456"); }
        catch (IllegalArgumentException expected) { failed = true; }
        if (!failed) throw new AssertionError("Mismatched report identities must fail");
        System.out.println("Feedback ID round-trip tests passed");
    }
}
