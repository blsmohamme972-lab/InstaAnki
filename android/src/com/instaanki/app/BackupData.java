package com.instaanki.app;

import org.json.JSONObject;
import org.json.JSONArray;
import java.util.LinkedHashMap;
import java.util.Map;

/** Validates the complete backup before any SQLite mutation. */
final class BackupData {
    static Map<String, String> validate(JSONObject backup) throws Exception {
        if (!"instaanki-backup-v1".equals(backup.optString("format"))) {
            throw new IllegalArgumentException("This is not an InstaAnki version 1 backup.");
        }
        JSONObject entries = backup.optJSONObject("state");
        if (entries == null || entries.length() == 0 || entries.length() > 5000) {
            throw new IllegalArgumentException("The backup does not contain a valid state map.");
        }
        Map<String, String> checked = new LinkedHashMap<>();
        java.util.Iterator<String> keys = entries.keys();
        long total = 0;
        while (keys.hasNext()) {
            String key = keys.next();
            Object raw = entries.get(key);
            if (key.isEmpty() || key.length() > 240 || !(raw instanceof String)) {
                throw new IllegalArgumentException("The backup contains an invalid state entry.");
            }
            String value = (String) raw;
            total += value.length();
            if (value.length() > 20 * 1024 * 1024 || total > 24 * 1024 * 1024) {
                throw new IllegalArgumentException("The backup contains too much state data.");
            }
            if ("instaanki.state.v1".equals(key)) validateLearning(new JSONObject(value));
            checked.put(key, value);
        }
        return checked;
    }

    /** Validate the learning snapshot before the SQLite transaction, including new optional fields. */
    private static void validateLearning(JSONObject value) throws Exception {
        JSONObject lessons = value.optJSONObject("lessons");
        JSONArray reviews = value.optJSONArray("reviews");
        if (!FeedbackData.integer(value.opt("schemaVersion"), 1, 1) || lessons == null || reviews == null
            || lessons.length() > 20000 || reviews.length() > 200000) throw invalid("Unsupported or oversized progress backup.");
        JSONObject settings = value.optJSONObject("settings");
        if (value.has("settings") && !value.isNull("settings") && settings == null) throw invalid("Invalid progress settings.");
        if (settings != null) {
            for (String key : new String[]{"autoPlay", "autoCheckUpdates", "reduceMotion"}) if (settings.has(key) && !(settings.opt(key) instanceof Boolean)) throw invalid("Invalid progress setting.");
            if (settings.has("speed")) {
                double speed = number(settings.opt("speed"));
                if (!(speed == .75 || speed == 1 || speed == 1.25 || speed == 1.5 || speed == 1.75 || speed == 2)) throw invalid("Invalid playback speed.");
            }
            if (settings.has("retention")) { double retention = number(settings.opt("retention")); if (retention < .75 || retention > .97) throw invalid("Invalid retention setting."); }
            if (settings.has("newPerDay")) { double count = number(settings.opt("newPerDay")); if (count < 1 || count > 100 || Math.floor(count) != count) throw invalid("Invalid daily lesson limit."); }
            if (settings.has("dailyTopicIds")) {
                JSONArray topics = settings.optJSONArray("dailyTopicIds");
                if (topics == null || topics.length() > 256) throw invalid("Invalid daily topics.");
                for (int i = 0; i < topics.length(); i++) if (!FeedbackData.safeId(topics.opt(i))) throw invalid("Invalid daily topic.");
            }
        }
        for (java.util.Iterator<String> ids = lessons.keys(); ids.hasNext();) {
            String id = ids.next(); JSONObject record = lessons.optJSONObject(id);
            if (!FeedbackData.safeId(id) || record == null) throw invalid("Invalid lesson progress.");
            if (record.has("note") && (!(record.opt("note") instanceof String) || record.getString("note").length() > 16000)) throw invalid("Invalid lesson note.");
            for (String key : new String[]{"hidden", "disliked"}) if (record.has(key) && !(record.opt(key) instanceof Boolean)) throw invalid("Invalid lesson preference.");
            if (record.has("enrolledAt") && !record.isNull("enrolledAt") && !FeedbackData.date(record.opt("enrolledAt"))) throw invalid("Invalid enrollment date.");
            if (record.has("watchedSeconds") && !record.isNull("watchedSeconds") && (!(record.opt("watchedSeconds") instanceof Number) || number(record.opt("watchedSeconds")) < 0)) throw invalid("Invalid watch time.");
            if (record.has("card") && !record.isNull("card")) {
                JSONObject card = record.optJSONObject("card");
                if (card == null || !FeedbackData.date(card.opt("due")) || (card.has("last_review") && !card.isNull("last_review") && !FeedbackData.date(card.opt("last_review")))) throw invalid("Invalid review date.");
                for (String key : new String[]{"stability", "difficulty", "scheduled_days", "reps", "lapses", "learning_steps", "state"}) {
                    if (!(card.opt(key) instanceof Number) || number(card.opt(key)) < 0) throw invalid("Invalid review card.");
                }
                if (card.getDouble("state") > 3 || card.getDouble("difficulty") > 10) throw invalid("Invalid review card state.");
            }
        }
        for (int i = 0; i < reviews.length(); i++) {
            JSONObject review = reviews.optJSONObject(i);
            if (review == null || !FeedbackData.safeId(review.opt("lessonId")) || !(review.opt("attemptId") instanceof String)
                || review.getString("attemptId").length() > 180 || !FeedbackData.date(review.opt("at"))
                || !(review.opt("correct") instanceof Boolean) || !("Good".equals(review.optString("rating")) || "Again".equals(review.optString("rating")))) {
                throw invalid("Invalid review history.");
            }
        }
        if (value.has("feedback")) FeedbackData.reports(value.optJSONArray("feedback"));
    }

    private static double number(Object value) {
        try {
            if (!(value instanceof Number) && !(value instanceof String)) throw new NumberFormatException();
            double result = Double.parseDouble(value.toString());
            if (!Double.isFinite(result)) throw new NumberFormatException();
            return result;
        } catch (Exception invalid) { throw invalid("Invalid numeric progress setting."); }
    }
    private static IllegalArgumentException invalid(String message) { return new IllegalArgumentException(message); }
}
