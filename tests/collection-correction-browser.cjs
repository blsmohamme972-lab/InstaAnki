/* Verify collection replacement and retained learning records in the real UI.
 * First run android/tests/CollectionCorrectionTest.java against both archives.
 * This suite consumes its native importer snapshots; the Android storage bridge
 * is represented by persistent browser storage, not an Android SQLite database.
 */
'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { loadRajaStarterFixture } = require('./helpers/raja-starter-fixture.cjs');

const root = path.resolve(__dirname, '..');
const web = path.join(root, 'web');
function option(name, fallback) {
  const index = process.argv.indexOf(name);
  if (index < 0) return fallback;
  assert.ok(process.argv[index + 1] && !process.argv[index + 1].startsWith('--'), `Missing value for ${name}`);
  return process.argv[index + 1];
}
const output = path.resolve(option('--output', path.join(root, 'test-results/collection-correction')));
const nativeResults = path.resolve(option('--native-results', path.join(output, 'native')));
const appRef = option('--app-ref', '');
const appBytes = appRef ? execFileSync('git', ['show', `${appRef}:web/app.js`], { cwd: root }) : fs.readFileSync(path.join(web, 'app.js'));
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const readJSON = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const nativeReview = readJSON(path.join(nativeResults, 'native-review.json'));
const fixture = loadRajaStarterFixture(web);
const packPhases = { base: [] };
const lessonPhases = {};
for (const phase of ['original', 'corrected', 'restored']) {
  packPhases[phase] = readJSON(path.join(nativeResults, `${phase}-packs.json`));
  lessonPhases[phase] = readJSON(path.join(nativeResults, `${phase}-lessons.json`));
}
assert.equal(lessonPhases.original.length, 20);
assert.equal(lessonPhases.corrected.length, 0);
const target = 'instaanki-medical-foundations-2026-v1';
const rajaId = 'shahzad-raja-2015-200-practice-questions';
const extraId = 'openref2026-q001';
const rajaLessonId = 'shahzad2015-q005';
const mime = { '.html': 'text/html', '.js': 'application/javascript', '.json': 'application/json', '.css': 'text/css', '.jpg': 'image/jpeg', '.png': 'image/png', '.mp3': 'audio/mpeg' };
const origin = 'https://appassets.androidplatform.net';
const csp = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; media-src 'self' blob:; connect-src 'self' https:; font-src 'self' data:; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'";
const results = [];
const phases = [];
const errors = [];
let phase = 'base';
let browser;

