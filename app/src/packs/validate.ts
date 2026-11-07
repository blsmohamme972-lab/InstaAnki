/**
 * In-app pack validator. Mirrors tools/validate_pack.py (the tool GPT runs before delivering a pack);
 * a parity test runs both on the same fixtures. Keep the two in sync when changing rules.
 */
import Ajv2020, { type ErrorObject, type ValidateFunction } from 'ajv/dist/2020';
import packSchema from '../../../schema/pack.schema.json';
import reelSchema from '../../../schema/reel.schema.json';
import transcriptSchema from '../../../schema/transcript.schema.json';

/* eslint-disable @typescript-eslint/no-explicit-any -- untrusted JSON is checked field by field */
type J = any;

export type PackFiles = Map<string, Uint8Array>;

export interface ValidationReport {
  errors: string[];
  warnings: string[];
  infos: string[];
  ok: boolean;
  pack?: J;
  reels: Map<string, J>;
}

const AUDIO_EXT = new Set(['.opus', '.ogg', '.m4a', '.mp3', '.wav']);
const IMAGE_EXT = new Set(['.svg', '.webp', '.png', '.jpg', '.jpeg']);
const MAX_IMAGE_BYTES = 1_500_000;
const MAX_AUDIO_BYTES = 3_000_000;
const RECOMMENDED_DURATION: [number, number] = [55, 100];
const AUDIO_TOLERANCE = 0.5;

