package com.instaanki.app;

/**
 * Stable feedback IDs across the local-report and native-queue representations.
 * The learning store uses "id"; the native queue stores the normalized "reportId".
 */
final class GithubReportId {
    private GithubReportId() { }

    static String resolve(String localId, String queuedId) {
        if (localId != null && queuedId != null && !localId.equals(queuedId))
            throw new IllegalArgumentException("Conflicting feedback report IDs");
        return queuedId != null ? queuedId : localId;
    }
}
