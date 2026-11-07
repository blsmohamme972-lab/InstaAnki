/// <reference types="vitest/config" />
import { readFileSync } from 'node:fs';
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as {
  version: string;
  instaanki: { minShellVersion: number };
};

/** Emits bundle-info.json so the native shell knows the version of the web bundle it ships. */
function bundleInfo(): Plugin {
  return {
    name: 'instaanki-bundle-info',
    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: 'bundle-info.json',
        source: JSON.stringify({
          bundleVersion: pkg.version,
          minShellVersion: pkg.instaanki.minShellVersion,
        }),
      });
    },
  };
}

export default defineConfig({
  base: './',
  plugins: [react(), bundleInfo()],
  define: {
    __BUNDLE_VERSION__: JSON.stringify(pkg.version),
  },
  build: {
    outDir: 'dist',
    target: 'es2022',
    sourcemap: false,
  },
  server: {
    // the JSON schemas live in ../schema
    fs: { allow: ['..'] },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'scripts/**/*.test.ts'],
  },
});
