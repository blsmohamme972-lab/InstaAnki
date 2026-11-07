/* Actual Chromium/media regression for the immersive player and atomic imports.
 * Uses only the three existing Raja lessons; temporary import fixtures are never
 * written into the production collection. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { loadRajaStarterFixture, routeRajaStarterFixture } = require('./helpers/raja-starter-fixture.cjs');
const web = path.resolve(__dirname, '../web');
const output = path.resolve(__dirname, '../test-results/reels');
const fixture = loadRajaStarterFixture(web);
const mime = { '.html': 'text/html', '.js': 'application/javascript', '.json': 'application/json', '.css': 'text/css', '.mp3': 'audio/mpeg', '.png': 'image/png', '.webp': 'image/webp', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg' };
const csp = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; media-src 'self' blob:; connect-src 'self' https:; object-src 'none'; base-uri 'none'";
const server = http.createServer((request, response) => {
  const relative = decodeURIComponent(new URL(request.url, 'http://local').pathname).replace(/^\//, '') || 'index.html';
  const file = path.resolve(web, relative);
  if (!file.startsWith(web + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { response.writeHead(404); response.end(); return; }
  const bytes = fs.readFileSync(file);
  response.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
  response.setHeader('Accept-Ranges', 'bytes'); response.setHeader('Content-Security-Policy', csp);
  const range = /bytes=(\d+)-(\d*)/.exec(request.headers.range || '');
  if (range) {
    const start = Number(range[1]), end = Math.min(bytes.length - 1, range[2] ? Number(range[2]) : bytes.length - 1);
    response.writeHead(206, { 'Content-Range': `bytes ${start}-${end}/${bytes.length}`, 'Content-Length': end - start + 1 }); response.end(bytes.subarray(start, end + 1)); return;
  }
  response.setHeader('Content-Length', bytes.length); response.end(bytes);
});
let browser, origin;
const passed = [], errors = [];
const endOf = lesson => lesson.presentation.effectiveEndSeconds;
async function check(label, callback) { await callback(); passed.push(label); console.log(`PASS ${label}`); }
async function until(page, predicate, arg) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) { if (await page.evaluate(predicate, arg)) return; await page.waitForTimeout(40); }
  throw new Error('Browser condition timed out: ' + predicate.toString());
}
async function fresh(size = { width: 390, height: 844 }, packs = null, content = fixture) {
  const context = await browser.newContext({ viewport: size, hasTouch: size.width < 700, isMobile: size.width < 700, deviceScaleFactor: 1 });
  await context.route('https://**/*', route => route.abort());
  await routeRajaStarterFixture(context, content);
  await context.addInitScript(packs => {
    localStorage.setItem('instaanki.state.v1', JSON.stringify({ schemaVersion: 1, lessons: {}, reviews: [], settings: { autoPlay: false, autoCheckUpdates: false, reduceMotion: true, newPerDay: 50 } }));
    if (packs) {
      window.testPacks = packs; window.testImmersive = [];
      window.AndroidNative = { getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value), removeItem: key => localStorage.removeItem(key), listPacks: () => JSON.stringify(window.testPacks), getAppInfo: () => JSON.stringify({ version: 'test', versionCode: 3 }), setImmersive: value => window.testImmersive.push(value) };
    }
    window.testFrames = { scheduled: 0, fired: 0 };
    const raf = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = callback => { window.testFrames.scheduled++; return raf(time => { window.testFrames.fired++; callback(time); }); };
  }, packs);
  const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin);
  await page.waitForSelector('#lesson-card:not([hidden])');
  await until(page, () => document.querySelector('audio').readyState >= 1 && document.querySelector('#lesson-image').naturalWidth > 0);
  return { context, page };
}
async function seek(page, seconds) {
  await page.locator('audio').evaluate((audio, seconds) => { audio.pause(); audio.currentTime = seconds; }, seconds);
  await until(page, seconds => { const a = document.querySelector('audio'); return !a.seeking && Math.abs(a.currentTime - seconds) < .035; }, seconds);
  await page.waitForTimeout(60);
}
async function finish(page, lesson) {
  await seek(page, endOf(lesson) - .18);
  await page.locator('#play-button').click();
  await page.waitForSelector('#modal-backdrop:not([hidden]) .quiz-prompt', { timeout: 3000 });
  const at = await page.locator('audio').evaluate(audio => ({ time: audio.currentTime, paused: audio.paused }));
  assert.equal(at.paused, true); assert.ok(at.time <= endOf(lesson) + .12, `Playback ran beyond narrated end: ${at.time}`);
}
async function answer(page, index) {
  await page.locator(`[data-answer="${index}"]`).click();
  await page.locator('[data-action="submit-answer"]').click();
  await page.waitForSelector('.quiz-result');
}
async function screenshot(page, name) { await page.screenshot({ path: path.join(output, name + '.png') }); }
async function swipe(page, direction) {
  const client = await page.context().newCDPSession(page);
  const y = direction === 'up' ? 435 : 225, end = direction === 'up' ? 225 : 435;
  await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: 165, y }] });
  await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 165, y: (y + end) / 2 }] });
  await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 165, y: end }] });
  await client.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await client.detach();
}
async function reloadPacks(page, packs) {
  await page.evaluate(packs => new Promise(resolve => {
    window.testPacks = packs;
    window.addEventListener('instaanki:collection-reloaded', () => resolve(), { once: true });
    window.dispatchEvent(new CustomEvent('instaanki:pack-imported'));
  }), packs);
}
async function visibleCounts(page) {
  await page.locator('[data-tab="publications"]').click();
  const books = await page.locator('[data-book]').count();
  await page.locator('[data-tab="review"]').click();
  const lessons = await page.locator('[data-practice-lesson]').count();
  return { books, lessons };
}
async function main() {
  fs.mkdirSync(output, { recursive: true });
  for (const lesson of fixture.lessons) {
    assert.equal(lesson.presentation?.schemaVersion, 1, 'The reviewed existing-lesson presentation update must be integrated before this suite runs.');
    assert.equal(lesson.presentation.clinicalGallery.images.length, 3);
  }
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  for (const size of [{ width: 390, height: 844 }, { width: 320, height: 568 }, { width: 1280, height: 900 }]) {
    await check(`Full media surface, contained images and usable MCQ at ${size.width}×${size.height}`, async () => {
      const { context, page } = await fresh(size);
      try {
        await seek(page, 12);
        const layout = await page.evaluate(() => {
          const stage = document.querySelector('#visual-stage').getBoundingClientRect(), main = document.querySelector('main').getBoundingClientRect();
          return { stageHeight: stage.height, mainHeight: main.height, overflow: document.documentElement.scrollWidth > innerWidth, header: getComputedStyle(document.querySelector('.app-header')).display, fit: getComputedStyle(document.querySelector('#lesson-image')).objectFit };
        });
        assert.equal(layout.header, 'none'); assert.equal(layout.overflow, false); assert.equal(layout.fit, 'contain'); assert.ok(Math.abs(layout.stageHeight - layout.mainHeight) < 1);
        await screenshot(page, `feed-${size.width}`);
        await page.locator('#lesson-question-button').click();
        const first = page.locator('[data-answer="0"]'); await first.click();
        const submit = page.locator('[data-action="submit-answer"]');
        const rect = await submit.boundingBox(); assert.ok(rect.y >= 0 && rect.y + rect.height <= size.height, 'Question action is below screen'); assert.ok(rect.height >= 44);
        await screenshot(page, `question-${size.width}`);
        await submit.click(); await page.waitForSelector('.quiz-result');
        const next = await page.locator('[data-action="quiz-continue"]').boundingBox(); assert.ok(next.y + next.height <= size.height, 'Result continuation is below screen');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await screenshot(page, `result-${size.width}`);
      } finally { await context.close(); }
    });
  }
  await check('All three ending galleries fit, recap follows recorded cues, and narration ends without a silent hold', async () => {
    const { context, page } = await fresh();
    try {
      for (const lesson of fixture.lessons) {
        await until(page, () => document.querySelector('audio').readyState >= 1);
        const binding = lesson.presentation.recap.cueBindings[0];
        await seek(page, (binding.startSeconds + binding.endSeconds) / 2);
        await page.waitForSelector('#lesson-ending:not([hidden])');
        await until(page, () => [...document.querySelectorAll('.clinical-tile img')].every(image => image.complete && image.naturalWidth > 0));
        assert.equal(await page.locator('.clinical-tile').count(), 3);
        assert.equal(await page.locator('.recap-node.is-active').getAttribute('data-recap-node'), binding.nodeId);
        assert.equal(await page.locator('#teaching-pointer').isVisible(), false, 'An old image pointer leaked onto the gallery');
        assert.equal(await page.locator('.clinical-tile img').evaluateAll(images => images.every(image => getComputedStyle(image).objectFit === 'contain' && image.getBoundingClientRect().height > 15)), true);
        await screenshot(page, `${lesson.id}-ending-390`);
        await page.setViewportSize({ width: 320, height: 568 });
        await screenshot(page, `${lesson.id}-ending-320`);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.setViewportSize({ width: 390, height: 844 });
        await page.locator('.clinical-tile').first().click();
        assert.equal(await page.locator('.source-image').count(), 1); await page.locator('[data-action="close-modal"]').click();
        await page.locator('#speed-button').click(); await page.locator('[data-speed="1.5"]').click();
        await finish(page, lesson);
        await answer(page, lesson.quiz.correctIndex);
        const count = await page.evaluate(() => Learning.state.reviews.length);
        await page.locator('audio').evaluate(audio => { audio.dispatchEvent(new Event('ended')); audio.dispatchEvent(new Event('ended')); });
        assert.equal(await page.evaluate(() => Learning.state.reviews.length), count, 'Duplicate completion graded twice');
        if (lesson !== fixture.lessons.at(-1)) await page.locator('[data-action="quiz-continue"]').click();
      }
      assert.equal(await page.evaluate(() => Learning.state.reviews.length), 3);
    } finally { await context.close(); }
  });
  await check('Swipe changes lessons; seek and speed stay synchronized; background and paused player stop animation', async () => {
    const { context, page } = await fresh();
    try {
      await swipe(page, 'up'); assert.equal(await page.locator('#lesson-title').textContent(), fixture.lessons[1].title);
      await swipe(page, 'down'); assert.equal(await page.locator('#lesson-title').textContent(), fixture.lessons[0].title);
      await until(page, () => document.querySelector('audio').readyState >= 1);
      await page.locator('#seek').evaluate(input => { input.value = 50; input.dispatchEvent(new Event('input', { bubbles: true })); });
      await until(page, end => Math.abs(document.querySelector('audio').currentTime - end / 2) < .05, endOf(fixture.lessons[0]));
      await page.locator('#speed-button').click(); await page.locator('[data-speed="2"]').click();
      await page.locator('#play-button').click(); await page.waitForTimeout(200);
      assert.equal(await page.locator('audio').evaluate(audio => audio.playbackRate), 2);
      await page.evaluate(() => window.dispatchEvent(new Event('instaanki:background')));
      assert.equal(await page.locator('audio').evaluate(audio => audio.paused), true);
      await page.waitForTimeout(60); const before = await page.evaluate(() => testFrames.fired);
      await page.waitForTimeout(240); assert.equal(await page.evaluate(() => testFrames.fired), before, 'Paused player kept a permanent RAF loop');
      assert.equal(await page.locator('audio').count(), 1, 'Hidden audio players were added');
    } finally { await context.close(); }
  });
  await check('Valid four-, five- and six-image galleries remain visible and fully framed on a small screen', async () => {
    const choices = [...new Map(fixture.lessons.flatMap(lesson => lesson.presentation.clinicalGallery.images).map(image => [image.url, image])).values()];
    for (const count of [4, 5, 6]) {
      const content = structuredClone(fixture); content.lessons[0].presentation.clinicalGallery.images = choices.slice(0, count);
      const { context, page } = await fresh({ width: 320, height: 568 }, null, content);
      try {
        await seek(page, content.lessons[0].presentation.clinicalGallery.startSeconds + 1);
        await until(page, () => [...document.querySelectorAll('.clinical-tile img')].every(image => image.complete && image.naturalWidth));
        assert.equal(await page.locator('#lesson-ending').isVisible(), true); assert.equal(await page.locator('.clinical-tile').count(), count);
        const valid = await page.locator('.clinical-tile img').evaluateAll(images => images.every(image => { const rect = image.getBoundingClientRect(); return getComputedStyle(image).objectFit === 'contain' && rect.height > 12 && rect.width > 30 && rect.bottom < innerHeight; }));
        assert.equal(valid, true, `${count}-image gallery cropped or collapsed`);
      } finally { await context.close(); }
    }
  });
  await check('Report, dislike and hide preserve FSRS; report-only export and restore are usable', async () => {
    const { context, page } = await fresh();
    try {
      const lesson = fixture.lessons[0];
      await page.evaluate(id => { Learning.grade(id, true, 'feedback-seed', 'review'); Learning.note(id, 'Private note must stay private.'); }, lesson.id);
      const before = await page.evaluate(id => ({ card: Learning.get(id).card, reviews: Learning.state.reviews, note: Learning.get(id).note }), lesson.id);
      await page.locator('#report-button').click();
      await page.locator('input[name="feedback-reason"][value="bad_timing"]').check();
      await page.locator('#feedback-comment').fill('The scene change needs checking near the summary.');
      await page.locator('#feedback-hide').check(); await page.locator('#feedback-dislike').check();
      await screenshot(page, 'report-390'); await page.locator('[data-action="save-feedback"]').click();
      const after = await page.evaluate(id => ({ card: Learning.get(id).card, reviews: Learning.state.reviews, note: Learning.get(id).note }), lesson.id);
      assert.deepEqual(after, before);
      assert.equal(await page.evaluate(id => Learning.get(id).hidden && Learning.get(id).disliked, lesson.id), true);
      assert.notEqual(await page.locator('#lesson-title').textContent(), lesson.title);
      await page.locator('[data-tab="settings"]').click(); await page.locator('#screen-settings [data-action="feedback-history"]').click();
      const download = page.waitForEvent('download'); await page.locator('[data-action="export-feedback"]').click();
      const file = await download; const payload = JSON.parse(fs.readFileSync(await file.path(), 'utf8'));
      assert.equal(payload.format, 'instaanki-feedback-v1'); assert.equal(payload.reports.length, 1); assert.equal(payload.reports[0].reason, 'bad_timing');
      assert.ok(Object.keys(payload.reports[0].assetHashes).length >= 3, 'Report did not retain the available lesson image checksums');
      assert.equal(JSON.stringify(payload).includes('Private note must stay private'), false); assert.equal('reviews' in payload, false);
      await page.locator(`[data-unhide-lesson="${lesson.id}"]`).click();
      assert.equal(await page.evaluate(id => Learning.get(id).hidden, lesson.id), false);
      assert.deepEqual(await page.evaluate(id => Learning.get(id).card, lesson.id), before.card);
      await page.locator('[data-action="close-modal"]').click();
      await page.evaluate(ids => ids.forEach(id => Learning.setHidden(id, true)), fixture.lessons.map(item => item.id));
      await page.locator('[data-tab="feed"]').click(); await page.locator('[data-feed="all"]').click();
      assert.match(await page.locator('#feed-empty').textContent(), /Your lessons are hidden/);
      assert.doesNotMatch(await page.locator('#feed-empty').textContent(), /limit is reached/);
    } finally { await context.close(); }
  });
  await check('Paused collection briefs forbid new videos and cannot be unpaused by imported metadata', async () => {
    const content = structuredClone(fixture); content.books[0].productionPaused = true;
    const pack = { packId: 'pause-override-fixture', baseUrl: origin + '/', manifest: { lessons: [], books: [{ ...content.books[0], productionPaused: false }] } };
    const { context, page } = await fresh(undefined, [pack], content);
    try {
      await page.evaluate(() => Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async text => { window.copiedCollectionBrief = text; } } }));
      await page.locator('[data-tab="publications"]').click(); await page.locator('[data-book]').click();
      assert.match(await page.locator('#modal-body').textContent(), /New lesson production is paused/);
      assert.match(await page.locator('[data-copy-plan]').textContent(), /Copy collection brief/);
      await page.locator('[data-copy-plan]').click(); const text = await page.evaluate(() => copiedCollectionBrief);
      assert.match(text, /^Repair the InstaAnki app and its existing 3 lessons only\./);
      assert.match(text, /Do not create new videos.*explicit new user request/);
      assert.ok(text.includes(content.books[0].id));
      for (const lesson of content.lessons) assert.ok(text.includes(lesson.id));
      assert.doesNotMatch(text, /Next batch:|Continue the InstaAnki collection/);
      await page.evaluate(() => { navigator.clipboard.writeText = async () => { throw new Error('Clipboard unavailable'); }; });
      await page.locator('[data-copy-plan]').click();
      assert.equal(await page.locator('#modal-eyebrow').textContent(), 'APP REPAIRS ONLY');
      assert.equal(await page.locator('#modal-body textarea').inputValue(), text);
    } finally { await context.close(); }
    const future = structuredClone(fixture); future.books[0].productionPaused = false;
    const resumed = await fresh(undefined, null, future);
    try {
      await resumed.page.evaluate(() => Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async text => { window.copiedCollectionBrief = text; } } }));
      await resumed.page.locator('[data-tab="publications"]').click(); await resumed.page.locator('[data-book]').click(); await resumed.page.locator('[data-copy-plan]').click();
      assert.match(await resumed.page.evaluate(() => copiedCollectionBrief), /Next batch:/);
    } finally { await resumed.context.close(); }
  });
  await check('Off-book packs are quarantined; same-book replacement/removal refreshes immediately without touching learning', async () => {
    const oldLesson = { ...structuredClone(fixture.lessons[0]), id: 'legacy-import-fixture', title: 'Legacy imported lesson', source: { bookId: 'legacy-fixture-book', questionNumber: 1 }, version: 1 };
    const legacyBook = { id: 'legacy-fixture-book', title: 'Legacy collection fixture', author: 'Test fixture', year: 2026, totalQuestions: 1, completedVideos: 1, completedQuestionNumbers: [1] };
    const pack = { packId: 'replacement-fixture', baseUrl: origin + '/', manifest: { version: 1, lessons: [oldLesson], books: [legacyBook] } };
    const { context, page } = await fresh(undefined, [pack]);
    try {
      assert.equal(await page.evaluate(() => testImmersive.at(-1)), true);
      assert.deepEqual(await visibleCounts(page), { books: 1, lessons: 3 });
      assert.equal(await page.evaluate(() => testImmersive.at(-1)), false);
      await page.locator('[data-tab="settings"]').click();
      assert.match(await page.locator('.collection-warning').textContent(), /different book.*hidden/);
      await page.evaluate(id => { Learning.grade(id, false, 'retired-lesson-review', 'review'); Learning.note(id, 'Preserve inactive lesson history.'); Learning.like(id); }, oldLesson.id);
      const before = await page.evaluate(() => localStorage.getItem(Learning.storageKey));
      const sameBookLesson = { ...oldLesson, source: { ...fixture.lessons[0].source, questionNumber: 77 } };
      await reloadPacks(page, [{ ...pack, manifest: { version: 1, lessons: [sameBookLesson], books: fixture.books } }]);
      assert.deepEqual(await visibleCounts(page), { books: 1, lessons: 4 });
      await reloadPacks(page, [{ ...pack, manifest: { version: 2, lessons: [], books: [] } }]);
      assert.deepEqual(await visibleCounts(page), { books: 1, lessons: 3 });
      assert.equal(await page.evaluate(() => localStorage.getItem(Learning.storageKey)), before);
      const updated = { ...structuredClone(fixture.lessons[0]), version: 99, title: 'Same Raja lesson — replacement fixture' };
      await reloadPacks(page, [{ ...pack, manifest: { version: 3, lessons: [updated], books: fixture.books } }]);
      assert.deepEqual(await visibleCounts(page), { books: 1, lessons: 3 });
      await page.locator('[data-tab="feed"]').click(); assert.equal(await page.locator('#lesson-title').textContent(), updated.title);
      assert.equal(await page.evaluate(() => testImmersive.at(-1)), true);
      await reloadPacks(page, []);
      assert.equal(await page.locator('#lesson-title').textContent(), fixture.lessons[0].title);
      assert.equal(await page.evaluate(() => localStorage.getItem(Learning.storageKey)), before);
    } finally { await context.close(); }
  });
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({ passed: passed.length, tests: passed, pageErrors: errors, viewports: ['390×844', '320×568', '1280×900'], physicalAndroidTested: false }, null, 2) + '\n');
  await browser.close(); browser = null; await new Promise(resolve => server.close(resolve));
}
main().catch(async error => {
  console.error(error); fs.mkdirSync(output, { recursive: true });
  fs.writeFileSync(path.join(output, 'failure.json'), JSON.stringify({ error: error.message, stack: error.stack, passed, pageErrors: errors }, null, 2));
  if (browser) await browser.close().catch(() => {}); server.close(); process.exitCode = 1;
});
