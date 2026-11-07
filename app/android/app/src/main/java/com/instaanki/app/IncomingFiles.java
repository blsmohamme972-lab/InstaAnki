package com.instaanki.app;

import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;
import android.util.Log;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * "Share -> InstaAnki" and "Open with InstaAnki": shared files are copied into cache/incoming/
 * and stay there until the web layer imports and deletes them (so nothing is lost if the app
 * is not ready yet).
 */
final class IncomingFiles {

    private static final String TAG = "InstaAnkiIncoming";
    static final String DIR = "incoming";
    private static final long MAX_BYTES = 300L * 1024 * 1024;

    private IncomingFiles() {}

    static List<Uri> urisOf(Intent intent) {
        List<Uri> uris = new ArrayList<>();
        if (intent == null || intent.getAction() == null) return uris;
        switch (intent.getAction()) {
            case Intent.ACTION_SEND: {
                Uri u = intent.getParcelableExtra(Intent.EXTRA_STREAM);
                if (u != null) uris.add(u);
                break;
            }
            case Intent.ACTION_SEND_MULTIPLE: {
                ArrayList<Uri> list = intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
                if (list != null) uris.addAll(list);
                break;
            }
            case Intent.ACTION_VIEW:
                if (intent.getData() != null && "content".equals(intent.getData().getScheme())) uris.add(intent.getData());
                break;
            default:
                break;
        }
        return uris;
    }

    static File dir(Context ctx) {
        return new File(ctx.getCacheDir(), DIR);
    }

    /** Blocking copy (call from a background thread). Returns how many files were saved. */
    static int save(Context ctx, List<Uri> uris) {
        File dir = dir(ctx);
        if (!dir.isDirectory() && !dir.mkdirs()) return 0;
        int saved = 0;
        for (int i = 0; i < uris.size(); i++) {
            Uri uri = uris.get(i);
            File out = new File(dir, System.currentTimeMillis() + "-" + i + "-" + safeName(displayName(ctx, uri)));
            try (InputStream in = ctx.getContentResolver().openInputStream(uri); OutputStream os = new FileOutputStream(out)) {
                if (in == null) throw new IOException("cannot open " + uri);
                byte[] buf = new byte[64 * 1024];
                long total = 0;
                int n;
                while ((n = in.read(buf)) != -1) {
                    total += n;
                    if (total > MAX_BYTES) throw new IOException("shared file is too large");
                    os.write(buf, 0, n);
                }
                saved++;
            } catch (Exception e) {
                Log.w(TAG, "could not save shared file", e);
                //noinspection ResultOfMethodCallIgnored
                out.delete();
            }
        }
        return saved;
    }

    static List<File> pending(Context ctx) {
        File[] files = dir(ctx).listFiles(File::isFile);
        if (files == null) return new ArrayList<>();
        Arrays.sort(files);
        return Arrays.asList(files);
    }

    private static String displayName(Context ctx, Uri uri) {
        try (Cursor c = ctx.getContentResolver().query(uri, new String[] { OpenableColumns.DISPLAY_NAME }, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                String name = c.getString(0);
                if (name != null) return name;
            }
        } catch (Exception ignored) {
            // fall through
        }
        String last = uri.getLastPathSegment();
        return last == null ? "pack.zip" : last;
    }

    static String safeName(String name) {
        String clean = name.replaceAll("[^A-Za-z0-9._-]", "_");
        if (clean.length() > 80) clean = clean.substring(clean.length() - 80);
        return clean.isEmpty() ? "pack.zip" : clean;
    }
}