async function until(page, predicate, value, timeout = 10000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await page.evaluate(predicate, value)) return;
    await page.waitForTimeout(30);
  }
  throw new Error('Browser condition timed out: ' + predicate.toString());
}
async function counts(page, label) {
  await page.locator('.nav-item[data-tab="publications"]').click();
  const books = await page.locator('.publication-card').evaluateAll(nodes => nodes.map(node => ({ id: node.dataset.book, produced: node.querySelector('.book-progress-head b').textContent })));
  await page.locator('.nav-item[data-tab="review"]').click();
  const lessonIds = await page.locator('[data-practice-lesson]').evaluateAll(nodes => nodes.map(node => node.dataset.practiceLesson));
  const result = { phase: label, lessonCount: lessonIds.length, bookCount: books.length, lessonIds, books };
  phases.push(result);
  return result;
}
async function stored(page) {
  return page.evaluate(() => ({ raw: AndroidNative.getItem(Learning.storageKey), state: JSON.parse(JSON.stringify(Learning.state)) }));
}
async function importPhase(page, next) {
  phase = next;
  await page.evaluate(next => {
    localStorage.setItem('correction-fixture.phase', next);
    window.dispatchEvent(new CustomEvent('instaanki:pack-imported', { detail: { packId: 'instaanki-medical-foundations-2026-v1' } }));
  }, next);
  await until(page, () => document.querySelector('#toast').textContent === 'Your new lessons are ready. Learning history was preserved.');
}
async function restart(page) {
  await page.reload();
  await page.waitForSelector('#lesson-card:not([hidden])');
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 1 });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    const pathname = decodeURIComponent(url.pathname);
    if (pathname === '/assets/app.js') return route.fulfill({ body: appBytes, contentType: 'application/javascript' });
    if (pathname === '/assets/data/lessons.json') return route.fulfill({ json: fixture.lessons });
    if (pathname === '/assets/data/books.json') return route.fulfill({ json: fixture.books });
    if (pathname === `/content/${target}/lessons.json`) return route.fulfill({ json: lessonPhases[phase] || [] });
    const prefix = pathname.startsWith('/assets/') ? '/assets/' : pathname.startsWith('/content/') ? '/content/' : null;
    if (!prefix) return route.fulfill({ status: 404 });
    const base = prefix === '/assets/' ? web : nativeReview.restoredPackRoot;
    const file = path.resolve(base, pathname.slice(prefix.length));
    if (!file.startsWith(base + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return route.fulfill({ status: 404 });
    return route.fulfill({ path: file, contentType: mime[path.extname(file)] || 'application/octet-stream', headers: { 'Content-Security-Policy': csp } });
  });
  await context.addInitScript(packs => {
    const storagePrefix = 'native-fixture:';
    const key = storagePrefix + 'instaanki.state.v1';
    if (!localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify({
      schemaVersion: 1, lessons: {}, reviews: [],
      settings: { autoPlay: false, autoCheckUpdates: false, reduceMotion: true, speed: 1, newPerDay: 100, dailyTopicIds: [] },
    }));
    window.AndroidNative = {
      getItem: key => localStorage.getItem(storagePrefix + key),
      setItem: (key, value) => localStorage.setItem(storagePrefix + key, value),
      removeItem: key => localStorage.removeItem(storagePrefix + key),
      listPacks: () => JSON.stringify(packs[localStorage.getItem('correction-fixture.phase') || 'base']),
      getAppInfo: () => JSON.stringify({ version: '0.1.1', versionCode: 2 }),
    };
  }, packPhases);
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin + '/assets/index.html');
  await page.waitForSelector('#lesson-card:not([hidden])');
  let count = await counts(page, 'bundled-only');
  assert.equal(count.lessonCount, 3); assert.deepEqual(count.books, [{ id: rajaId, produced: '3 / 200' }]);
  results.push('Bundled 0.1.1 fixture starts with exactly 3 original lessons and 1 Raja publication');

  await importPhase(page, 'original');
  await until(page, () => document.querySelectorAll('[data-practice-lesson]').length === 23);
  count = await counts(page, 'original-20-imported');
  assert.equal(count.lessonCount, 23); assert.equal(count.bookCount, 2);
  results.push('Actual imported archive metadata adds the 20 reference lessons and second publication');

  await page.evaluate(({ rajaLessonId, extraId }) => {
    const now = new Date(Date.now() + 3600000);
    Learning.expose(rajaLessonId, 9, now);
    Learning.grade(rajaLessonId, true, 'correction-raja-review', 'review', now);
    Learning.note(rajaLessonId, 'Original Raja note: keep this exact text.');
    Learning.expose(extraId, 9, now);
    Learning.grade(extraId, false, 'correction-extra-review', 'review', now);
    Learning.note(extraId, 'Reference note: available again after reimport.');
    Learning.like(extraId);
    Learning.setSetting('retention', 0.95);
    Learning.setSetting('speed', 1.25);
  }, { rajaLessonId, extraId });
  const before = await stored(page);
  assert.equal(before.state.reviews.length, 2);
  assert.equal(before.state.lessons[rajaLessonId].card.reps, 1);
  assert.equal(before.state.lessons[extraId].card.reps, 1);
  results.push('Real Learning engine creates FSRS cards, two review logs, private notes, a saved lesson and preferences');

  await importPhase(page, 'corrected');
  count = await counts(page, 'correction-imported-before-restart');
  assert.equal(count.lessonCount, 23); assert.equal(count.bookCount, 2);
  assert.equal((await stored(page)).raw, before.raw);
  results.push('Existing 0.1.1 keeps its in-memory list until cold restart; import alone does not change learning bytes');

  await restart(page);
  count = await counts(page, 'correction-after-cold-restart');
  assert.equal(count.lessonCount, 3); assert.deepEqual(count.books, [{ id: rajaId, produced: '3 / 200' }]);
  assert.deepEqual(new Set(count.lessonIds), new Set(fixture.lessons.map(lesson => lesson.id)));
  const after = await stored(page);
  assert.equal(after.raw, before.raw);
  assert.deepEqual(after.state, before.state);
  assert.equal(after.state.lessons[extraId].note, 'Reference note: available again after reimport.');
  assert.equal(after.state.reviews.length, 2);
  results.push('Cold restart shows only the original 3 Raja lessons and 1 publication, with all stored learning bytes unchanged');
  const backup = await page.evaluate(() => JSON.parse(Learning.backup().state[Learning.storageKey]));
  assert.deepEqual(backup, before.state);
  results.push('Learning backup still includes inactive lesson records, reviews, FSRS schedules, notes and preferences');

  await importPhase(page, 'restored');
  await until(page, () => document.querySelectorAll('[data-practice-lesson]').length === 23);
  await restart(page);
  count = await counts(page, 'original-pack-reimported');
  assert.equal(count.lessonCount, 23); assert.equal(count.bookCount, 2);
  assert.equal((await stored(page)).raw, before.raw);
  await page.locator('.nav-item[data-tab="feed"]').click();
  await page.locator('[data-feed="saved"]').click();
  assert.equal(await page.locator('#lesson-title').textContent(), lessonPhases.original.find(lesson => lesson.id === extraId).title);
  await page.locator('[data-action="note"]').click();
  assert.equal(await page.locator('#note-input').inputValue(), 'Reference note: available again after reimport.');
  await page.screenshot({ path: path.join(output, 'restored-note.png') });
  await page.locator('[data-action="close-modal"]').click();
  assert.equal((await stored(page)).raw, before.raw);
  results.push('Reimport restores 23 lessons/2 publications; the saved reference lesson and its unchanged note are accessible through the UI');

  await importPhase(page, 'corrected');
  await restart(page);
  count = await counts(page, 'correction-reapplied-after-cold-restart');
  assert.equal(count.lessonCount, 3); assert.equal(count.bookCount, 1);
  assert.equal((await stored(page)).raw, before.raw);
  await page.locator('.nav-item[data-tab="publications"]').click();
  await page.screenshot({ path: path.join(output, 'raja-only-publications.png') });
  results.push('Reapplying the correction is reversible and repeatable with no learning-state changes');
  assert.deepEqual(errors, []);
  const report = {
    schemaVersion: 1, reviewedAt: new Date().toISOString(), passed: true,
    scope: 'Real app UI and Learning bundle in Playwright Chromium; native importer-produced descriptors and payloads; persistent bridge fixture',
    physicalAndroidTested: false, sqliteTested: false, requiresAppRestart: true,
    appSourceRef: appRef || 'working-tree', appSourceSha256: sha(appBytes),
    learningBundleSha256: sha(fs.readFileSync(path.join(web, 'learning.js'))),
    baseline: fixture.label, learningStateSha256Before: sha(before.raw), learningStateSha256After: sha((await stored(page)).raw),
    preservedRecordIds: Object.keys(before.state.lessons), preservedReviewCount: before.state.reviews.length,
    checks: results, phases, pageErrors: errors,
  };
  fs.writeFileSync(path.join(output, 'browser-review.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(`PASS ${results.length} collection/learning lifecycle checks; report: ${path.join(output, 'browser-review.json')}`);
})().catch(error => {
  fs.mkdirSync(output, { recursive: true });
  fs.writeFileSync(path.join(output, 'browser-failure.json'), JSON.stringify({ error: error.stack, completedChecks: results, phases, pageErrors: errors }, null, 2) + '\n');
  console.error(error.stack); process.exitCode = 1;
}).finally(async () => { await browser?.close(); });
