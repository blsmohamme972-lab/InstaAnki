import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { editJson, editText, loadDir, reelPath, SAMPLE_PACK_DIR } from './testkit';
import { validatePack, type PackFiles } from './validate';

type Mutation = [name: string, fn: (f: PackFiles) => void];

const REEL = reelPath('reel.json');
const MUTATIONS: Mutation[] = [
  ['answer index out of range', (f) => editJson(f, REEL, (r) => (r.questions[1].answer = 7))],
  ['explain points to a missing segment', (f) => editJson(f, REEL, (r) => (r.questions[2].explain = 'nope'))],
  ['svgId not in the svg', (f) => editJson(f, REEL, (r) => (r.regions.aorta.svgId = 'aorta-missing'))],
  [
    'cue outside the audio and unknown region',
    (f) => editJson(f, REEL, (r) => r.cues.push({ t: 500, type: 'pulse', region: 'ghost' })),
  ],
  ['unsafe svg with baked text', (f) => editText(f, reelPath('img/heart.svg'), (s) => s.replace('</svg>', '<text x="1" y="1">LV</text><script>alert(1)</script></svg>'))],
  ['unknown field', (f) => editJson(f, REEL, (r) => (r.questions[3].typo_field = 1))],
  ['missing audio file', (f) => f.delete(reelPath('audio.opus'))],
  ['pretest is not mcq/truefalse', (f) => editJson(f, REEL, (r) => (r.pretest = 'q-case-htn'))],
  ['no show cue at t=0', (f) => editJson(f, REEL, (r) => (r.cues = r.cues.filter((c: any) => c.type !== 'show')))],
  ['cloze cut not on a word', (f) => editJson(f, REEL, (r) => (r.questions.find((q: any) => q.type === 'cloze').cut = 44.3))],
  ['overlapping segments', (f) => editJson(f, REEL, (r) => (r.segments[1].start = 2))],
  ['transcript out of order', (f) => editJson(f, reelPath('transcript.json'), (t) => ([t.words[3], t.words[4]] = [t.words[4], t.words[3]]))],
  ['pack.json is not JSON', (f) => f.set('pack.json', new TextEncoder().encode('{ nope'))],
  ['listed reel without folder', (f) => editJson(f, 'pack.json', (p) => p.reels.push('ghost-reel-001'))],
  ['camera target missing', (f) => editJson(f, REEL, (r) => r.cues.push({ t: 3, type: 'camera' }))],
  ['region outside image', (f) => editJson(f, REEL, (r) => (r.regions.extra = { image: 'heart', label: 'x', rect: { x: 0.9, y: 0.1, w: 0.3, h: 0.1 } }))],
];

describe('validatePack', () => {
  it('accepts the example pack with no errors or warnings', () => {
    const report = validatePack(loadDir(SAMPLE_PACK_DIR));
    expect(report.errors).toEqual([]);
    expect(report.warnings).toEqual([]);
    expect(report.ok).toBe(true);
    expect(report.reels.size).toBe(1);
  });

  it.each(MUTATIONS)('rejects or flags: %s', (_name, mutate) => {
    const files = loadDir(SAMPLE_PACK_DIR);
    mutate(files);
    const report = validatePack(files);
    expect(report.errors.length + report.warnings.length).toBeGreaterThan(0);
  });
});

const python = spawnSync('python3', ['-c', 'import jsonschema'], { encoding: 'utf8' });
const hasPython = python.status === 0;
const VALIDATOR = new URL('../../../tools/validate_pack.py', import.meta.url).pathname;

function runPython(files: PackFiles): { ok: boolean; errors: string[]; warnings: string[] } {
  const dir = mkdtempSync(join(tmpdir(), 'instaanki-parity-'));
  try {
    for (const [path, data] of files) {
      mkdirSync(dirname(join(dir, path)), { recursive: true });
      writeFileSync(join(dir, path), data);
    }
    const res = spawnSync('python3', [VALIDATOR, dir], { encoding: 'utf8' });
    const lines = res.stdout.split('\n');
    return {
      ok: res.status === 0,
      errors: lines.filter((l) => l.startsWith('ERROR   ')).map((l) => l.slice(8)),
      warnings: lines.filter((l) => l.startsWith('WARNING ')).map((l) => l.slice(8)),
    };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

/** Schema error wording differs between ajv and python-jsonschema; every other message must match exactly. */
const nonSchema = (lines: string[]) =>
  lines
    .filter((l) => !l.includes('] schema: '))
    .map((l) => l.replace(/(invalid JSON in [^:]+:).*/, '$1')) // parser wording is language-specific
    .sort();

describe.skipIf(!hasPython)('parity with tools/validate_pack.py', () => {
  it.each([['unchanged example', () => undefined] as Mutation, ...MUTATIONS])('%s', (_name, mutate) => {
    const files = loadDir(SAMPLE_PACK_DIR);
    mutate(files);
    const ts = validatePack(files);
    const py = runPython(files);
    expect(ts.ok).toBe(py.ok);
    expect(nonSchema(ts.errors)).toEqual(nonSchema(py.errors));
    expect(nonSchema(ts.warnings)).toEqual(nonSchema(py.warnings));
    expect(ts.errors.some((l) => l.includes('] schema: '))).toBe(py.errors.some((l) => l.includes('] schema: ')));
  });
});
