package com.instaanki.app;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import org.json.JSONObject;
import java.util.Map;

/** Learning state lives outside content packages and survives app updates. */
final class LocalStore extends SQLiteOpenHelper {
    LocalStore(Context context) { super(context, "instaanki.db", null, 1); }

    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE state (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL, updated_at INTEGER NOT NULL)");
    }

    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        // Version 1. Future versions must migrate without dropping learning data.
    }

    synchronized String get(String key) {
        try (Cursor c = getReadableDatabase().query("state", new String[]{"value"}, "key=?", new String[]{key}, null, null, null)) {
            return c.moveToFirst() ? c.getString(0) : null;
        }
    }

    synchronized void put(String key, String value) {
        if (key == null || key.isEmpty() || key.length() > 240 || value == null || value.length() > 20 * 1024 * 1024) {
            throw new IllegalArgumentException("State entry is invalid or too large.");
        }
        ContentValues row = new ContentValues();
        row.put("key", key); row.put("value", value); row.put("updated_at", System.currentTimeMillis());
        if (getWritableDatabase().insertWithOnConflict("state", null, row, SQLiteDatabase.CONFLICT_REPLACE) == -1) {
            throw new IllegalStateException("Your learning progress could not be saved. Check the device's available storage.");
        }
    }

    synchronized void remove(String key) {
        getWritableDatabase().delete("state", "key=?", new String[]{key});
    }

    synchronized JSONObject exportData() throws Exception {
        JSONObject entries = new JSONObject();
        try (Cursor c = getReadableDatabase().query("state", new String[]{"key", "value"}, null, null, null, null, "key")) {
            while (c.moveToNext()) entries.put(c.getString(0), c.getString(1));
        }
        return new JSONObject().put("format", "instaanki-backup-v1")
            .put("createdAt", System.currentTimeMillis()).put("state", entries);
    }

    synchronized int importData(JSONObject backup) throws Exception {
        Map<String, String> checked = BackupData.validate(backup);
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            long now = System.currentTimeMillis();
            for (Map.Entry<String, String> entry : checked.entrySet()) {
                ContentValues row = new ContentValues();
                row.put("key", entry.getKey()); row.put("value", entry.getValue()); row.put("updated_at", now);
                if (db.insertWithOnConflict("state", null, row, SQLiteDatabase.CONFLICT_REPLACE) == -1) {
                    throw new IllegalStateException("The backup could not be restored.");
                }
            }
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
        return checked.size();
    }
}
