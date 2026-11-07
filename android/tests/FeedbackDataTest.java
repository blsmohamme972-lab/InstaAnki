package com.instaanki.app;

import org.json.JSONArray;
import org.json.JSONObject;

/** Exercises the actual native export allowlist and restore validator without Android UI claims. */
public final class FeedbackDataTest {
    private static int passed;
    private static void ok(boolean result, String label) { if (!result) throw new AssertionError(label); passed++; System.out.println("PASS " + label); }
    private static JSONObject report() throws Exception {
        return new JSONObject().put("id", "feedback-test-1").put("lessonId", "shahzad2015-q005").put("lessonVersion", 2)
            .put("reason", "bad_sound").put("comment", "Audio is clipped.").put("createdAt", "2026-11-07T12:00:00.000Z")
            .put("source", new JSONObject().put("bookId", "shahzad-raja-2015-200-practice-questions").put("questionNumber", 5))
            .put("assetHashes", new JSONObject().put("media/audio/q005.mp3", repeat('a', 64)))
            .put("app", new JSONObject().put("version", "0.1.2").put("versionCode", 3));
    }
    private static JSONObject document() throws Exception {
        return new JSONObject().put("format", "instaanki-feedback-v1").put("schemaVersion", 1)
            .put("createdAt", "2026-11-07T12:01:00.000Z").put("reports", new JSONArray().put(report()));
    }
    private static String repeat(char c, int count) { char[] out = new char[count]; java.util.Arrays.fill(out, c); return new String(out); }
    private static void rejects(String value, String label) throws Exception {
        boolean rejected = false;try { FeedbackData.exportDocument(value); } catch (Exception expected) { rejected = true; }ok(rejected, label);
    }
    private static JSONObject backup(JSONObject learning) throws Exception {
        return new JSONObject().put("format", "instaanki-backup-v1").put("state", new JSONObject().put("instaanki.state.v1", learning.toString()));
    }
    private static JSONObject learning() throws Exception {
        return new JSONObject().put("schemaVersion", 1).put("settings", new JSONObject().put("dailyTopicIds", new JSONArray()))
            .put("lessons", new JSONObject().put("shahzad2015-q005", new JSONObject().put("note", "Keep this private.").put("watchedSeconds", 9).put("card", JSONObject.NULL)))
            .put("reviews", new JSONArray());
    }
    public static void main(String[] args) throws Exception {
        JSONObject source = document();source.put("reviews", new JSONArray().put("private"));source.put("notes", "private");
        source.getJSONArray("reports").getJSONObject(0).put("note", "private").getJSONObject("source").put("rawBookText", "private");
        JSONObject output = FeedbackData.exportDocument(source.toString());
        ok(!output.toString().contains("private"), "native export excludes notes, reviews and arbitrary source text");
        ok(output.getJSONArray("reports").getJSONObject(0).getString("lessonId").equals("shahzad2015-q005"), "native export retains exact stable lesson identity");
        ok(output.getJSONArray("reports").getJSONObject(0).getJSONObject("assetHashes").getString("media/audio/q005.mp3").equals(repeat('a', 64)), "native export retains asset fingerprint");
        rejects(source.toString().substring(0, source.toString().length() - 5), "truncated feedback JSON rejected before export");
        JSONObject bad = document();bad.getJSONArray("reports").getJSONObject(0).put("reason", "invalid");rejects(bad.toString(), "invalid feedback reason rejected");
        bad = document();bad.getJSONArray("reports").getJSONObject(0).put("comment", repeat('x', 4001));rejects(bad.toString(), "oversized comment rejected");
        bad = document();bad.getJSONArray("reports").getJSONObject(0).getJSONObject("assetHashes").put("audio", "corrupted");rejects(bad.toString(), "corrupted asset checksum rejected");
        bad = document();bad.getJSONArray("reports").put(report());rejects(bad.toString(), "duplicate report IDs rejected");
        JSONObject legacy = learning();String exact = legacy.toString();
        ok(BackupData.validate(backup(legacy)).get("instaanki.state.v1").equals(exact), "legacy backup without feedback or hidden fields remains compatible");
        JSONObject updated = learning().put("feedback", new JSONArray().put(report()));updated.getJSONObject("lessons").getJSONObject("shahzad2015-q005").put("hidden", true).put("disliked", true);
        ok(BackupData.validate(backup(updated)).get("instaanki.state.v1").equals(updated.toString()), "native restore preserves feedback and visibility preferences exactly");
        updated.getJSONArray("feedback").getJSONObject(0).put("createdAt", "not-a-date");boolean refused = false;
        try { BackupData.validate(backup(updated)); } catch (Exception expected) { refused = true; }
        ok(refused, "invalid feedback backup rejected before SQLite mutation");
        JSONObject invalidCard = learning();invalidCard.getJSONObject("lessons").getJSONObject("shahzad2015-q005").put("card", new JSONObject().put("due", "broken"));refused = false;
        try { BackupData.validate(backup(invalidCard)); } catch (Exception expected) { refused = true; }
        ok(refused, "corrupted FSRS backup rejected before SQLite mutation");
        System.out.println("All " + passed + " native feedback assertions passed.");
    }
}
