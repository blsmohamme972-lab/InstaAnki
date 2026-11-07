package com.instaanki.app;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import androidx.appcompat.app.AlertDialog;
import com.getcapacitor.Bridge;
import com.instaanki.app.ota.OtaController;
import com.instaanki.app.ota.OtaManifest;
import java.util.Locale;
import java.util.concurrent.Executor;

/** Native dialogs for updates: they work even if the web layer is broken. */
final class UpdateUi {

    private static boolean showing;

    private UpdateUi() {}

    static synchronized boolean tryBegin() {
        if (showing) return false;
        showing = true;
        return true;
    }

    static synchronized void end() {
        showing = false;
    }

    static String formatSize(long bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return String.format(Locale.US, "%.0f KB", bytes / 1024.0);
        return String.format(Locale.US, "%.1f MB", bytes / (1024.0 * 1024.0));
    }

    static void offerUpdate(Activity activity, OtaController ota, Bridge bridge, OtaController.CheckResult r, Executor io) {
        if (activity.isFinishing() || !tryBegin()) return;
        OtaManifest m = r.manifest;
        StringBuilder msg = new StringBuilder();
        msg.append("الإصدار v").append(m.bundleVersion).append(" · ").append(formatSize(r.downloadBytes));
        if (!m.notes.isEmpty()) msg.append("\n\n").append(m.notes);
        new AlertDialog.Builder(activity)
            .setTitle("تحديث متاح")
            .setMessage(msg.toString())
            .setCancelable(false)
            .setPositiveButton("تحديث الآن", (d, w) -> download(activity, ota, bridge, m, io))
            .setNegativeButton("لاحقاً", (d, w) -> end())
            .show();
    }

    private static void download(Activity activity, OtaController ota, Bridge bridge, OtaManifest m, Executor io) {
        final AlertDialog progress = new AlertDialog.Builder(activity)
            .setTitle("جارٍ التحديث")
            .setMessage("جارٍ التنزيل…")
            .setCancelable(false)
            .show();
        io.execute(() -> {
            try {
                ota.download(m, (done, total) ->
                    activity.runOnUiThread(() -> progress.setMessage(String.format(Locale.US, "جارٍ التنزيل… %d/%d", done, total)))
                );
                activity.runOnUiThread(() -> {
                    progress.dismiss();
                    end();
                    ota.apply(bridge, m.bundleVersion);
                });
            } catch (Exception e) {
                activity.runOnUiThread(() -> {
                    progress.dismiss();
                    new AlertDialog.Builder(activity)
                        .setTitle("تعذّر التحديث")
                        .setMessage(e.getMessage() == null ? e.toString() : e.getMessage())
                        .setPositiveButton("حسناً", (d, w) -> end())
                        .setCancelable(false)
                        .show();
                });
            }
        });
    }

    static void needsApk(Activity activity, OtaController.CheckResult r) {
        if (activity.isFinishing() || !tryBegin()) return;
        String version = r.manifest != null ? " (v" + r.manifest.bundleVersion + ")" : "";
        new AlertDialog.Builder(activity)
            .setTitle("تحديث كبير متاح" + version)
            .setMessage("هذا التحديث يحتاج تثبيت نسخة جديدة من التطبيق. بياناتك تبقى كما هي.")
            .setCancelable(false)
            .setPositiveButton("تنزيل", (d, w) -> {
                end();
                activity.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(BuildConfig.APK_RELEASES_URL)));
            })
            .setNegativeButton("لاحقاً", (d, w) -> end())
            .show();
    }
}
