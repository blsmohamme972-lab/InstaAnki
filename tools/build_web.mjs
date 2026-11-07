import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const checked = spawnSync('python3', [
  fileURLToPath(new URL('./check_source_scope.py', import.meta.url)),
  '--web-root', fileURLToPath(new URL('../web/', import.meta.url)),
], {cwd: root, stdio: 'inherit'});
if (checked.error) {
  console.error(`Source scope check failed: ${checked.error.message}`);
  process.exit(1);
}
if (checked.status !== 0) process.exit(checked.status || 1);

// Keep the check inside this entry point so direct node invocations also stop
// before changing the bundle, even when npm lifecycle hooks are not used.
const {build} = await import('esbuild');
await build({absWorkingDir:root,entryPoints:['web/learning.entry.js'],outfile:'web/learning.js',bundle:true,format:'iife',target:['chrome90'],minify:true,legalComments:'eof'});
