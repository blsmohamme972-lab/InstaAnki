import { Capacitor, registerPlugin, type PluginListenerHandle } from '@capacitor/core';

/** Native side: android/app/src/main/java/com/instaanki/app/ShellPlugin.kt */
export interface ShellInfo {
  /** versionCode of the installed APK. 0 in the browser. */
  shellVersion: number;
  /** Version of the web bundle that is running now. */
  bundleVersion: string;
  bundleSource: 'builtin' | 'downloaded';
  /** Set when the previous launch of a downloaded bundle failed and the shell went back. */
  rolledBackFrom: string | null;
  updateChannel: string;
}

export type UpdateStatus = 'up-to-date' | 'update-available' | 'needs-apk' | 'offline' | 'error' | 'unsupported';

export interface IncomingFile {
  /** Path relative to the Cache directory. */
  path: string;
  name: string;
}

export interface ShellPlugin {
  getInfo(): Promise<ShellInfo>;
  /** Must be called once the app has started correctly, or the shell rolls the bundle back. */
  notifyAppReady(): Promise<void>;
  /** interactive: show the native "update available" dialog when there is one. */
  checkForUpdate(options: { interactive: boolean }): Promise<{ status: UpdateStatus; latest?: string; message?: string }>;
  /** Zip files shared to the app ("Share -> InstaAnki") that were not processed yet. */
  takeIncomingFiles(): Promise<{ files: IncomingFile[] }>;
  addListener(event: 'incomingFile', fn: (file: IncomingFile) => void): Promise<PluginListenerHandle>;
}

const web: ShellPlugin = {
  async getInfo() {
    return {
      shellVersion: 0,
      bundleVersion: __BUNDLE_VERSION__,
      bundleSource: 'builtin',
      rolledBackFrom: null,
      updateChannel: 'web',
    };
  },
  async notifyAppReady() {},
  async checkForUpdate() {
    return { status: 'unsupported' };
  },
  async takeIncomingFiles() {
    return { files: [] };
  },
  async addListener() {
    return { remove: async () => {} };
  },
};

export const Shell = registerPlugin<ShellPlugin>('InstaAnkiShell', { web: () => web });

export const isNative = (): boolean => Capacitor.isNativePlatform();
