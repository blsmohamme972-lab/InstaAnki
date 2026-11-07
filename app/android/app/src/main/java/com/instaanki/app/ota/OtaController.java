package com.instaanki.app.ota;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import androidx.core.content.pm.PackageInfoCompat;
import com.getcapacitor.Bridge;
import com.instaanki.app.BuildConfig;
import com.instaanki.app.R;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.net.UnknownHostException;
import java.nio.charset.StandardCharsets;
import java.security.PublicKey;
import java.util.Set;
import org.json.JSONObject;

/** Android side of the updater: state, startup decision, checks, download and rollback. */
public final class OtaController {

    private static final String TAG = "InstaAnkiOta";
    private static final String PREFS = "InstaAnkiOta";
    /** Same keys Capacitor's Bridge reads at startup. */
    private static final String CAP_PREFS = "CapWebViewSettings";
    private static final String CAP_SERVER_PATH = "serverBasePath";
    public static final long CONFIRM_TIMEOUT_MS = 15_000;

    private static OtaController instance;

    private final Context context;
    private final OtaState state;
    private final BundleInstaller installer;
    private final HttpFetcher fetcher;
    private final long shellVersion;
    private final String builtinVersion;
    private final Handler main = new Handler(Looper.getMainLooper());
    private String running = "";
    private Runnable confirmTimeout;

    public static synchronized OtaController get(Context ctx) {
        if (instance == null) instance = new OtaController(ctx.getApplicationContext());
        return instance;
    }

    private OtaController(Context context) {
        this.context = context;
        final SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        this.state = new OtaState(
            new OtaState.Store() {
                @Override
                public String get(String key, String fallback) {
                    return prefs.getString(key, fallback);
                }

                @Override
                public void put(String key, String value) {
                    prefs.edit().putString(key, value).commit();
                }
            }
        );
        this.installer = new BundleInstaller(new File(context.getFilesDir(), "ota/bundles"));
        this.fetcher = new HttpFetcher(BuildConfig.OTA_BASE_URL);
        this.shellVersion = readVersionCode(context);
        this.builtinVersion = readBuiltinVersion(context);
    }

    // ------------------------------------------------------------------ startup

    private boolean decided;

    /**
     * Must run before the Capacitor bridge is created (MainActivity.onCreate before super).
     * The decision is taken once per process; a re-created activity reuses it.
     */
    public synchronized void prepareStartup() {
        if (decided) {
            writeCapacitorPath(running);
            return;
        }
        decided = true;
        running = StartupLogic.decideStartup(state, shellVersion, installer::exists);
        writeCapacitorPath(running);
        Log.i(TAG, "startup: running=" + label(running) + " current=" + label(state.current()) + " pending=" + label(state.pending()));
        if (!state.pending().isEmpty()) scheduleConfirmTimeout(null);
    }

    // ------------------------------------------------------------------ info for JS

    public synchronized long shellVersion() {
        return shellVersion;
    }

    public synchronized String runningVersion() {
        return running.isEmpty() ? builtinVersion : running;
    }

    public synchronized boolean runningBuiltin() {
        return running.isEmpty();
    }

    public synchronized String rolledBackFrom() {
        return state.rolledBackFrom();
    }

    public synchronized void onAppReady() {
        cancelConfirmTimeout();
        Set<String> keep = StartupLogic.confirm(state, running);
        installer.retainOnly(keep);
    }

    // ------------------------------------------------------------------ checking

    public enum Status {
        UP_TO_DATE("up-to-date"),
        UPDATE_AVAILABLE("update-available"),
        NEEDS_APK("needs-apk"),
        OFFLINE("offline"),
        ERROR("error");

        public final String js;

        Status(String js) {
            this.js = js;
        }
    }

    public static final class CheckResult {

        public final Status status;
        public final OtaManifest manifest;
        public final long downloadBytes;
        public final String message;

        CheckResult(Status status, OtaManifest manifest, long downloadBytes, String message) {
            this.status = status;
            this.manifest = manifest;
            this.downloadBytes = downloadBytes;
            this.message = message;
        }
    }

