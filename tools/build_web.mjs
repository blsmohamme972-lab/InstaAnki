import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const args = process.argv.slice(2);
if (args.length && !(args.length === 2 && args[0] === '--profile' && ['fresh', 'standard'].includes(args[1]))) {
  console.error('Usage: node tools/build_web.mjs [--profile standard|fresh]'); process.exit(1);
}
const profile = args[1] || 'standard';
const output = profile === 'fresh' ? 'build/fresh-web/learning.js' : 'web/learning.js';
const checked = spawnSync('python3', [
  fileURLToPath(new URL('./check_source_scope.py', import.meta.url)),
  '--web-root', fileURLToPath(new URL('../web/', import.meta.url)),
  '--profile', profile,
  ...(profile === 'fresh' ? ['--prepare-fresh', fileURLToPath(new URL('../build/fresh-web/', import.meta.url))] : []),
], {cwd: root, stdio: 'inherit'});
if (checked.error) {
  console.error(`Source scope check failed: ${checked.error.message}`);
  process.exit(1);
}
if (checked.status !== 0) process.exit(checked.status || 1);

// Keep the check inside this entry point so direct node invocations also stop
// before changing the bundle, even when npm lifecycle hooks are not used.
const {build} = await import('esbuild');
await build({absWorkingDir:root,entryPoints:['web/learning.entry.js'],outfile:output,bundle:true,format:'iife',target:['chrome90'],minify:true,legalComments:'eof'});
