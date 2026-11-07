/* Daily-topic selection, hierarchy, persistence and feed-limit regressions. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..');
const web = path.join(root, 'web');
const output = path.join(root, 'test-results', 'daily-topics');
const lessons = JSON.parse(fs.readFileSync(path.join(web, 'data/lessons.json'), 'utf8'));
const taxonomy = JSON.parse(fs.readFileSync(path.join(web, 'data/taxonomy.json'), 'utf8'));
const ids = {
  cardiac: 'specialty.cardiac', thoracic: 'specialty.thoracic', vascular: 'specialty.vascular',
  parent: 'condition.pulmonary_sequestration', child: 'condition.extralobar_pulmonary_sequestration',
  focus: 'focus.anatomy', noMatch: 'condition.esophageal_cancer',
};
for (const id of Object.values(ids)) assert.ok(taxonomy.tags.some(tag => tag.id === id && tag.status === 'active'), 'Missing canonical test tag: ' + id);
const cardiac = lessons.find(lesson => lesson.primarySpecialtyId === ids.cardiac);
const thoracic = lessons.find(lesson => lesson.primarySpecialtyId === ids.thoracic);
const vascular = lessons.find(lesson => lesson.primarySpecialtyId === ids.vascular);
const mime = { '.html': 'text/html', '.js': 'application/javascript', '.json': 'application/json', '.css': 'text/css', '.mp3': 'audio/mpeg', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg' };
const csp = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; media-src 'self' blob:; connect-src 'self' https:; font-src 'self' data:; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'";
const server = http.createServer((request, response) => {
  let relative;
  try { relative = decodeURIComponent(new URL(request.url, 'http://local').pathname).replace(/^\/+/, '') || 'index.html'; }
  catch (_) { response.writeHead(400).end(); return; }
  const file = path.resolve(web, relative);
  if (!file.startsWith(web + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { response.writeHead(404).end(); return; }
  const data = fs.readFileSync(file);
  response.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
  response.setHeader('Content-Security-Policy', csp);
  response.setHeader('Accept-Ranges', 'bytes');
  const range = /^bytes=(\d+)-(\d*)$/.exec(request.headers.range || '');
  if (range) {
    const start = Number(range[1]), end = Math.min(data.length - 1, range[2] ? Number(range[2]) : data.length - 1);
    if (start >= data.length || end < start) { response.writeHead(416, { 'Content-Range': `bytes */${data.length}` }).end(); return; }
    response.writeHead(206, { 'Content-Range': `bytes ${start}-${end}/${data.length}`, 'Content-Length': end - start + 1 });
    response.end(data.subarray(start, end + 1)); return;
  }
  response.setHeader('Content-Length', data.length); response.end(data);
});

const results = [], errors = [];
let browser, origin;
async function check(name, fn) { await fn(); results.push(name); console.log('PASS ' + name); }

async function newPage() {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, hasTouch: true, isMobile: true });
  await context.route('https://**/*', route => route.abort());
  await context.addInitScript(() => {
    // Preserve storage across reloads; otherwise this test could mask data loss.
    if (!localStorage.getItem('instaanki.state.v1')) localStorage.setItem('instaanki.state.v1', JSON.stringify({
      schemaVersion: 1, settings: { autoPlay: false, autoCheckUpdates: false, newPerDay: 10 }, lessons: {}, reviews: [],
    }));
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin); await page.waitForSelector('#lesson-card:not([hidden])');
  return { context, page };
}

async function openTopics(page) {
  await page.locator('[data-tab="settings"]').click();
  await page.locator('#screen-settings [data-action="daily-topics"]').click();
  await page.waitForSelector('#daily-topic-search');
}
async function selected(page) { return page.evaluate(() => [...Learning.state.settings.dailyTopicIds].sort()); }
async function topicCheckbox(page, id) {
  // Topic groups may be collapsed. Search is the user path to a nested choice.
  const tag = taxonomy.tags.find(tag => tag.id === id);
  await page.locator('#daily-topic-search').fill(tag.label);
  const checkbox = page.locator(`[data-daily-tag="${id}"]`).first();
  await checkbox.waitFor({ state: 'visible' });
  return checkbox;
}
async function saveTopics(page) {
  await page.locator('[data-action="save-daily-topics"]').click();
  await page.waitForSelector('#modal-backdrop', { state: 'hidden' });
  await page.locator('[data-tab="feed"]').click();
}
async function choose(page, choices) {
  await openTopics(page);
  await page.locator('[data-action="daily-topics-all"]').click();
  for (const id of choices) {
    await (await topicCheckbox(page, id)).check();
    assert.equal(await page.locator(`[data-daily-tag="${id}"]`).evaluateAll(inputs => inputs.every(input => input.checked)), true,
      'Shared topic controls must reflect the same canonical choice');
  }
  await saveTopics(page);
  assert.deepEqual(await selected(page), [...new Set(choices)].sort());
}
async function expectFeed(page, expected) {
  await page.waitForSelector('#lesson-card:not([hidden])');
  const position = (await page.locator('#lesson-position').textContent()).split('/').map(Number);
  const count = position[1];
  assert.equal(count, expected.length, 'Unexpected number of feed lessons');
  // Previous/Next are bounded. Return to the first lesson through the supported
  // keyboard gesture, and never press Finish as a way of wrapping to the start.
  await page.evaluate(() => document.activeElement?.blur());
  for (let index = position[0]; index > 1; index--) await page.keyboard.press('ArrowUp');
  const actual = [];
  for (let index = 0; index < count; index++) {
    const displayedPosition = (await page.locator('#lesson-position').textContent()).split('/').map(Number);
    assert.deepEqual(displayedPosition, [index + 1, count]);
    const audioPath = await page.locator('#lesson-audio').evaluate(audio => new URL(audio.src).pathname);
    const displayed = lessons.find(lesson => audioPath.endsWith('/' + lesson.audioUrl));
    assert.ok(displayed, 'Feed audio does not identify a known lesson');
    assert.equal(displayed.id, expected[index].id, 'Daily-topic feed has an unexpected lesson or order');
    assert.equal(await page.locator('#lesson-title').textContent(), expected[index].title);
    actual.push(displayed.id);
    if (index < count - 1) await page.locator('[data-action="next"]').click();
  }
  assert.equal(new Set(actual).size, actual.length, 'Topic union duplicated a lesson');
  assert.deepEqual(actual, expected.map(lesson => lesson.id));
}

async function main() {
  fs.mkdirSync(output, { recursive: true });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true });
  const { context, page } = await newPage();

  await check('Thoracic daily topics persist across reload and select only the matching lesson', async () => {
    await choose(page, [ids.thoracic]);
    await expectFeed(page, [thoracic]);
    await page.reload(); await page.waitForSelector('#lesson-card:not([hidden])');
    assert.deepEqual(await selected(page), [ids.thoracic]);
    await expectFeed(page, [thoracic]);
  });

  await check('Cardiac and Thoracic selections form a union without duplicate lessons', async () => {
    await choose(page, [ids.cardiac, ids.thoracic]);
    await expectFeed(page, [cardiac, thoracic]);
    await choose(page, [ids.cardiac, ids.thoracic, ids.parent]);
    await expectFeed(page, [cardiac, thoracic]);
  });

  await check('canceling topic edits keeps the saved preference and its feed unchanged', async () => {
    await choose(page, [ids.thoracic]);
    await openTopics(page);
    await page.locator(`[data-daily-tag="${ids.thoracic}"]`).uncheck();
    await page.locator(`[data-daily-tag="${ids.vascular}"]`).check();
    await page.locator('[data-action="close-modal"]').click();
    assert.deepEqual(await selected(page), [ids.thoracic]);
    await page.locator('[data-tab="feed"]').click();
    await expectFeed(page, [thoracic]);
  });

  await check('canonical parent selection matches a child annotation; alias search and lesson count remain accurate', async () => {
    assert.ok(thoracic.tags.some(tag => tag.id === ids.child), 'Fixture must use the child annotation');
    assert.ok(!thoracic.tags.some(tag => tag.id === ids.parent), 'Fixture must not explicitly contain the parent tag');
    await openTopics(page);
    await page.locator('[data-action="daily-topics-all"]').click();
    await page.locator('#daily-topic-search').fill('Bronchopulmonary');
    await page.locator(`[data-daily-tag="${ids.parent}"]`).waitFor({ state: 'visible' });
    await page.locator(`[data-daily-tag="${ids.parent}"]`).check();
    assert.match(await page.locator('#daily-topic-count').textContent(), /\b1\b.*lesson/i);
    await page.locator('#daily-topic-search').fill('this-query-matches-no-surgical-topic');
    assert.equal(await page.locator('[data-daily-tag]:visible').count(), 0);
    assert.match(await page.locator('#daily-topic-count').textContent(), /\b1\b.*lesson/i, 'Searching must not change the selected lesson count');
    await page.locator('#daily-topic-search').fill('Sequestration');
    assert.equal(await page.locator(`[data-daily-tag="${ids.parent}"]`).isChecked(), true);
    await page.screenshot({ path: path.join(output, 'topic-search.png') });
    await saveTopics(page);
    assert.deepEqual(await selected(page), [ids.parent]);
    await expectFeed(page, [thoracic]);
    await choose(page, [ids.focus]);
    await expectFeed(page, [cardiac, thoracic]);
  });

  await check('a valid topic with no produced lessons shows an explanatory empty state', async () => {
    assert.ok(lessons.every(lesson => !lesson.tags.some(tag => tag.id === ids.noMatch)), 'Zero-match fixture is no longer empty');
    await openTopics(page);
    await page.locator('[data-action="daily-topics-all"]').click();
    await (await topicCheckbox(page, ids.noMatch)).check();
    assert.match(await page.locator('#daily-topic-count').textContent(), /\b0\b.*lesson/i);
    await saveTopics(page);
    await page.waitForSelector('#feed-empty:not([hidden])');
    const message = await page.locator('#feed-empty').textContent();
    assert.match(message, /topic|selection|selected/i);
    assert.match(message, /no |none|not |yet|0 /i);
    assert.equal(await page.locator('#lesson-card').isVisible(), false);
    assert.deepEqual(await selected(page), [ids.noMatch]);
    await page.screenshot({ path: path.join(output, 'no-matching-lessons.png') });
  });

  await check('All clears the saved topic constraint and restores the full feed', async () => {
    await choose(page, []);
    await expectFeed(page, lessons);
    await page.reload(); await page.waitForSelector('#lesson-card:not([hidden])');
    assert.deepEqual(await selected(page), []);
    await expectFeed(page, lessons);
  });

  await check('topic filtering precedes the daily new-lesson limit', async () => {
    assert.notEqual(lessons[0].id, thoracic.id, 'Limit-order fixture requires Thoracic after an unrelated lesson');
    await page.locator('[data-tab="settings"]').click();
    await page.locator('[data-action="new-limit"]').click();
    await page.locator('#new-limit-input').fill('1');
    await page.locator('[data-action="save-new-limit"]').click();
    await choose(page, [ids.thoracic]);
    await expectFeed(page, [thoracic]);
    assert.equal(await page.evaluate(() => Learning.state.settings.newPerDay), 1);
    await page.reload(); await page.waitForSelector('#lesson-card:not([hidden])');
    await expectFeed(page, [thoracic]);
  });
  await context.close();

  await check('Due and Saved remain available outside daily topics without altering scheduled recall', async () => {
    const { context: reviewContext, page: reviewPage } = await newPage();
    try {
      await reviewPage.evaluate(id => {
        Learning.like(id);
        Learning.expose(id, 9, new Date(Date.now() - 86400000));
      }, cardiac.id);
      const before = await reviewPage.evaluate(() => JSON.stringify({ lessons: Learning.state.lessons, reviews: Learning.state.reviews }));
      await choose(reviewPage, [ids.thoracic]);
      await expectFeed(reviewPage, [thoracic]);
      for (const feed of ['due', 'saved']) {
        await reviewPage.locator(`[data-feed="${feed}"]`).click();
        await reviewPage.waitForSelector('#lesson-card:not([hidden])');
        assert.equal(await reviewPage.locator('#lesson-title').textContent(), cardiac.title);
        assert.match(await reviewPage.locator('#lesson-position').textContent(), /\/\s*01$/);
        assert.equal(await reviewPage.locator('#lesson-audio').evaluate(audio => audio.paused), true);
        if (await reviewPage.locator('#modal-backdrop').isVisible()) await reviewPage.locator('[data-action="close-modal"]').click();
      }
      await reviewPage.locator('[data-feed="all"]').click();
      await expectFeed(reviewPage, [thoracic]);
      assert.equal(await reviewPage.evaluate(() => JSON.stringify({ lessons: Learning.state.lessons, reviews: Learning.state.reviews })), before);
    } finally { await reviewContext.close(); }
  });

  await check('daily-topic flows produce no uncaught player errors', async () => assert.deepEqual(errors, []));
  await browser.close(); browser = null;
  await new Promise(resolve => server.close(resolve));
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({ passed: results.length, tests: results, physicalAndroidTested: false }, null, 2) + '\n');
}

main().catch(async error => {
  console.error(error);
  fs.mkdirSync(output, { recursive: true });
  fs.writeFileSync(path.join(output, 'failure.json'), JSON.stringify({ error: error.message, stack: error.stack, passed: results, pageErrors: errors }, null, 2) + '\n');
  if (browser) await browser.close().catch(() => {});
  server.close(); process.exitCode = 1;
});
