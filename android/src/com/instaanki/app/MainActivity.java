package com.instaanki.app;

import android.app.Activity;
import android.content.Intent;
import android.content.ClipData;
import android.content.pm.PackageInfo;
import android.content.res.AssetFileDescriptor;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.Toast;
import org.json.JSONObject;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** Small, offline Android shell: trusted bundled UI, native SQLite, and data-only lesson packs. */
public final class MainActivity extends Activity {
    private static final String HOST = "appassets.androidplatform.net";
    private static final String START_URL = "https://" + HOST + "/assets/index.html";
    private static final int PICK_PACK = 101;
    private static final int EXPORT_BACKUP = 102;
    private static final int WEB_FILE_PICKER = 103;
    private static final int IMPORT_BACKUP = 104;
    private static final int EXPORT_FEEDBACK = 105;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private WebView web;
    private LocalStore state;
    private ContentPacks packs;
    private ValueCallback<Uri[]> fileCallback;
    private final AtomicBoolean importing = new AtomicBoolean(false);
    private volatile String pendingFeedbackExport;
    private boolean immersiveRequested;

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setStatusBarColor(Color.rgb(8, 19, 29));
        getWindow().setNavigationBarColor(Color.rgb(8, 19, 29));
        getWindow().getDecorView().setSystemUiVisibility(0);
        state = new LocalStore(this);
        try { packs = new ContentPacks(new File(getFilesDir(), "lesson-packs")); }
        catch (IOException e) { throw new IllegalStateException("Unable to open local content storage", e); }

