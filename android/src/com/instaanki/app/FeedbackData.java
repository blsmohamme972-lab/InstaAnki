package com.instaanki.app;

import org.json.JSONArray;
import org.json.JSONObject;
import java.time.Instant;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;

/** Feedback is local data. Only these explicit diagnostic fields may be shared. */
final class FeedbackData {
    static final int MAX_REPORTS = 5000;
    private static final Set<String> REASONS = new HashSet<>(Arrays.asList(
        "bad_sound", "bad_images", "bad_timing", "bad_mcq", "wrong_source", "other"));

    static JSONObject exportDocument(String text) throws Exception {
        if (text == null || text.length() > 20 * 1024 * 1024) throw invalid("The feedback file is too large.");
        JSONObject input = new JSONObject(text);
        if (!"instaanki-feedback-v1".equals(input.optString("format")) || !integer(input.opt("schemaVersion"), 1, 1)) {
            throw invalid("This is not an InstaAnki feedback report.");
        }
        if (!date(input.opt("createdAt"))) throw invalid("Invalid feedback export date.");
        return new JSONObject().put("format", "instaanki-feedback-v1").put("schemaVersion", 1)
            .put("createdAt", input.getString("createdAt")).put("reports", reports(input.optJSONArray("reports")));
    }

    static JSONArray reports(JSONArray input) throws Exception {
        if (input == null || input.length() > MAX_REPORTS) throw invalid("Invalid feedback reports.");
        JSONArray output = new JSONArray();
        Set<String> ids = new HashSet<>();
        for (int i = 0; i < input.length(); i++) {
            JSONObject checked = report(input.optJSONObject(i));
            if (!ids.add(checked.getString("id"))) throw invalid("Duplicate feedback report ID.");
            output.put(checked);
        }
        return output;
    }

    private static JSONObject report(JSONObject value) throws Exception {
        if (value == null || !safeId(value.opt("id")) || !safeId(value.opt("lessonId")) || !date(value.opt("createdAt"))) {
            throw invalid("Invalid feedback report.");
        }
        String reason = value.optString("reason");
        if ("audio_issue".equals(reason)) reason = "bad_sound";
        else if ("image_issue".equals(reason)) reason = "bad_images";
        else if ("sync_issue".equals(reason)) reason = "bad_timing";
        else if ("factual_error".equals(reason)) reason = "bad_mcq";
        else if ("unclear_explanation".equals(reason)) reason = "other";
        if (!REASONS.contains(reason) || !(value.opt("comment") instanceof String) || value.getString("comment").length() > 4000) {
            throw invalid("Invalid feedback reason or comment.");
        }
        Object version = value.opt("lessonVersion");
        if (version != null && version != JSONObject.NULL && !integer(version, 0, 1e9)
            && !(version instanceof String && ((String) version).matches("[A-Za-z0-9][A-Za-z0-9._-]{0,79}"))) {
            throw invalid("Invalid feedback lesson version.");
        }
        JSONObject source = new JSONObject();
        if (value.has("source")) {
            JSONObject raw = value.optJSONObject("source");
            if (raw == null) throw invalid("Invalid feedback source.");
            if (raw.has("bookId")) { if (!safeId(raw.opt("bookId"))) throw invalid("Invalid feedback book ID."); source.put("bookId", raw.getString("bookId")); }
            if (raw.has("questionNumber")) { if (!integer(raw.opt("questionNumber"), 1, 1e7)) throw invalid("Invalid feedback source question."); source.put("questionNumber", raw.getInt("questionNumber")); }
            for (String key : new String[]{"sourceRecordSha256", "extractionSha256"}) if (raw.has(key)) {
                if (!hash(raw.opt(key))) throw invalid("Invalid feedback source checksum.");
                source.put(key, raw.getString(key).toLowerCase(java.util.Locale.ROOT));
            }
        }
        JSONObject assets = new JSONObject();
        if (value.has("assetHashes")) {
            JSONObject raw = value.optJSONObject("assetHashes");
            if (raw == null || raw.length() > 200) throw invalid("Invalid feedback asset checksums.");
            for (Iterator<String> it = raw.keys(); it.hasNext();) {
                String key = it.next();
                if (!key.matches("[A-Za-z0-9][A-Za-z0-9._/-]{0,319}") || !hash(raw.opt(key))) throw invalid("Invalid feedback asset checksum.");
                for (String part : key.split("/", -1)) if (part.isEmpty() || part.equals(".") || part.equals("..") || forbidden(part)) throw invalid("Invalid feedback asset path.");
                assets.put(key, raw.getString(key).toLowerCase(java.util.Locale.ROOT));
            }
        }
        JSONObject app = new JSONObject();
        if (value.has("app")) {
            JSONObject raw = value.optJSONObject("app");
            if (raw == null) throw invalid("Invalid feedback app version.");
            for (String key : new String[]{"version", "packageName", "platform"}) if (raw.has(key)) {
                if (!(raw.opt(key) instanceof String) || raw.getString(key).length() > 120) throw invalid("Invalid feedback app version.");
                app.put(key, raw.getString(key));
            }
            if (raw.has("versionCode")) { if (!integer(raw.opt("versionCode"), 0, 9007199254740991d)) throw invalid("Invalid feedback app version."); app.put("versionCode", raw.getLong("versionCode")); }
        }
        return new JSONObject().put("id", value.getString("id")).put("lessonId", value.getString("lessonId"))
            .put("lessonVersion", version == null ? JSONObject.NULL : version).put("reason", reason)
            .put("comment", value.getString("comment")).put("createdAt", value.getString("createdAt"))
            .put("source", source).put("assetHashes", assets).put("app", app);
    }

    static boolean safeId(Object value) {
        return value instanceof String && ((String) value).matches("[A-Za-z0-9][A-Za-z0-9._-]{0,119}") && !forbidden((String) value);
    }
    private static boolean forbidden(String value) { return value.equals("__proto__") || value.equals("constructor") || value.equals("prototype"); }
    static boolean date(Object value) { try { return value instanceof String && Instant.parse((String) value) != null; } catch (Exception invalid) { return false; } }
    static boolean integer(Object value, double min, double max) { return value instanceof Number && Double.isFinite(((Number) value).doubleValue()) && ((Number) value).doubleValue() >= min && ((Number) value).doubleValue() <= max && Math.floor(((Number) value).doubleValue()) == ((Number) value).doubleValue(); }
    private static boolean hash(Object value) { return value instanceof String && ((String) value).matches("(?i)[a-f0-9]{64}"); }
    private static IllegalArgumentException invalid(String message) { return new IllegalArgumentException(message); }
}
