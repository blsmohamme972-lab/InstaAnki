/* Browser regressions for the watch -> question -> result flow and due reviews.
 * Uses real local MP3 playback; seeking near the end keeps the suite short.
 * PLAYWRIGHT_MODULE can select an existing compatible Playwright installation.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..');
const web = path.join(root, 'web');
const resultsDir = path.join(root, 'test-results');
const lessons = JSON.parse(fs.readFileSync(path.join(web, 'data/lessons.json')));
const mime = { '.html': 'text/html', '.js': 'application/javascript', '.json': 'application/json', '.css': 'text/css', '.mp3': 'audio/mpeg', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg' };
const server = http.createServer((request, response) => {
  const relative = decodeURIComponent(new URL(request.url, 'http://local').pathname).replace(/^\//, '') || 'index.html';
  const file = path.resolve(web, relative);
  if (!file.startsWith(web + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    response.writeHead(404); response.end('Not found'); return;
  }
  const bytes = fs.readFileSync(file);
  response.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
  response.setHeader('Accept-Ranges', 'bytes');
  response.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; media-src 'self' blob:; connect-src 'self' https:; font-src 'self' data:; object-src 'none'; frame-src 'none'; base-uri 'none'");
  const range = /bytes=(\d+)-(\d*)/.exec(request.headers.range || '');
  if (range) {
    const start = Number(range[1]);
    const end = Math.min(bytes.length - 1, range[2] ? Number(range[2]) : bytes.length - 1);
    response.writeHead(206, { 'Content-Range': `bytes ${start}-${end}/${bytes.length}`, 'Content-Length': end - start + 1 });
    response.end(bytes.subarray(start, end + 1)); return;
  }
  response.setHeader('Content-Length', bytes.length);
  response.end(bytes);
});

let browser, origin;
const passed = [], errors = [];
async function check(name, callback) {
  await callback(); passed.push(name); console.log(`PASS ${name}`);
}
async function until(page, predicate, timeout = 10000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await page.evaluate(predicate)) return;
    await page.waitForTimeout(50);
  }
  throw new Error('Browser flow condition timed out');
}
async function fresh() {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, deviceScaleFactor: 1 });
  await context.route('https://**/*', route => route.abort());
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    localStorage.setItem('instaanki.state.v1', JSON.stringify({ schemaVersion: 1, settings: { autoPlay: false, autoCheckUpdates: false, reduceMotion: true }, lessons: {}, reviews: [] }));
    window.flowAttemptIds = [];
    const generate = crypto.randomUUID.bind(crypto);
    crypto.randomUUID = () => { const id = generate(); window.flowAttemptIds.push(id); return id; };
  });
  await page.goto(origin);
  await page.waitForSelector('#lesson-card:not([hidden])');
  await until(page, () => document.querySelector('audio').readyState >= 1);
  return { context, page };
}
async function finishVideo(page) {
  await until(page, () => document.querySelector('audio').readyState >= 1);
  await page.locator('audio').evaluate(audio => { audio.currentTime = Math.max(0, audio.duration - .14); });
  if (await page.locator('audio').evaluate(audio => audio.paused)) await page.locator('#play-button').click();
  await page.waitForSelector('#modal-backdrop:not([hidden]) .quiz-prompt');
}
async function answer(page, index) {
  await page.locator(`[data-answer="${index}"]`).click();
  await page.locator('[data-action="submit-answer"]').click();
  await page.waitForSelector('.quiz-result');
}
async function seedDue(page, ids) {
  await page.evaluate(ids => {
    ids.forEach((id, index) => Learning.grade(id, true, `seed-${index}`, 'review'));
    const backup = Learning.backup();
    const state = JSON.parse(backup.state[Learning.storageKey]);
    ids.forEach((id, index) => { state.lessons[id].card.due = new Date(Date.now() - 60000 + index).toISOString(); });
    backup.state[Learning.storageKey] = JSON.stringify(state);
    Learning.restore(backup);
  }, ids);
}

