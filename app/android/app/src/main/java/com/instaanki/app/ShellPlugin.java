package com.instaanki.app;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.instaanki.app.ota.OtaController;
import java.io.File;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** JS API: app/src/platform/shell.ts */
@CapacitorPlugin(name = "InstaAnkiShell")
public class ShellPlugin extends Plugin {

    private static final AtomicBoolean AUTO_CHECKED = new AtomicBoolean(false);
    private final ExecutorService io = Executors.newSingleThreadExecutor();

    private OtaController ota() {
        return OtaController.get(getContext());
    }

    @Override
    public void load() {
        ota().attach(getActivity());
    }

    @PluginMethod
    public void getInfo(PluginCall call) {
        OtaController ota = ota();
        JSObject ret = new JSObject();
        ret.put("shellVersion", ota.shellVersion());
        ret.put("bundleVersion", ota.runningVersion());
        ret.put("bundleSource", ota.runningBuiltin() ? "builtin" : "downloaded");
        String rb = ota.rolledBackFrom();
        ret.put("rolledBackFrom", rb.isEmpty() ? JSObject.NULL : rb);
        ret.put("updateChannel", BuildConfig.OTA_BASE_URL);
        call.resolve(ret);
    }

    @PluginMethod
    public void notifyAppReady(PluginCall call) {
        ota().onAppReady();
        call.resolve();
        // first confirmed start of this process: look for updates in the background
        if (AUTO_CHECKED.compareAndSet(false, true)) io.execute(() -> present(ota().check()));
    }

    @PluginMethod
    public void checkForUpdate(PluginCall call) {
        final boolean interactive = Boolean.TRUE.equals(call.getBoolean("interactive", false));
        io.execute(() -> {
            OtaController.CheckResult r = ota().check();
            JSObject ret = new JSObject();
            ret.put("status", r.status.js);
            if (r.manifest != null) ret.put("latest", r.manifest.bundleVersion);
            if (r.message != null) ret.put("message", r.message);
            call.resolve(ret);
            if (interactive) present(r);
        });
    }

    @PluginMethod
    public void takeIncomingFiles(PluginCall call) {
        JSArray files = new JSArray();
        for (File f : IncomingFiles.pending(getContext())) {
            JSObject o = new JSObject();
            o.put("path", IncomingFiles.DIR + "/" + f.getName());
            o.put("name", f.getName());
            files.put(o);
        }
        JSObject ret = new JSObject();
        ret.put("files", files);
        call.resolve(ret);
    }

    /** Called by MainActivity after a shared file was saved. */
    void notifyIncoming() {
        notifyListeners("incomingFile", new JSObject(), true);
    }

    private void present(OtaController.CheckResult r) {
        if (getActivity() == null) return;
        getActivity().runOnUiThread(() -> {
            switch (r.status) {
                case UPDATE_AVAILABLE:
                    UpdateUi.offerUpdate(getActivity(), ota(), getBridge(), r, io);
                    break;
                case NEEDS_APK:
                    UpdateUi.needsApk(getActivity(), r);
                    break;
                default:
                    break;
            }
        });
    }
}