    /** Blocking: call from a background thread. */
    public CheckResult check() {
        try {
            byte[] json = fetcher.fetchBytes("latest.json", 1024 * 1024);
            String sig = new String(fetcher.fetchBytes("latest.json.sig", 4096), StandardCharsets.UTF_8).trim();
            PublicKey key = Signatures.parsePublicKeyPem(readRaw(R.raw.ota_public_key));
            if (!Signatures.verify(key, json, sig)) return new CheckResult(Status.ERROR, null, 0, "bad signature");
            OtaManifest m = OtaManifest.parse(json);
            synchronized (this) {
                if (!StartupLogic.shouldOffer(state, m.bundleVersion, running, builtinVersion)) {
                    return new CheckResult(Status.UP_TO_DATE, m, 0, null);
                }
                if (m.minShellVersion > shellVersion) return new CheckResult(Status.NEEDS_APK, m, 0, null);
            }
            return new CheckResult(Status.UPDATE_AVAILABLE, m, installer.bytesToDownload(m, runningSource()), null);
        } catch (HttpFetcher.NotFound e) {
            return new CheckResult(Status.UP_TO_DATE, null, 0, "no update published yet");
        } catch (UnknownHostException e) {
            return new CheckResult(Status.OFFLINE, null, 0, null);
        } catch (IOException e) {
            return new CheckResult(isOnline() ? Status.ERROR : Status.OFFLINE, null, 0, e.getMessage());
        } catch (OtaException e) {
            return new CheckResult(Status.ERROR, null, 0, e.getMessage());
        }
    }

    /** Blocking: downloads the bundle into its folder. */
    public void download(OtaManifest m, BundleInstaller.Progress progress) throws IOException, OtaException {
        installer.install(m, runningSource(), fetcher, progress);
    }

    /** Switches the WebView to the downloaded bundle. It must confirm within CONFIRM_TIMEOUT_MS. */
    public synchronized void apply(Bridge bridge, String version) {
        StartupLogic.markApplied(state, version);
        running = version;
        writeCapacitorPath(version);
        bridge.setServerBasePath(installer.dirFor(version).getAbsolutePath());
        scheduleConfirmTimeout(bridge);
    }

    private void scheduleConfirmTimeout(final Bridge bridge) {
        cancelConfirmTimeout();
        confirmTimeout = () -> {
            synchronized (OtaController.this) {
                if (state.pending().isEmpty()) return;
                Log.w(TAG, "bundle " + state.pending() + " did not confirm; rolling back");
                running = StartupLogic.rollback(state);
                writeCapacitorPath(running);
                if (bridge != null) loadRunning(bridge);
                else restartActivity();
            }
        };
        main.postDelayed(confirmTimeout, CONFIRM_TIMEOUT_MS);
    }

    private void cancelConfirmTimeout() {
        if (confirmTimeout != null) main.removeCallbacks(confirmTimeout);
        confirmTimeout = null;
    }

    private Activity currentActivity;

    public synchronized void attach(Activity activity) {
        currentActivity = activity;
    }

    private void restartActivity() {
        Activity a = currentActivity;
        if (a != null) a.recreate();
    }

    private void loadRunning(Bridge bridge) {
        if (running.isEmpty()) bridge.setServerAssetPath("public");
        else bridge.setServerBasePath(installer.dirFor(running).getAbsolutePath());
    }

    // ------------------------------------------------------------------ helpers

    private void writeCapacitorPath(String version) {
        String path = version.isEmpty() ? "" : installer.dirFor(version).getAbsolutePath();
        context.getSharedPreferences(CAP_PREFS, Context.MODE_PRIVATE).edit().putString(CAP_SERVER_PATH, path).commit();
    }

    /** Files of the bundle that is running now (downloaded folder or the APK's assets). */
    private BundleInstaller.LocalSource runningSource() {
        final String version;
        synchronized (this) {
            version = running;
        }
        if (version.isEmpty()) {
            return path -> {
                try {
                    return context.getAssets().open("public/" + path);
                } catch (FileNotFoundException e) {
                    return null;
                }
            };
        }
        final File dir = installer.dirFor(version);
        return path -> {
            File f = new File(dir, path);
            return f.isFile() ? new FileInputStream(f) : null;
        };
    }

    private boolean isOnline() {
        android.net.ConnectivityManager cm = (android.net.ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) return true;
        if (Build.VERSION.SDK_INT >= 23) return cm.getActiveNetwork() != null;
        return true;
    }

    private String readRaw(int id) throws IOException {
        try (InputStream in = context.getResources().openRawResource(id)) {
            return new String(readAll(in), StandardCharsets.UTF_8);
        }
    }

    private static byte[] readAll(InputStream in) throws IOException {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
        return out.toByteArray();
    }

    private static long readVersionCode(Context ctx) {
        try {
            PackageInfo info = ctx.getPackageManager().getPackageInfo(ctx.getPackageName(), 0);
            return PackageInfoCompat.getLongVersionCode(info);
        } catch (Exception e) {
            return BuildConfig.VERSION_CODE;
        }
    }

    private static String readBuiltinVersion(Context ctx) {
        try (InputStream in = ctx.getAssets().open("public/bundle-info.json")) {
            return new JSONObject(new String(readAll(in), StandardCharsets.UTF_8)).getString("bundleVersion");
        } catch (Exception e) {
            Log.w(TAG, "no bundle-info.json in the APK", e);
            return "0.0.0";
        }
    }

    private static String label(String v) {
        return v.isEmpty() ? "builtin" : v;
    }
}
