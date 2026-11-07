package com.instaanki.app;

import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.PluginHandle;
import com.instaanki.app.ota.OtaController;
import java.util.List;

public class MainActivity extends BridgeActivity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        // Pick the web bundle (built-in / downloaded / rollback) before the bridge reads it.
        OtaController ota = OtaController.get(this);
        ota.prepareStartup();
        ota.attach(this);
        registerPlugin(ShellPlugin.class);
        super.onCreate(savedInstanceState);
        if (savedInstanceState == null) receive(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        receive(intent);
    }

    private void receive(Intent intent) {
        final List<Uri> uris = IncomingFiles.urisOf(intent);
        if (uris.isEmpty()) return;
        new Thread(() -> {
            if (IncomingFiles.save(getApplicationContext(), uris) > 0) {
                runOnUiThread(() -> {
                    PluginHandle handle = getBridge() == null ? null : getBridge().getPlugin("InstaAnkiShell");
                    if (handle != null) ((ShellPlugin) handle.getInstance()).notifyIncoming();
                });
            }
        }, "incoming-files").start();
    }
}