        FrameLayout frame = new FrameLayout(this);
        frame.setBackgroundColor(Color.rgb(8, 19, 29));
        web = new WebView(this);
        web.setBackgroundColor(Color.rgb(8, 19, 29));
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        frame.addView(web, new FrameLayout.LayoutParams(-1, -1));
        setContentView(frame);
        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
            frame.setOnApplyWindowInsetsListener((view, insets) -> {
                android.graphics.Insets safe = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                android.graphics.Insets ime = insets.getInsets(WindowInsets.Type.ime());
                view.setPadding(safe.left, safe.top, safe.right, Math.max(safe.bottom, ime.bottom));
                return insets;
            });
            frame.requestApplyInsets();
        }
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setSupportMultipleWindows(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setBuiltInZoomControls(false);
        settings.setTextZoom(100);
        settings.setSafeBrowsingEnabled(true);
        WebView.setWebContentsDebuggingEnabled(false);
        web.addJavascriptInterface(new NativeBridge(), "AndroidNative");
        web.setWebViewClient(new LocalClient());
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
                try { startActivityForResult(picker, WEB_FILE_PICKER); }
                catch (Exception e) { fileCallback.onReceiveValue(null); fileCallback = null; }
                return true;
            }
        });
        web.loadUrl(START_URL);
    }

    private void applyImmersiveMode() {
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {
                controller.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                if (immersiveRequested) controller.hide(WindowInsets.Type.systemBars());
                else controller.show(WindowInsets.Type.systemBars());
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(immersiveRequested
                ? View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                : View.SYSTEM_UI_FLAG_VISIBLE);
        }
    }

    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) applyImmersiveMode();
    }

    private final class NativeBridge {
        @JavascriptInterface public String getItem(String key) { return state.get(key); }
        @JavascriptInterface public void setItem(String key, String value) { state.put(key, value); }
        @JavascriptInterface public void removeItem(String key) { state.remove(key); }
        @JavascriptInterface public String listPacks() { return packs.list().toString(); }
        @JavascriptInterface public void setImmersive(boolean enabled) {
            runOnUiThread(() -> { immersiveRequested = enabled; applyImmersiveMode(); });
        }

        @JavascriptInterface public String getAppInfo() {
            try {
                PackageInfo info = getPackageManager().getPackageInfo(getPackageName(), 0);
                return new JSONObject().put("name", "InstaAnki").put("packageName", getPackageName())
                    .put("version", info.versionName).put("versionCode", info.versionCode).put("nativeApi", 3)
                    .put("storage", "SQLite").put("offline", true).put("zipImport", true)
                    .put("feedbackExport", true).put("downloadSizeVerification", true)
                    .put("downloadCompatibilityVerification", true).put("immersiveFeed", true)
                    .put("platform", "Android").put("androidVersion", Build.VERSION.RELEASE).toString();
            } catch (Exception e) { return "{}"; }
        }

        @JavascriptInterface public void importZip() {
            runOnUiThread(() -> {
                if (importing.get()) { toast("A content package is already being imported."); return; }
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("*/*").putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/zip", "application/x-zip-compressed", "application/octet-stream"});
                try { startActivityForResult(intent, PICK_PACK); }
                catch (Exception e) { failure("No file picker is available on this device."); }
            });
        }

        @JavascriptInterface public void exportBackup() {
            runOnUiThread(() -> {
                Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("application/json").putExtra(Intent.EXTRA_TITLE, "InstaAnki-backup-" + System.currentTimeMillis() + ".json");
                try { startActivityForResult(intent, EXPORT_BACKUP); }
                catch (Exception e) { failure("No document saver is available on this device."); }
            });
        }

        @JavascriptInterface public void importBackup() {
            runOnUiThread(() -> {
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("*/*").putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/json", "text/plain", "application/octet-stream"});
                try { startActivityForResult(intent, IMPORT_BACKUP); }
                catch (Exception e) { failure("No document picker is available on this device."); }
            });
        }

        @JavascriptInterface public boolean shareFeedback(String document) {
            final String checked;
            try { checked = FeedbackData.exportDocument(document).toString(2); }
            catch (Exception invalid) { failure("The feedback report could not be prepared. Your saved reports are still on this device."); return false; }
            io.execute(() -> {
                try {
                    File directory = new File(getCacheDir(), "feedback-exports");
                    if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Unable to prepare feedback sharing.");
                    // Old shared copies may be removed; the durable local reports remain in SQLite.
                    File[] old = directory.listFiles();
                    if (old != null) for (File item : old) if (item.isFile() && item.lastModified() < System.currentTimeMillis() - 7L * 24 * 60 * 60 * 1000) item.delete();
                    File file = new File(directory, "InstaAnki-feedback-" + java.util.UUID.randomUUID() + ".json");
                    try (FileOutputStream output = new FileOutputStream(file)) { output.write(checked.getBytes(StandardCharsets.UTF_8)); output.getFD().sync(); }
                    Uri uri = new Uri.Builder().scheme("content").authority(getPackageName() + ".feedback").appendPath("reports").appendPath(file.getName()).build();
                    runOnUiThread(() -> {
                        Intent send = new Intent(Intent.ACTION_SEND).setType("application/json")
                            .putExtra(Intent.EXTRA_STREAM, uri)
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                        send.setClipData(ClipData.newRawUri("InstaAnki feedback", uri));
                        try { startActivity(Intent.createChooser(send, "Share feedback report")); }
                        catch (Exception unavailable) { failure("No app is available to share this file. Use Save feedback file instead."); }
                    });
                } catch (Exception error) { failure(error.getMessage()); }
            });
            // This means the chooser was requested, never that a report was sent.
            return true;
        }

        @JavascriptInterface public boolean exportFeedback(String document) {
            try {
                if (pendingFeedbackExport != null) { failure("Finish saving the current feedback file first."); return false; }
                pendingFeedbackExport = FeedbackData.exportDocument(document).toString(2);
            } catch (Exception invalid) { failure("The feedback report could not be prepared."); return false; }
            runOnUiThread(() -> {
                Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("application/json").putExtra(Intent.EXTRA_TITLE, "InstaAnki-feedback-" + System.currentTimeMillis() + ".json");
                try { startActivityForResult(intent, EXPORT_FEEDBACK); }
                catch (Exception unavailable) { pendingFeedbackExport = null; failure("No document saver is available on this device."); }
            });
            return true;
        }

        @JavascriptInterface public void downloadPack(String url, String expectedSha256) {
            startDownload(url, expectedSha256, -1);
        }

        @JavascriptInterface public void downloadPackVerified(String url, String expectedSha256, long expectedBytes) {
            if (expectedBytes <= 0) { failure("The update catalog does not provide a valid package size. Nothing was installed."); return; }
            startDownload(url, expectedSha256, expectedBytes);
        }

        @JavascriptInterface public void downloadPackCompatible(String url, String expectedSha256, long expectedBytes, double minimumAppVersionCode) {
            if (expectedBytes <= 0) { failure("The update catalog does not provide a valid package size. Nothing was installed."); return; }
            startDownload(url, expectedSha256, expectedBytes, minimumAppVersionCode);
        }

        private void startDownload(String url, String expectedSha256, long expectedBytes) {
            startDownload(url, expectedSha256, expectedBytes, 1);
        }

        private void startDownload(String url, String expectedSha256, long expectedBytes, double minimumAppVersionCode) {
            final int installedVersionCode;
            try {
                installedVersionCode = getPackageManager().getPackageInfo(getPackageName(), 0).versionCode;
                PackDownloader.requireCompatibleApp(minimumAppVersionCode, installedVersionCode);
            } catch (Exception error) { failure(error.getMessage()); return; }
            if (!importing.compareAndSet(false, true)) { failure("A content package is already being installed."); return; }
            emit("instaanki:import-started", new JSONObject());
            io.execute(() -> {
                File downloaded = null;
                try {
                    downloaded = PackDownloader.downloadCompatible(url, expectedSha256, expectedBytes, minimumAppVersionCode,
                            installedVersionCode, new File(getCacheDir(), "pack-downloads"), (received, total) -> {
                        try {
                            emit("instaanki:download-progress", new JSONObject().put("receivedBytes", received)
                                .put("totalBytes", total > 0 ? total : JSONObject.NULL)
                                .put("percent", total > 0 ? Math.round(received * 100.0 / total) : JSONObject.NULL));
                        } catch (Exception ignored) { }
                    });
                    try (InputStream input = new FileInputStream(downloaded)) {
                        JSONObject result = packs.importZip(input);
                        emit("instaanki:pack-imported", result);
                        toast("Content package downloaded and installed.");
                    }
                } catch (Exception e) { failure(e.getMessage()); }
                finally { if (downloaded != null) downloaded.delete(); importing.set(false); }
            });
        }

        @JavascriptInterface public void openExternal(String url) {
            Uri uri = Uri.parse(url == null ? "" : url);
            if (!"https".equals(uri.getScheme())) return;
            runOnUiThread(() -> openExternalLink(uri));
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        Uri uri = data == null ? null : data.getData();
        if (requestCode == WEB_FILE_PICKER) {
            if (fileCallback != null) { fileCallback.onReceiveValue(resultCode == RESULT_OK && uri != null ? new Uri[]{uri} : null); fileCallback = null; }
            return;
        }
        if (resultCode != RESULT_OK || uri == null) { if (requestCode == EXPORT_FEEDBACK) pendingFeedbackExport = null; return; }
        if (requestCode == PICK_PACK) {
            if (!importing.compareAndSet(false, true)) { failure("A content package is already being installed."); return; }
            emit("instaanki:import-started", new JSONObject());
            io.execute(() -> {
                try (InputStream input = getContentResolver().openInputStream(uri)) {
                    if (input == null) throw new IOException("Unable to read the selected file.");
                    JSONObject result = packs.importZip(input);
                    emit("instaanki:pack-imported", result);
                    toast("Content package imported. Your learning history is preserved.");
                } catch (Exception e) { failure(e.getMessage()); }
                finally { importing.set(false); }
            });
        } else if (requestCode == EXPORT_BACKUP) {
            io.execute(() -> {
                try (OutputStream output = getContentResolver().openOutputStream(uri, "wt")) {
                    if (output == null) throw new IOException("Unable to create the backup.");
                    output.write(state.exportData().toString(2).getBytes(StandardCharsets.UTF_8));
                    emit("instaanki:backup-exported", new JSONObject().put("ok", true));
                    toast("Learning backup saved.");
                } catch (Exception e) { failure(e.getMessage()); }
            });
        } else if (requestCode == EXPORT_FEEDBACK) {
            final String feedback = pendingFeedbackExport; pendingFeedbackExport = null;
            if (feedback == null) { failure("The feedback export was interrupted. Your reports are saved; choose Save feedback file again."); return; }
            io.execute(() -> {
                try (OutputStream output = getContentResolver().openOutputStream(uri, "wt")) {
                    if (output == null) throw new IOException("Unable to create the feedback file.");
                    output.write(feedback.getBytes(StandardCharsets.UTF_8));
                    emit("instaanki:feedback-exported", new JSONObject().put("ok", true));
                    toast("Feedback file saved. It contains reports only, not your private notes or review history.");
                } catch (Exception e) { failure(e.getMessage()); }
            });
        } else if (requestCode == IMPORT_BACKUP) {
            io.execute(() -> {
                try (InputStream input = getContentResolver().openInputStream(uri)) {
                    if (input == null) throw new IOException("Unable to open the selected backup.");
                    ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                    byte[] buffer = new byte[32 * 1024]; int count;
                    while ((count = input.read(buffer)) != -1) {
                        if (bytes.size() + count > 32 * 1024 * 1024) throw new IOException("The backup exceeds the 32 MiB limit.");
                        bytes.write(buffer, 0, count);
                    }
                    JSONObject backup = new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8));
                    int restored = state.importData(backup);
                    emit("instaanki:backup-imported", new JSONObject().put("ok", true).put("keysRestored", restored));
                    toast("Learning backup restored. Downloaded content was preserved.");
                } catch (Exception e) { failure(e.getMessage()); }
            });
        }
    }

    private final class LocalClient extends WebViewClient {
        @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if ("https".equals(uri.getScheme()) && HOST.equals(uri.getHost())
                && "/assets/index.html".equals(uri.getPath())) return false;
            if (request.isForMainFrame() && "https".equals(uri.getScheme()) && !HOST.equals(uri.getHost())) {
                openExternalLink(uri);
            }
            return true;
        }

        @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if (!"https".equals(uri.getScheme())) return error(403, "Blocked");
            if (!HOST.equals(uri.getHost())) {
                // Only images and explicitly requested data may be fetched remotely. UI scripts remain bundled.
                String destination = request.getRequestHeaders().get("Sec-Fetch-Dest");
                String path = uri.getPath() == null ? "" : uri.getPath().toLowerCase(Locale.ROOT);
                if (request.isForMainFrame() || "script".equals(destination) || "iframe".equals(destination)
                    || "document".equals(destination) || path.endsWith(".js") || path.endsWith(".mjs")
                    || path.endsWith(".html") || path.endsWith(".htm")) return error(403, "Blocked");
                return null;
            }
            try {
                String path = uri.getPath();
                if (path == null || path.contains("..") || path.contains("\\") || path.indexOf('\u0000') >= 0) return error(403, "Blocked");
                if (path.startsWith("/assets/")) {
                    String asset = "www/" + path.substring("/assets/".length());
                    if (asset.endsWith("/")) asset += "index.html";
                    long size;
                    InputStream input;
                    try {
                        AssetFileDescriptor afd = getAssets().openFd(asset);
                        size = afd.getLength();
                        input = afd.createInputStream();
                    } catch (IOException compressed) {
                        input = getAssets().open(asset);
                        size = input.available();
                    }
                    return resource(path, input, size, request.getRequestHeaders());
                }
                if (path.startsWith("/content/")) {
                    File file = packs.resolve(path.substring("/content/".length()));
                    if (!file.isFile()) return error(404, "Not Found");
                    return resource(path, new FileInputStream(file), file.length(), request.getRequestHeaders());
                }
                return error(404, "Not Found");
            } catch (Exception e) { return error(404, "Not Found"); }
        }
    }

    private WebResourceResponse resource(String path, InputStream input, long total, Map<String, String> requestHeaders) throws IOException {
        Map<String, String> headers = new HashMap<>();
        headers.put("Access-Control-Allow-Origin", "https://" + HOST);
        headers.put("Accept-Ranges", "bytes");
        headers.put("X-Content-Type-Options", "nosniff");
        headers.put("Cache-Control", "no-cache");
        headers.put("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; media-src 'self' blob:; connect-src 'self' https:; font-src 'self' data:; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'");
        String range = null;
        for (Map.Entry<String, String> e : requestHeaders.entrySet()) if (e.getKey().equalsIgnoreCase("Range")) range = e.getValue();
        int status = 200;
        String reason = "OK";
        long length = total;
        if (range != null && range.startsWith("bytes=") && !range.contains(",") && total > 0) {
            try {
                String[] bounds = range.substring(6).split("-", -1);
                if (bounds.length != 2) throw new IllegalArgumentException();
                long start = bounds[0].isEmpty() ? Math.max(0, total - Long.parseLong(bounds[1])) : Long.parseLong(bounds[0]);
                long end = bounds[0].isEmpty() || bounds[1].isEmpty() ? total - 1 : Math.min(total - 1, Long.parseLong(bounds[1]));
                if (start < 0 || start >= total || end < start) throw new IllegalArgumentException();
                long remaining = start;
                while (remaining > 0) { long skipped = input.skip(remaining); if (skipped <= 0) { if (input.read() == -1) throw new IOException("Truncated media"); skipped = 1; } remaining -= skipped; }
                length = end - start + 1;
                input = new LimitedStream(input, length);
                headers.put("Content-Range", "bytes " + start + "-" + end + "/" + total);
                status = 206; reason = "Partial Content";
            } catch (RuntimeException invalid) {
                input.close(); return error(416, "Range Not Satisfiable");
            }
        }
        headers.put("Content-Length", Long.toString(length));
        String mime = mimeType(path);
        String encoding = mime.startsWith("text/") || mime.contains("json") || mime.contains("javascript") || mime.contains("svg") ? "UTF-8" : null;
        return new WebResourceResponse(mime, encoding, status, reason, headers, input);
    }

    private static final class LimitedStream extends FilterInputStream {
        private long remaining;
        LimitedStream(InputStream in, long limit) { super(in); remaining = limit; }
        @Override public int read() throws IOException { if (remaining <= 0) return -1; int r = super.read(); if (r >= 0) remaining--; return r; }
        @Override public int read(byte[] b, int off, int len) throws IOException {
            if (remaining <= 0) return -1;
            int r = in.read(b, off, (int) Math.min(len, remaining)); if (r > 0) remaining -= r; return r;
        }
        @Override public long skip(long count) throws IOException { long r = in.skip(Math.min(count, remaining)); remaining -= r; return r; }
    }

    private static String mimeType(String path) {
        String p = path.toLowerCase(Locale.ROOT);
        if (p.endsWith(".html")) return "text/html";
        if (p.endsWith(".js") || p.endsWith(".mjs")) return "application/javascript";
        if (p.endsWith(".css")) return "text/css";
        if (p.endsWith(".json")) return "application/json";
        if (p.endsWith(".svg")) return "image/svg+xml";
        if (p.endsWith(".png")) return "image/png";
        if (p.endsWith(".jpg") || p.endsWith(".jpeg")) return "image/jpeg";
        if (p.endsWith(".webp")) return "image/webp";
        if (p.endsWith(".avif")) return "image/avif";
        if (p.endsWith(".gif")) return "image/gif";
        if (p.endsWith(".mp3")) return "audio/mpeg";
        if (p.endsWith(".m4a")) return "audio/mp4";
        if (p.endsWith(".aac")) return "audio/aac";
        if (p.endsWith(".wav")) return "audio/wav";
        if (p.endsWith(".ogg") || p.endsWith(".opus")) return "audio/ogg";
        if (p.endsWith(".mp4")) return "video/mp4";
        if (p.endsWith(".webm")) return "video/webm";
        if (p.endsWith(".vtt")) return "text/vtt";
        if (p.endsWith(".woff2")) return "font/woff2";
        if (p.endsWith(".woff")) return "font/woff";
        if (p.endsWith(".ttf")) return "font/ttf";
        if (p.endsWith(".txt")) return "text/plain";
        return "application/octet-stream";
    }

    private static WebResourceResponse error(int code, String message) {
        Map<String, String> headers = new HashMap<>();
        headers.put("Cache-Control", "no-store");
        return new WebResourceResponse("text/plain", "UTF-8", code, message, headers,
            new ByteArrayInputStream(message.getBytes(StandardCharsets.UTF_8)));
    }

    private void openExternalLink(Uri uri) {
        try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); }
        catch (Exception e) { toast("No browser is available to open this source."); }
    }

    private void emit(String name, JSONObject detail) {
        String data = detail.toString().replace("\u2028", "\\u2028").replace("\u2029", "\\u2029");
        runOnUiThread(() -> { if (web != null) web.evaluateJavascript("window.dispatchEvent(new CustomEvent(" + JSONObject.quote(name) + ",{detail:" + data + "}));", null); });
    }

    private void failure(String message) {
        String safe = message == null || message.isEmpty() ? "The operation could not be completed." : message;
        try { emit("instaanki:error", new JSONObject().put("message", safe)); } catch (Exception ignored) { }
        toast(safe);
    }

    private void toast(String message) { runOnUiThread(() -> Toast.makeText(this, message, Toast.LENGTH_LONG).show()); }

    @Override protected void onPause() {
        if (web != null) {
            web.evaluateJavascript("document.querySelectorAll('audio,video').forEach(function(m){m.pause()});window.dispatchEvent(new Event('instaanki:background'));", null);
            web.onPause();
        }
        super.onPause();
    }

    @Override protected void onResume() { super.onResume(); if (web != null) web.onResume(); }

    @Override public void onBackPressed() {
        web.evaluateJavascript("typeof window.InstaAnkiBack==='function' ? !!window.InstaAnkiBack() : false", handled -> {
            if (!"true".equals(handled)) { if (web.canGoBack()) web.goBack(); else MainActivity.super.onBackPressed(); }
        });
    }

    @Override protected void onDestroy() {
        if (fileCallback != null) fileCallback.onReceiveValue(null);
        io.shutdown();
        if (web != null) { web.removeJavascriptInterface("AndroidNative"); web.destroy(); web = null; }
        // SQLite stays available to any import/export job completing during recreation.
        super.onDestroy();
    }
}
