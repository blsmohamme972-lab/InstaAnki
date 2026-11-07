/* Collection identity checks against the actual Fresh UI. All lessons below
 * are synthetic in-memory metadata. No old ZIP, audio, images or source text
 * are needed. Build first with npm run build:web:fresh. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..');
const web = path.join(root, 'build/fresh-web');
const books = JSON.parse(fs.readFileSync(path.join(web, 'data/books.json'), 'utf8'));
const book = books[0];
assert.ok(book && Number.isInteger(book.totalQuestions) && book.totalQuestions >= 4);
assert.equal(fs.readFileSync(path.join(web, 'app.js'), 'utf8'), fs.readFileSync(path.join(root, 'web/app.js'), 'utf8'), 'Rebuild the Fresh bundle before running import identity checks.');
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.css': 'text/css' };
const server = http.createServer((request, response) => {
  const relative = new URL(request.url, 'http://local').pathname.replace(/^\//, '') || 'index.html';
  const file = path.resolve(web, relative);
  if (!file.startsWith(web + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { response.writeHead(404); response.end(); return; }
  response.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
  response.end(fs.readFileSync(file));
});
const errors = [], passed = [];
let browser, origin;
const fixture = (version = 2, questionNumber = 1) => ({
  id: 'synthetic-import-identity', version, title: `Synthetic question ${questionNumber}, revision ${version}`,
  source: { bookId: book.id, questionNumber }, audioUrl: 'media/synthetic.mp3', poster: 'media/synthetic.png',
  scenes: [{ start: 0, end: 1, image: 'media/synthetic.png', caption: 'Synthetic import fixture; no medical content' }],
  quiz: { prompt: 'Synthetic fixture', options: ['A', 'B'], correctIndex: 0, explanation: 'No medical teaching content.' },
});
const pack = (id, lesson) => ({ packId: id, baseUrl: `${origin}/${id}/`, manifest: { lessons: Array.isArray(lesson) ? lesson : [lesson], books: [] } });
async function check(label, run) { await run(); passed.push(label); console.log('PASS ' + label); }
async function session(packs, savedState = null) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await context.route('https://**/*', route => route.abort());
  await context.addInitScript(({ packs, savedState }) => {
    localStorage.setItem('instaanki.state.v1', savedState || JSON.stringify({ schemaVersion: 1, lessons: {}, reviews: [], settings: { autoPlay: false, autoCheckUpdates: false, reduceMotion: true, newPerDay: 10 } }));
    window.testPacks = packs;
    window.AndroidNative = {
      listPacks: () => JSON.stringify(testPacks),
      getAppInfo: () => JSON.stringify({ packageName: 'com.instaanki.fresh', version: '0.3.1', versionCode: 5 }),
      getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value), removeItem: key => localStorage.removeItem(key),
    };
  }, { packs, savedState });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin);
  await page.waitForFunction(() => document.querySelector('#lesson-title').textContent || document.querySelector('.collection-count'));
  return { context, page };
}
async function reloadPacks(page, packs) {
  await page.evaluate(packs => new Promise(resolve => {
    window.testPacks = packs;
    window.addEventListener('instaanki:collection-reloaded', resolve, { once: true });
    window.dispatchEvent(new CustomEvent('instaanki:pack-imported'));
  }), packs);
}
const state = page => page.evaluate(() => localStorage.getItem(Learning.storageKey));

async function main() {
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(web, 'data/lessons.json'), 'utf8')), []);
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const original = fixture();
  let savedState;

  await check('A higher-version different source cannot inherit an active lesson ID or learning history', async () => {
    const { context, page } = await session([pack('original', original)]);
    try {
      await page.evaluate(({ id, source }) => {
        Learning.note(id, 'This history belongs to source question one.');
        Learning.grade(id, true, 'synthetic-recall', 'review');
        Learning.reportFeedback(id, { reason: 'bad_images', comment: 'Synthetic report.', lessonVersion: 2, source, assetHashes: {} });
      }, original);
      savedState = await state(page);
      await reloadPacks(page, [pack('original', original), pack('replacement', fixture(3, 2))]);
      assert.equal(await page.locator('#lesson-title').textContent(), original.title);
      assert.match(await page.locator('#toast').textContent(), /reuses a lesson ID for a different source question/);
      assert.equal(await state(page), savedState);
      await page.locator('[data-tab="settings"]').click();
      assert.match(await page.locator('.collection-warning').textContent(), /different source question/);
      assert.match(await page.locator('.app-version').textContent(), /0\.3\.1/, 'Installed identity must override the base distribution marker');
    } finally { await context.close(); }
  });

  await check('Cold-start source collisions are hidden in both directory orders instead of choosing one arbitrarily', async () => {
    const candidates = [pack('first', original), pack('second', fixture(3, 2))];
    for (const packs of [candidates, [...candidates].reverse()]) {
      const { context, page } = await session(packs, savedState);
      try {
        assert.equal(await page.locator('#lesson-card').isVisible(), false);
        assert.match(await page.locator('.collection-count').textContent(), /0 lessons/);
        assert.match(await page.locator('#toast').textContent(), /different source question/);
        assert.equal(await state(page), savedState);
      } finally { await context.close(); }
    }
  });

  await check('A legitimate same-source revision is selected without changing cards, reports or notes', async () => {
    const corrected = fixture(3);
    for (const packs of [[pack('older', original), pack('newer', corrected)], [pack('newer', corrected), pack('older', original)]]) {
      const { context, page } = await session(packs, savedState);
      try {
        assert.equal(await page.locator('#lesson-title').textContent(), corrected.title);
        assert.equal(await state(page), savedState);
        assert.equal(await page.evaluate(() => Learning.getFeedback()[0].lessonVersion), 2);
      } finally { await context.close(); }
    }
  });

  await check('Every cold-start collision is hidden when the same two packs conflict on multiple IDs', async () => {
    const candidates = [
      pack('first', [{ ...fixture(2, 1), id: 'collision-one' }, { ...fixture(2, 2), id: 'collision-two' }]),
      pack('second', [{ ...fixture(3, 3), id: 'collision-one' }, { ...fixture(3, 4), id: 'collision-two' }]),
    ];
    for (const packs of [candidates, [...candidates].reverse()]) {
      const { context, page } = await session(packs, savedState);
      try {
        assert.equal(await page.locator('#lesson-card').isVisible(), false);
        assert.match(await page.locator('.collection-count').textContent(), /0 lessons/);
        assert.match(await page.locator('#toast').textContent(), /different source question/);
        assert.equal(await state(page), savedState);
      } finally { await context.close(); }
    }
  });

  await check('Duplicate IDs, reserved IDs and invalid question references are rejected without disturbing other packs', async () => {
    const { context, page } = await session([pack('original', original)], savedState);
    try {
      const invalid = [
        [fixture(3), fixture(4)],
        { ...fixture(3), id: 'constructor' },
        { ...fixture(3), source: { bookId: book.id, questionNumber: '1' } },
        fixture(3, book.totalQuestions + 1),
      ];
      for (const candidate of invalid) {
        await reloadPacks(page, [pack('original', original), pack('invalid', candidate)]);
        assert.equal(await page.locator('#lesson-title').textContent(), original.title);
        assert.equal(await state(page), savedState);
      }
    } finally { await context.close(); }
  });

  assert.deepEqual(errors, []);
  console.log(`All ${passed.length} synthetic collection identity checks passed; no medical media or physical Android playback tested.`);
}
main().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  await browser?.close(); server.close();
});
