import {build} from 'esbuild';
await build({entryPoints:['web/learning.entry.js'],outfile:'web/learning.js',bundle:true,format:'iife',target:['chrome90'],minify:true,legalComments:'eof'});
