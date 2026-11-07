package com.instaanki.app;

import org.json.JSONObject;
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
            checked.put(key, value);
        }
        return checked;
    }
}