const SVG_ID_RE = /\bid\s*=\s*["']([^"']+)["']/g;
const SVG_DANGER: [RegExp, string][] = [
  [/<\s*script\b/i, 'contains <script>'],
  [/<\s*foreignObject\b/i, 'contains <foreignObject>'],
  [/\son[a-z]+\s*=/i, 'contains an event handler attribute (on...=)'],
  [/(?:xlink:)?href\s*=\s*["']\s*(?:https?:|javascript:|data:text\/html)/i, 'references an external/script URL'],
];
const SVG_TEXT_RE = /<\s*text\b/i;

let validators: { pack: ValidateFunction; reel: ValidateFunction; transcript: ValidateFunction } | null = null;
function getValidators() {
  if (!validators) {
    const ajv = new Ajv2020({ allErrors: true, strict: false });
    validators = {
      pack: ajv.compile(packSchema),
      reel: ajv.compile(reelSchema),
      transcript: ajv.compile(transcriptSchema),
    };
  }
  return validators;
}

const decoder = new TextDecoder('utf-8', { fatal: true });
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const isInt = (v: unknown): v is number => Number.isInteger(v);
const isObj = (v: unknown): v is Record<string, J> => typeof v === 'object' && v !== null && !Array.isArray(v);
const ext = (p: string) => {
  const name = p.split('/').at(-1) ?? '';
  const i = name.lastIndexOf('.');
  return i >= 0 ? name.slice(i).toLowerCase() : '';
};
const basename = (p: string) => p.split('/').at(-1) ?? p;
const fmt = (n: number) => n.toFixed(1);

function formatSchemaError(e: ErrorObject): string | null {
  if (e.keyword === 'if') return null; // the real cause is reported by the "then" branch
  const loc = e.instancePath.replace(/^\//, '') || '(root)';
  let msg = e.message ?? 'invalid';
  if (e.keyword === 'additionalProperties') msg += ` ('${(e.params as { additionalProperty: string }).additionalProperty}')`;
  if (e.keyword === 'enum') msg += `: ${JSON.stringify((e.params as { allowedValues: unknown[] }).allowedValues)}`;
  return `schema: ${loc}: ${msg}`;
}

class Reporter {
  errors: string[] = [];
  warnings: string[] = [];
  infos: string[] = [];
  err(where: string, msg: string) {
    this.errors.push(`[${where}] ${msg}`);
  }
  warn(where: string, msg: string) {
    this.warnings.push(`[${where}] ${msg}`);
  }
  info(where: string, msg: string) {
    this.infos.push(`[${where}] ${msg}`);
  }
  schema(fn: ValidateFunction, obj: unknown, where: string): boolean {
    if (fn(obj)) return true;
    const seen = new Set<string>();
    for (const e of fn.errors ?? []) {
      const line = formatSchemaError(e);
      if (line && !seen.has(line)) {
        seen.add(line);
        this.err(where, line);
      }
    }
    return false;
  }
}

function safeJoin(dir: string, rel: unknown, rep: Reporter, where: string): string | null {
  if (typeof rel !== 'string') return null;
  const parts = rel.split('/');
  if (rel.startsWith('/') || rel.includes('\\') || parts.includes('..')) {
    rep.err(where, `unsafe path: ${rel}`);
    return null;
  }
  return [dir, ...parts.filter((p) => p !== '' && p !== '.')].join('/');
}

function loadJson(files: PackFiles, path: string, rep: Reporter, where: string): J | undefined {
  const bytes = files.get(path);
  if (!bytes) {
    rep.err(where, `missing file: ${basename(path)}`);
    return undefined;
  }
  try {
    return JSON.parse(decoder.decode(bytes));
  } catch (e) {
    rep.err(where, `invalid JSON in ${basename(path)}: ${(e as Error).message}`);
    return undefined;
  }
}

function checkSvg(files: PackFiles, path: string, rep: Reporter, where: string): Set<string> {
  let src: string;
  try {
    src = decoder.decode(files.get(path)!);
  } catch {
    rep.err(where, `${basename(path)}: SVG is not UTF-8 text`);
    return new Set();
  }
  for (const [rx, msg] of SVG_DANGER) {
    if (rx.test(src)) rep.err(where, `${basename(path)}: unsafe SVG, ${msg}`);
  }
  if (SVG_TEXT_RE.test(src)) {
    rep.warn(where, `${basename(path)}: SVG contains <text>; labels must be overlays (regions.label), not baked into images`);
  }
  return new Set([...src.matchAll(SVG_ID_RE)].map((m) => m[1]!));
}

function validateReel(files: PackFiles, reelDir: string, reelId: string, packReels: Map<string, J>, rep: Reporter): void {
  const where = `reel ${reelId}`;
  const reel = packReels.get(reelId);
  if (!isObj(reel)) return;
  const v = getValidators();
  if (!rep.schema(v.reel, reel, where)) {
    rep.info(where, 'cross-reference checks run on a best-effort basis after schema errors');
  }
  if (reel.id !== reelId) rep.err(where, `reel.json id '${reel.id}' must equal its folder name '${reelId}'`);

  let duration: number | null = isNum(reel.duration) && reel.duration > 0 ? reel.duration : null;
  if (duration === null) {
    rep.err(where, 'duration missing or invalid; remaining timing checks skipped');
  } else if (duration < RECOMMENDED_DURATION[0] || duration > RECOMMENDED_DURATION[1]) {
    rep.warn(where, `duration ${fmt(duration)}s is outside the recommended 60-90 s range`);
  }
  const inTime = (t: unknown, what: string) => {
    if (duration === null || !isNum(t)) return;
    if (t < 0 || t > duration + 0.01) rep.err(where, `${what}: time ${t} is outside 0..${duration}`);
  };

  // ---- audio
  const audio = safeJoin(reelDir, reel.audio, rep, where);
  if (audio !== null) {
    const bytes = files.get(audio);
    if (!bytes) {
      rep.err(where, `audio file not found: ${reel.audio}`);
    } else {
      if (!AUDIO_EXT.has(ext(audio))) rep.err(where, `audio format ${ext(audio)} not allowed (${[...AUDIO_EXT].sort().join(', ')})`);
      if (ext(audio) === '.wav') rep.warn(where, 'WAV audio is large; prefer Opus (.opus) ~48 kbps mono');
      if (bytes.length > MAX_AUDIO_BYTES) rep.warn(where, `audio is ${Math.floor(bytes.length / 1024)} KB; aim for < 1 MB (Opus 48 kbps mono)`);
    }
  }

  // ---- transcript
  let words: J[] = [];
  const trPath = safeJoin(reelDir, reel.transcript, rep, where);
  if (trPath !== null) {
    const transcript = loadJson(files, trPath, rep, where);
    if (transcript !== undefined && rep.schema(v.transcript, transcript, `${where} transcript`)) {
      words = transcript.words;
      let prev = -1;
      words.forEach((w, i) => {
        if (!isNum(w.s) || !isNum(w.e)) return;
        if (w.s >= w.e) rep.err(where, `transcript word #${i} '${w.w}': s >= e`);
        if (w.s < prev - 1e-6) rep.err(where, `transcript word #${i} '${w.w}' is out of order`);
        prev = w.s;
        if (duration !== null && w.e > duration + AUDIO_TOLERANCE) rep.err(where, `transcript word #${i} ends after the audio (${w.e}s)`);
      });
      const last = words.at(-1);
      if (duration !== null && last && isNum(last.e) && duration - last.e > 5) rep.warn(where, 'more than 5 s of silence after the last word');
      if (!words.some((w) => w.key)) rep.warn(where, 'no transcript word is marked key=true (used to highlight key terms in captions)');
    }
  }

  // ---- images
  const images: Record<string, J> = isObj(reel.images) ? reel.images : {};
  const svgIds = new Map<string, Set<string>>();
  for (const [key, img] of Object.entries(images)) {
    if (!isObj(img) || typeof img.src !== 'string') continue;
    const path = safeJoin(reelDir, img.src, rep, where);
    if (path === null) continue;
    const bytes = files.get(path);
    if (!bytes) {
      rep.err(where, `image '${key}': file not found: ${img.src}`);
      continue;
    }
    const e = ext(path);
    if (!IMAGE_EXT.has(e)) rep.err(where, `image '${key}': format ${e} not allowed (${[...IMAGE_EXT].sort().join(', ')})`);
    if (bytes.length > MAX_IMAGE_BYTES) rep.warn(where, `image '${key}' is ${Math.floor(bytes.length / 1024)} KB (limit 1.5 MB)`);
    if (e === '.svg') svgIds.set(key, checkSvg(files, path, rep, where));
    else if (e === '.png' || e === '.jpg' || e === '.jpeg') rep.info(where, `image '${key}': prefer SVG for diagrams or WebP for photos`);
    if (Math.max(isNum(img.width) ? img.width : 0, isNum(img.height) ? img.height : 0) > 4096) rep.warn(where, `image '${key}': dimensions above 4096 px`);
  }

  // ---- regions
  const regions: Record<string, J> = isObj(reel.regions) ? reel.regions : {};
  if ('full' in regions) rep.err(where, "region key 'full' is reserved for camera.target");
  for (const [key, reg] of Object.entries(regions)) {
    if (!isObj(reg)) continue;
    const imgKey = reg.image;
    if (!(imgKey in images)) {
      rep.err(where, `region '${key}': unknown image '${imgKey}'`);
      continue;
    }
    if ('svgId' in reg) {
      const ids = svgIds.get(imgKey);
      if (!ids) rep.err(where, `region '${key}': svgId used but image '${imgKey}' is not an SVG`);
      else if (!ids.has(reg.svgId)) rep.err(where, `region '${key}': id '${reg.svgId}' not found in ${images[imgKey]?.src}`);
    }
    if (isObj(reg.rect)) {
      const r = reg.rect;
      const n = (x: unknown) => (isNum(x) ? x : 0);
      if (n(r.x) + n(r.w) > 1.0001 || n(r.y) + n(r.h) > 1.0001) rep.err(where, `region '${key}': rect goes outside the image (x+w or y+h > 1)`);
    }
  }
  const quizRegions = Object.entries(regions).filter(([, r]) => isObj(r) && r.quiz !== false).map(([k]) => k);
  if (quizRegions.length < 2) rep.warn(where, 'fewer than 2 quiz regions: auto formats identify/locate need at least 2 (ideally 3+) labelled regions');

  // ---- segments
  const segments: J[] = Array.isArray(reel.segments) ? reel.segments.filter(isObj) : [];
  const segIds = new Set<string>();
  let lastEnd = -1;
  for (const s of segments) {
    if (segIds.has(s.id)) rep.err(where, `duplicate segment id '${s.id}'`);
    segIds.add(s.id);
    if (!isNum(s.start) || !isNum(s.end)) continue;
    if (s.start >= s.end) rep.err(where, `segment '${s.id}': start >= end`);
    if (s.start < lastEnd - 0.01) rep.err(where, `segment '${s.id}' overlaps the previous one or is out of order`);
    lastEnd = s.end;
    inTime(s.start, `segment '${s.id}'.start`);
    inTime(s.end, `segment '${s.id}'.end`);
  }
  if (segments.length && !segments.some((s) => s.importance === 'key')) rep.err(where, "no segment has importance 'key'");

  // ---- cues
  const cues: J[] = Array.isArray(reel.cues) ? reel.cues.filter(isObj) : [];
  const shows = cues.filter((c) => c.type === 'show' && isNum(c.t)).sort((a, b) => a.t - b.t);
  if (!shows.length || shows[0].t > 0.05) rep.err(where, "the first cue must be a 'show' at t=0 (otherwise the screen is empty)");
  const imageAt = (t: number): string | undefined => {
    let cur: string | undefined;
    for (const c of shows) if (c.t <= t + 1e-6) cur = c.image;
    return cur;
  };
  const checkRegionRef = (rk: unknown, desc: string, t: number, allowFull = false) => {
    if (rk === undefined || rk === null || (allowFull && rk === 'full')) return;
    if (typeof rk !== 'string' || !(rk in regions)) {
      rep.err(where, `${desc}: unknown region '${rk}'`);
      return;
    }
    const shown = imageAt(t);
    if (shown !== undefined && regions[rk].image !== shown) {
      rep.warn(where, `${desc}: region '${rk}' belongs to image '${regions[rk].image}' but '${shown}' is on screen`);
    }
  };
  let prevT = -1;
  cues.forEach((c, i) => {
    const t = c.t;
    const desc = `cue #${i} (${c.type} @ ${t})`;
    if (!isNum(t)) return;
    if (t < prevT - 1e-6) rep.warn(where, `${desc}: cues are not sorted by time`);
    prevT = t;
    inTime(t, desc);
    if (isNum(c.until)) {
      if (c.until <= t) rep.err(where, `${desc}: until <= t`);
      inTime(c.until, `${desc}.until`);
    }
    if (c.type === 'show' && !(c.image in images)) rep.err(where, `${desc}: unknown image '${c.image}'`);
    else if (c.type === 'camera') checkRegionRef(c.target, desc, t, true);
    else if (c.type === 'spotlight') for (const rk of Array.isArray(c.target) ? c.target : [c.target]) checkRegionRef(rk, desc, t);
    else if (c.type === 'label' || c.type === 'pulse') checkRegionRef(c.region, desc, t);
    else if (c.type === 'arrow') {
      checkRegionRef(c.from, desc, t);
      checkRegionRef(c.to, desc, t);
    }
  });

  // ---- questions
  const questions: J[] = Array.isArray(reel.questions) ? reel.questions.filter(isObj) : [];
  const qById = new Map<string, J>();
  for (const q of questions) {
    const qdesc = `question '${q.id}' (${q.type})`;
    if (qById.has(q.id)) rep.err(where, `duplicate question id '${q.id}'`);
    qById.set(q.id, q);
    for (const sid of Array.isArray(q.explain) ? q.explain : [q.explain]) {
      if (!segIds.has(sid)) rep.err(where, `${qdesc}: explain refers to unknown segment '${sid}'`);
    }
    if (Array.isArray(q.options) && isInt(q.answer) && (q.answer < 0 || q.answer >= q.options.length)) {
      rep.err(where, `${qdesc}: answer index ${q.answer} out of range (0..${q.options.length - 1})`);
    }
    if (q.type === 'cloze') {
      const { from, cut, resume } = q;
      if (isNum(from) && isNum(cut) && isNum(resume)) {
        if (!(from <= cut && cut < resume)) rep.err(where, `${qdesc}: need from <= cut < resume`);
        inTime(from, `${qdesc}.from`);
        inTime(cut, `${qdesc}.cut`);
        inTime(resume, `${qdesc}.resume`);
        if (words.length && !words.some((w) => isNum(w.s) && Math.abs(w.s - cut) <= 0.15)) {
          rep.warn(where, `${qdesc}: 'cut' (${cut}) does not match the start of any transcript word (+-0.15 s)`);
        }
      }
    } else if (q.type === 'compare') {
      if (!(q.image in images)) rep.err(where, `${qdesc}: unknown image '${q.image}'`);
      if (q.otherReel === reelId) rep.err(where, `${qdesc}: otherReel must be a different reel`);
      else if (packReels.has(q.otherReel)) {
        const otherImgs = packReels.get(q.otherReel)?.images ?? {};
        if (!isObj(otherImgs) || !(q.otherImage in otherImgs)) rep.err(where, `${qdesc}: image '${q.otherImage}' not found in reel '${q.otherReel}'`);
      } else {
        rep.info(where, `${qdesc}: reel '${q.otherReel}' is not in this pack; it must already exist in the app library`);
      }
    } else if (q.type === 'teachback') {
      const groups = Array.isArray(q.keywords) ? q.keywords.length : 0;
      if (isInt(q.minHits) && q.minHits > groups) rep.err(where, `${qdesc}: minHits > number of keyword groups`);
    }
  }

  const pre = reel.pretest;
  if (pre !== undefined) {
    if (!qById.has(pre)) rep.err(where, `pretest refers to unknown question '${pre}'`);
    else if (!['mcq', 'truefalse'].includes(qById.get(pre).type)) rep.err(where, 'pretest must be an mcq or truefalse question');
  }
  if (!questions.some((q) => q.type === 'mcq' && q.id !== pre)) rep.err(where, 'need at least one mcq that is not the pretest (asked after the video)');
  if (questions.filter((q) => q.type === 'truefalse').length < 2) rep.warn(where, 'recommended: at least 2 truefalse statements');
  if (questions.length + quizRegions.length < 6) rep.warn(where, 'few probes in total (questions + quiz regions < 6); reviews will repeat the same probes often');

  if (isObj(reel.recap) && Array.isArray(reel.recap.segments)) {
    for (const sid of reel.recap.segments) if (!segIds.has(sid)) rep.err(where, `recap refers to unknown segment '${sid}'`);
  }
  for (const rel of Array.isArray(reel.related) ? reel.related : []) {
    if (isObj(rel) && !packReels.has(rel.reel)) rep.info(where, `related reel '${rel.reel}' is not in this pack`);
  }
}

/** Validates an extracted pack (paths relative to the pack root). */
export function validatePack(files: PackFiles): ValidationReport {
  const rep = new Reporter();
  const reels = new Map<string, J>();
  const done = (pack?: J): ValidationReport => ({
    errors: rep.errors,
    warnings: rep.warnings,
    infos: rep.infos,
    ok: rep.errors.length === 0,
    pack,
    reels,
  });

  const pack = loadJson(files, 'pack.json', rep, 'pack');
  if (pack === undefined) return done();
  rep.schema(getValidators().pack, pack, 'pack');
  const reelIds: string[] = Array.isArray(pack.reels) ? pack.reels.filter((r: unknown) => typeof r === 'string') : [];

  const onDisk = new Set<string>();
  for (const path of files.keys()) {
    const m = /^reels\/([^/]+)\//.exec(path);
    if (m) onDisk.add(m[1]!);
  }
  if (onDisk.size === 0) {
    rep.err('pack', 'missing folder: reels/');
    return done(pack);
  }
  for (const extra of [...onDisk].filter((d) => !reelIds.includes(d)).sort()) {
    rep.warn('pack', `folder reels/${extra} is not listed in pack.json reels`);
  }

  for (const rid of reelIds) {
    if (!onDisk.has(rid)) {
      rep.err('pack', `listed reel '${rid}' has no folder reels/${rid}`);
      continue;
    }
    reels.set(rid, loadJson(files, `reels/${rid}/reel.json`, rep, `reel ${rid}`));
  }
  for (const [rid, data] of reels) {
    if (isObj(data)) validateReel(files, `reels/${rid}`, rid, reels, rep);
  }

  let total = 0;
  for (const b of files.values()) total += b.length;
  if (total > 50 * 1024 * 1024) rep.warn('pack', `pack is ${Math.floor(total / (1024 * 1024))} MB; split packs above 50 MB`);
  rep.info('pack', `${reelIds.length} reel(s), ${(total / 1024).toFixed(0)} KB total`);
  return done(pack);
}
