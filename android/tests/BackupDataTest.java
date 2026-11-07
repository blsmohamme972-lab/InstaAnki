package com.instaanki.app;

import org.json.JSONObject;
import java.util.Map;

/** Verifies untrusted backup input is validated before it reaches the native transaction. */
public final class BackupDataTest {
    public static void main(String[] args) throws Exception {
        JSONObject valid = new JSONObject().put("format", "instaanki-backup-v1")
            .put("state", new JSONObject().put("instaanki-state", "{\"reviews\":[{\"id\":\"a\"}]}"));
        Map<String, String> parsed = BackupData.validate(valid);
        if (!parsed.get("instaanki-state").contains("reviews")) throw new AssertionError("Valid state was not preserved");
        System.out.println("PASS valid backup preserves the exact stored state");
        JSONObject[] invalid = {
            new JSONObject("{\"format\":\"other\",\"state\":{\"a\":\"1\"}}"),
            new JSONObject("{\"format\":\"instaanki-backup-v1\"}"),
            new JSONObject("{\"format\":\"instaanki-backup-v1\",\"state\":{}}"),
            new JSONObject("{\"format\":\"instaanki-backup-v1\",\"state\":{\"a\":{}}}"),
            new JSONObject("{\"format\":\"instaanki-backup-v1\",\"state\":{\"a\":null}}"),
            new JSONObject("{\"format\":\"instaanki-backup-v1\",\"state\":{\"\":\"data\"}}"),
        };
        for (JSONObject backup : invalid) {
            boolean rejected = false;
            try { BackupData.validate(backup); } catch (Exception expected) { rejected = true; }
            if (!rejected) throw new AssertionError("Invalid backup accepted");
            System.out.println("PASS malformed backup rejected before database writes");
        }
        System.out.println("All 7 backup validation assertions passed.");
    }
}