async function main() {
  fs.mkdirSync(resultsDir, { recursive: true });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true });

  await check('new lesson has clear steps; first enrollment does not interrupt an unfinished video', async () => {
    const { context, page } = await fresh();
    try {
      assert.deepEqual(await page.locator('#lesson-steps li').allTextContents(), ['1 Watch', '2 Answer', '3 Result']);
      await page.locator('audio').evaluate(audio => { audio.currentTime = 12; });
      await page.evaluate(id => Learning.expose(id, 9), lessons[0].id);
      await page.locator('#like-button').click();
      await page.locator('[data-tab="settings"]').click();
      await page.locator('[data-tab="feed"]').click();
      assert.equal(await page.locator('#modal-backdrop').isVisible(), false);
      assert.ok(await page.locator('audio').evaluate(audio => audio.currentTime >= 12));
      const record = await page.evaluate(id => ({ reps: Learning.get(id).card.reps, reviews: Learning.state.reviews.length }), lessons[0].id);
      assert.deepEqual(record, { reps: 0, reviews: 0 });
      await finishVideo(page);
      assert.equal(await page.locator('#modal-title').textContent(), 'New lesson question');
      assert.equal(await page.locator('.quiz-lesson-title').textContent(), lessons[0].title);
      assert.equal(await page.locator('.quiz-choice-count').textContent(), `Choose 1 of ${lessons[0].quiz.options.length} answers`);
      assert.match(await page.locator('.quiz-steps [aria-current="step"]').textContent(), /Answer/);
      await page.screenshot({ path: path.join(resultsDir, 'flow-new-question.png') });
      await answer(page, lessons[0].quiz.correctIndex);
      assert.match(await page.locator('.correct-answer').textContent(), /Correct answer:/);
      assert.match(await page.locator('.quiz-steps [aria-current="step"]').textContent(), /Result/);
      assert.equal(await page.evaluate(() => Learning.state.reviews.length), 1);
      await page.screenshot({ path: path.join(resultsDir, 'flow-answer-result.png') });
      await page.locator('[data-action="quiz-continue"]').click();
      assert.equal(await page.locator('#lesson-title').textContent(), lessons[1].title);
    } finally { await context.close(); }
  });

  await check('closing a pending question preserves its selection and attempt; Play returns to the question', async () => {
    const { context, page } = await fresh();
    try {
      await finishVideo(page);
      const option = await page.$(`[data-answer="${lessons[0].quiz.correctIndex}"]`);
      await option.focus(); await option.press('Space');
      assert.equal(await option.evaluate(button => button.isConnected && document.activeElement === button), true);
      assert.equal(await page.locator('[data-action="submit-answer"]').isEnabled(), true);
      const attempts = await page.evaluate(() => [...flowAttemptIds]);
      await page.locator('[data-action="close-modal"]').click();
      assert.equal(await page.locator('#lesson-question-button').textContent(), 'Answer question');
      assert.equal(await page.locator('#play-button').getAttribute('aria-label'), 'Answer question');
      await page.locator('#play-button').click();
      assert.equal(await page.locator(`[data-answer="${lessons[0].quiz.correctIndex}"]`).getAttribute('aria-pressed'), 'true');
      assert.deepEqual(await page.evaluate(() => [...flowAttemptIds]), attempts);
      await page.locator('[data-action="submit-answer"]').click();
      await page.waitForSelector('.quiz-result');
      const review = await page.evaluate(() => Learning.state.reviews.at(-1));
      assert.equal(review.attemptId, attempts[0]);
      await page.locator('[data-action="close-modal"]').click();
      assert.equal(await page.locator('#lesson-question-button').textContent(), 'View answer');
      await page.locator('#lesson-question-button').click();
      await page.waitForSelector('.quiz-result');
      assert.equal(await page.evaluate(() => Learning.state.reviews.length), 1);
      assert.deepEqual(await page.evaluate(() => [...flowAttemptIds]), attempts);
    } finally { await context.close(); }
  });

  await check('practice on an unseen lesson remains practice after watching and returns to the review screen', async () => {
    const { context, page } = await fresh();
    try {
      await page.locator('[data-tab="review"]').click();
      await page.locator(`[data-practice-lesson="${lessons[0].id}"]`).click();
      assert.equal(await page.locator('#modal-title').textContent(), 'Practice question');
      await page.locator(`[data-answer="${lessons[0].quiz.correctIndex}"]`).click();
      const attempts = await page.evaluate(() => [...flowAttemptIds]);
      await page.locator(`[data-watch-lesson="${lessons[0].id}"]`).click();
      await until(page, () => !document.querySelector('audio').paused);
      await finishVideo(page);
      assert.equal(await page.locator('#modal-title').textContent(), 'Practice question');
      assert.equal(await page.locator(`[data-answer="${lessons[0].quiz.correctIndex}"]`).getAttribute('aria-pressed'), 'true');
      assert.deepEqual(await page.evaluate(() => [...flowAttemptIds]), attempts);
      await page.locator('[data-action="submit-answer"]').click();
      await page.waitForSelector('.quiz-result');
      const result = await page.evaluate(id => ({ card: Learning.get(id).card, review: Learning.state.reviews.at(-1) }), lessons[0].id);
      assert.equal(result.card, null);
      assert.equal(result.review.practice, true);
      assert.equal(result.review.attemptId, attempts[0]);
      assert.match(await page.locator('[data-action="quiz-continue"]').textContent(), /Back to review/);
      await page.locator('[data-action="quiz-continue"]').click();
      assert.equal(await page.locator('#screen-review').isVisible(), true);
      assert.equal(await page.locator('#modal-backdrop').isVisible(), false);
    } finally { await context.close(); }
  });

  await check('due reviews are question-first; explanation becomes practice without rescheduling or looping the session', async () => {
    const { context, page } = await fresh();
    try {
      await seedDue(page, [lessons[0].id, lessons[1].id]);
      await page.locator('[data-tab="review"]').click();
      await page.locator('[data-action="start-review"]').click();
      assert.equal(await page.locator('#modal-title').textContent(), 'Due review');
      assert.match(await page.locator('.quiz-context-note').textContent(), /Answer from memory/);
      assert.equal(await page.locator('audio').evaluate(audio => audio.paused), true);
      const before = await page.evaluate(id => JSON.stringify(Learning.get(id).card), lessons[0].id);
      await page.screenshot({ path: path.join(resultsDir, 'flow-due-question.png') });
      await page.locator(`[data-watch-lesson="${lessons[0].id}"]`).click();
      await finishVideo(page);
      assert.equal(await page.locator('#modal-title').textContent(), 'Practice question');
      assert.match(await page.locator('.quiz-context-note').textContent(), /due review stays/);
      await answer(page, lessons[0].quiz.correctIndex);
      assert.equal(await page.evaluate(id => JSON.stringify(Learning.get(id).card), lessons[0].id), before);
      assert.equal(await page.evaluate(() => Learning.state.reviews.at(-1).practice), true);
      await page.screenshot({ path: path.join(resultsDir, 'flow-assisted-practice.png') });
      await page.locator('[data-action="quiz-continue"]').click();
      assert.equal(await page.locator('.quiz-lesson-title').textContent(), lessons[1].title);
      assert.equal(await page.locator('#modal-title').textContent(), 'Due review');
      await until(page, () => document.querySelector('#modal-body').scrollTop <= 1);
      await answer(page, lessons[1].quiz.correctIndex);
      assert.match(await page.locator('[data-action="quiz-continue"]').textContent(), /Back to review/);
      await page.locator('[data-action="quiz-continue"]').click();
      assert.equal(await page.locator('#screen-review').isVisible(), true);
      assert.equal(await page.locator('#modal-backdrop').isVisible(), false);
      assert.equal(await page.evaluate(id => Learning.due([{ id }]).length, lessons[0].id), 1);
      assert.equal(await page.evaluate(() => Learning.state.reviews.length), 4);
    } finally { await context.close(); }
  });

  await check('replaying an answered video restores its feedback and never creates a second grade', async () => {
    const { context, page } = await fresh();
    try {
      await finishVideo(page); await answer(page, lessons[0].quiz.correctIndex);
      const before = await page.evaluate(id => JSON.stringify({ card: Learning.get(id).card, reviews: Learning.state.reviews, attempts: flowAttemptIds }), lessons[0].id);
      await page.locator(`[data-watch-lesson="${lessons[0].id}"]`).click();
      await finishVideo(page);
      await page.waitForSelector('.quiz-result');
      assert.equal(await page.locator('.quiz-option:not(:disabled)').count(), 0);
      assert.equal(await page.evaluate(id => JSON.stringify({ card: Learning.get(id).card, reviews: Learning.state.reviews, attempts: flowAttemptIds }), lessons[0].id), before);
      await page.locator('[data-action="quiz-continue"]').click();
      assert.equal(await page.locator('#lesson-title').textContent(), lessons[1].title);
    } finally { await context.close(); }
  });

  await check('one-lesson selections end with clear choices and replay returns to the saved result', async () => {
    const { context, page } = await fresh();
    try {
      await page.locator('#like-button').click();
      await page.locator('[data-feed="saved"]').click();
      assert.match(await page.locator('#lesson-position').textContent(), /01\s*\/\s*01/);
      await finishVideo(page); await answer(page, lessons[0].quiz.correctIndex);
      assert.match(await page.locator('[data-action="quiz-continue"]').textContent(), /Finish lesson/);
      await page.locator('[data-action="quiz-continue"]').click();
      assert.equal(await page.locator('#modal-title').textContent(), 'You reached the end.');
      assert.equal(await page.locator('#modal-body [data-action="daily-topics"]').isVisible(), true);
      assert.equal(await page.locator('#modal-body [data-action="review-home"]').isVisible(), true);
      await page.screenshot({ path: path.join(resultsDir, 'flow-selection-complete.png') });
      await page.locator(`[data-watch-lesson="${lessons[0].id}"]`).click();
      await finishVideo(page); await page.waitForSelector('.quiz-result');
      assert.equal(await page.evaluate(() => Learning.state.reviews.length), 1);
      assert.match(await page.locator('[data-action="quiz-continue"]').textContent(), /Finish lesson/);
      await page.locator('[data-action="quiz-continue"]').click();
      assert.equal(await page.locator('#modal-title').textContent(), 'You reached the end.');
      assert.equal(await page.locator('[data-feed="saved"]').getAttribute('class'), 'selected');
    } finally { await context.close(); }
  });

  await check('incorrect and unknown answers still schedule Again; feedback states the correct answer in text', async () => {
    const { context, page } = await fresh();
    try {
      await finishVideo(page);
      await page.locator('[data-action="dont-know"]').click();
      await page.waitForSelector('.quiz-result');
      assert.equal(await page.locator('.quiz-result h3').textContent(), 'Answer explained');
      assert.equal(await page.evaluate(() => Learning.state.reviews.at(-1).rating), 'Again');
      assert.equal(await page.evaluate(() => Learning.state.reviews.at(-1).practice), false);
      await page.locator('[data-action="quiz-continue"]').click();
      await finishVideo(page);
      await answer(page, (lessons[1].quiz.correctIndex + 1) % lessons[1].quiz.options.length);
      assert.equal(await page.locator('.quiz-result h3').textContent(), 'Incorrect');
      assert.match(await page.locator('.correct-answer').textContent(), new RegExp(lessons[1].quiz.options[lessons[1].quiz.correctIndex].replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
      assert.equal(await page.evaluate(() => Learning.state.reviews.at(-1).rating), 'Again');
      assert.equal(await page.locator('.quiz-option:not(:disabled)').count(), 0);
    } finally { await context.close(); }
  });

  await check('feedback keeps Next and Replay visible and usable at 390×844 and 360×640 without manual scrolling', async () => {
    for (const viewport of [{ width: 390, height: 844 }, { width: 360, height: 640 }]) {
      const { context, page } = await fresh();
      try {
        await page.setViewportSize(viewport);
        await finishVideo(page); await answer(page, lessons[0].quiz.correctIndex);
        assert.equal(await page.locator('#modal-body .quiz-actions').count(), 0);
        assert.equal(await page.locator('#modal-actions .quiz-actions').count(), 1);
        assert.equal(await page.locator('.answered-options').getAttribute('open'), null);
        assert.equal(await page.locator('.quiz-option').count(), lessons[0].quiz.options.length);
        for (const selector of ['[data-action="quiz-continue"]', `[data-watch-lesson="${lessons[0].id}"]`]) {
          const geometry = await page.locator(selector).evaluate(button => {
            const box = button.getBoundingClientRect();
            const header = document.querySelector('.modal-header').getBoundingClientRect();
            const center = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
            return { inViewport: box.top >= header.bottom && box.bottom <= innerHeight && box.left >= 0 && box.right <= innerWidth, unobscured: !!center && button.contains(center) };
          });
          assert.equal(geometry.inViewport, true, `${selector} must fit ${viewport.width}×${viewport.height}`);
          assert.equal(geometry.unobscured, true, `${selector} must remain directly tappable`);
        }
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        assert.equal(await page.evaluate(() => document.querySelector('#modal-body').getBoundingClientRect().bottom <= document.querySelector('#modal-actions').getBoundingClientRect().top + 1), true);
        await page.screenshot({ path: path.join(resultsDir, `flow-result-${viewport.width}x${viewport.height}.png`) });
      } finally { await context.close(); }
    }
  });

  await check('flow changes produce no uncaught browser errors', async () => assert.deepEqual(errors, []));
  fs.writeFileSync(path.join(resultsDir, 'lesson-flow-report.json'), JSON.stringify({ passed: passed.length, tests: passed, realAudioPlayback: true, physicalAndroidTested: false }, null, 2) + '\n');
}

main().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  server.close();
});
