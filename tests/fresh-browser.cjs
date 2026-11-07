/* Run against the real media-free build, not a mocked empty lessons route.
 * Build first: node tools/build_web.mjs --profile fresh */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const web = path.resolve(__dirname, '../build/fresh-web');
const output = path.resolve(__dirname, '../test-results/fresh');
const catalogUrl = 'https://raw.githubusercontent.com/blsmohamme972-lab/InstaAnki/main/content/catalog-v2.json';
const mime = { '.html': 'text/html', '.js': 'application/javascript', '.json': 'application/json', '.css': 'text/css', '.txt': 'text/plain' };
const errors = [], passed = [];
let browser, origin;
const server = http.createServer((request, response) => {
  const relative = decodeURIComponent(new URL(request.url, 'http://local').pathname).replace(/^\//, '') || 'index.html';
  const file = path.resolve(web, relative);
  if (!file.startsWith(web + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { response.writeHead(404); response.end(); return; }
  response.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
  response.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; media-src 'self' blob:; connect-src 'self' https:; object-src 'none'; base-uri 'none'");
  response.end(fs.readFileSync(file));
});

async function check(label, run) { await run(); passed.push(label); console.log('PASS ' + label); }
async function until(page, condition) {
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    if (await page.evaluate(condition)) return;
    await page.waitForTimeout(40);
  }
  throw new Error('Browser condition timed out: ' + condition.toString());
}
async function session(viewport = { width: 390, height: 844 }, options = {}) {
  const context = await browser.newContext({ viewport, isMobile: viewport.width < 700, hasTouch: viewport.width < 700, deviceScaleFactor: 1 });
  const holder = { value: options.catalog || { schemaVersion: 1, channel: 'app-v3', packs: [] }, checks: 0 };
  const mediaRequests = [];
  await context.route('https://**/*', route => route.abort());
  await context.route(catalogUrl, route => { holder.checks++; return route.fulfill({ json: holder.value }); });
  await context.addInitScript(({ native, autoCheck }) => {
    localStorage.setItem('instaanki.state.v1', JSON.stringify({ schemaVersion: 1, lessons: {}, reviews: [], settings: { autoPlay: false, autoCheckUpdates: autoCheck, reduceMotion: true, newPerDay: 10 } }));
    window.testDownloads = []; window.testExternal = []; window.testImports = 0; window.testImmersive = []; window.testCopied = '';
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: async text => { window.testCopied = text; } } });
    if (native) window.AndroidNative = {
      getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value), removeItem: key => localStorage.removeItem(key),
      getAppInfo: () => JSON.stringify({ packageName: 'com.instaanki.fresh', version: '0.3.0', versionCode: 4 }),
      listPacks: () => '[]', importZip: () => { window.testImports++; },
      setImmersive: value => window.testImmersive.push(value),
      downloadPackCompatible: (...args) => window.testDownloads.push(args),
      openExternal: url => window.testExternal.push(url),
    };
  }, { native: options.native !== false, autoCheck: options.autoCheck === true });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (/\.(mp3|wav|mp4|png|jpe?g|webp)(\?|$)/i.test(request.url())) mediaRequests.push(request.url()); });
  await page.goto(origin);
  await page.waitForSelector('.collection-count');
  return { context, page, holder, mediaRequests };
}
async function showCatalog(page, holder, value) {
  holder.value = value;
  if (await page.locator('#modal-backdrop').isVisible()) await page.locator('[data-action="close-modal"]').click();
  await page.locator('[data-tab="settings"]').click();
  await page.locator('#screen-settings [data-action="check-updates"]').click();
  await until(page, () => !document.querySelector('#modal-body').textContent.includes('Checking the release catalog'));
}
async function forceAction(page, attribute, value) {
  await page.evaluate(({ attribute, value }) => {
    const button = document.createElement('button'); button.setAttribute(attribute, value); document.body.append(button); button.click(); button.remove();
  }, { attribute, value });
}
async function main() {
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(web, 'data/lessons.json'))), []);
  const distribution = JSON.parse(fs.readFileSync(path.join(web, 'data/distribution.json')));
  assert.equal(distribution.app.packageName, 'com.instaanki.fresh');
  const ledger = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../production/books', distribution.approvedBookId + '.json')));
  const produced = ledger.questions.filter(question => question.status === 'produced').sort((left, right) => left.number - right.number);
  const producedNumbers = produced.map(question => question.number);
  const producedIds = produced.map(question => question.lessonId).filter(Boolean);
  fs.mkdirSync(output, { recursive: true });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });

  await check('Actual fresh bundle opens with zero lessons, no media requests and useful actions at 390 and 320 pixels', async () => {
    for (const viewport of [{ width: 390, height: 844 }, { width: 320, height: 568 }]) {
      const { context, page, mediaRequests } = await session(viewport);
      try {
        assert.equal(await page.locator('#lesson-card').isVisible(), false);
        assert.equal(await page.locator('.feed-toolbar').isVisible(), false);
        assert.equal(await page.locator('.feed-bottomline').isVisible(), false);
        assert.equal(await page.locator('audio').getAttribute('src'), null);
        assert.equal(await page.locator('#feed-empty [data-action="import-pack"]').isVisible(), true);
        await page.locator('#feed-empty [data-action="import-pack"]').click();
        assert.equal(await page.evaluate(() => testImports), 1);
        assert.equal(await page.evaluate(() => testImmersive.some(Boolean)), false, 'Empty welcome should leave system bars available');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.locator('#feed-empty').evaluate(element => { element.scrollTop = 0; });
        await page.screenshot({ path: path.join(output, `empty-${viewport.width}.png`) });
        assert.deepEqual(mediaRequests, []);
      } finally { await context.close(); }
    }
  });

  await check('Publications match the current verified production ledger without presenting historical lessons as installed', async () => {
    const { context, page, mediaRequests } = await session();
    try {
      await page.locator('[data-tab="publications"]').click();
      assert.equal(await page.locator('.publication-card').count(), 1);
      assert.match(await page.locator('.installed-summary').textContent(), /0lessons on this device/);
      assert.ok((await page.locator('.book-progress-head').textContent()).includes(`Historical production${produced.length} / ${ledger.totalQuestions}`));
      assert.equal(await page.locator('img[data-cover]').count(), 0);
      await page.screenshot({ path: path.join(output, 'publications-390.png') });
      await page.locator('.publication-card').click();
      const publicationText = await page.locator('#modal-body').textContent();
      assert.ok(publicationText.includes(`${produced.length} lessons historically produced`));
      assert.ok(publicationText.includes('0 lessons on this device'));
      if (producedNumbers.length) {
        await page.locator(`[data-question="${producedNumbers[0]}"]`).click();
        assert.match(await page.locator('#toast').textContent(), /produced previously.*not installed/);
      }
      await page.locator('[data-copy-plan]').click();
      const brief = await page.evaluate(() => testCopied);
      assert.match(brief, /^Repair the InstaAnki app only\. This fresh collection has no installed lessons\./);
      assert.ok(brief.includes(`Produced source question numbers: ${producedNumbers.join(', ') || 'none'}`));
      assert.ok(brief.includes(`Historical produced lesson IDs: ${producedIds.join(', ') || 'none'}`));
      assert.match(brief, /Do not create new videos/);
      assert.doesNotMatch(brief, /Next batch|Continue the InstaAnki/);
      await page.locator('[data-action="close-modal"]').click();
      await page.locator('[data-tab="review"]').click();
      assert.equal(await page.locator('[data-practice-lesson]').count(), 0);
      assert.equal(await page.locator('#screen-review [data-action="import-pack"]').isVisible(), true);
      await page.locator('[data-tab="insights"]').click();
      await page.locator('[data-tab="settings"]').click();
      assert.match(await page.locator('#screen-settings').textContent(), /0 lessons · No account required/);
      assert.match(await page.locator('.app-version').textContent(), /0\.3\.0/);
      assert.deepEqual(mediaRequests, []);
    } finally { await context.close(); }
  });

  const pack = { id: 'future-explicit-fresh-pack', title: 'Explicit Fresh fixture', version: '1.0.0', minAppVersionCode: 4, url: 'https://example.invalid/fresh.zip', sha256: 'a'.repeat(64), sizeBytes: 1234, lessonVersions: { 'future-fixture': 1 } };
  await check('Fresh excludes untargeted legacy content in automatic prompts, cards and direct download actions', async () => {
    const excluded = [undefined, [], ['com.instaanki.app'], 'com.instaanki.fresh'].map((targets, index) => ({ ...pack, id: `excluded-${index}`, targetPackageNames: targets }));
    const { context, page, holder } = await session(undefined, { autoCheck: true, catalog: { schemaVersion: 1, packs: excluded, latestApp: { version: '9.0', versionCode: 99, url: 'https://example.invalid/legacy.apk' } } });
    try {
      await until(page, () => !!document.querySelector('.collection-count'));
      await page.waitForTimeout(200);
      assert.ok(holder.checks > 0);
      assert.equal(await page.locator('#modal-backdrop').isVisible(), false);
      const state = await page.evaluate(() => localStorage.getItem(Learning.storageKey));
      await showCatalog(page, holder, holder.value);
      assert.equal(await page.locator('[data-update-pack]').count(), 0);
      assert.equal(await page.locator('[data-action="open-app-update"]').count(), 0);
      assert.match(await page.locator('#modal-body').textContent(), /No lesson packages are published for this fresh app yet/);
      for (const item of excluded) await forceAction(page, 'data-download-pack', item.id);
      await forceAction(page, 'data-action', 'open-app-update');
      assert.deepEqual(await page.evaluate(() => testDownloads), []);
      assert.deepEqual(await page.evaluate(() => testExternal), []);
      assert.equal(await page.evaluate(() => localStorage.getItem(Learning.storageKey)), state);
    } finally { await context.close(); }
  });

  await check('Explicit Fresh pack targeting still requires app compatibility before reaching native download', async () => {
    const { context, page, holder } = await session();
    try {
      const compatible = { ...pack, targetPackageNames: ['com.instaanki.fresh'] };
      for (const minimum of [undefined, 0, 4.5, '4', 5]) {
        const item = { ...compatible, minAppVersionCode: minimum };
        await showCatalog(page, holder, { schemaVersion: 1, packs: [item] });
        assert.equal(await page.locator('[data-update-pack]').count(), 1);
        assert.equal(await page.locator('[data-download-pack]').count(), 0);
        await forceAction(page, 'data-download-pack', item.id);
        assert.deepEqual(await page.evaluate(() => testDownloads), []);
      }
      await showCatalog(page, holder, { schemaVersion: 1, packs: [compatible] });
      await page.locator('[data-download-pack]').click();
      assert.deepEqual(await page.evaluate(() => testDownloads), [[pack.url, pack.sha256, pack.sizeBytes, 4]]);
    } finally { await context.close(); }
  });

  await check('APK notices and open action require matching Fresh identity for latestApp, apps list or apps map', async () => {
    const { context, page, holder } = await session();
    const future = { version: '0.3.1', versionCode: 5, url: 'https://example.invalid/fresh-031.apk' };
    try {
      for (const candidate of [future, { ...future, packageName: 'com.instaanki.app' }, { ...future, packageName: 'com.instaanki.fresh', versionCode: 4 }]) {
        await showCatalog(page, holder, { schemaVersion: 1, packs: [], latestApp: candidate });
        assert.equal(await page.locator('[data-action="open-app-update"]').count(), 0);
        await forceAction(page, 'data-action', 'open-app-update');
        assert.deepEqual(await page.evaluate(() => testExternal), []);
      }
      for (const metadata of [
        { latestApp: { ...future, packageName: 'com.instaanki.fresh' } },
        { apps: [{ ...future, packageName: 'com.instaanki.fresh' }] },
        { apps: { 'com.instaanki.fresh': future } },
      ]) {
        await showCatalog(page, holder, { schemaVersion: 1, packs: [], ...metadata });
        await page.locator('[data-action="open-app-update"]').click();
        assert.equal(await page.evaluate(() => testExternal.at(-1)), future.url);
      }
      assert.equal(await page.evaluate(() => testExternal.length), 3);
    } finally { await context.close(); }
  });

  await check('Browser preview reads Fresh identity from its staged distribution marker', async () => {
    const { context, page, holder } = await session({ width: 1280, height: 900 }, { native: false });
    try {
      await page.locator('[data-tab="settings"]').click();
      assert.match(await page.locator('.app-version').textContent(), /0\.3\.0/);
      await showCatalog(page, holder, { schemaVersion: 1, packs: [pack], latestApp: { versionCode: 99, url: 'https://example.invalid/legacy.apk' } });
      assert.equal(await page.locator('[data-update-pack]').count(), 0);
      assert.equal(await page.locator('[data-action="open-app-update"]').count(), 0);
      await page.locator('[data-action="close-modal"]').click();
      await page.locator('[data-tab="feed"]').click();
      await page.screenshot({ path: path.join(output, 'empty-desktop.png') });
    } finally { await context.close(); }
  });

  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({ passed: passed.length, tests: passed, pageErrors: errors, viewports: ['390×844', '320×568', '1280×900'], actualStage: 'build/fresh-web', bundledLessons: 0, physicalAndroidTested: false }, null, 2) + '\n');
  await browser.close(); browser = null;
  await new Promise(resolve => server.close(resolve));
}
main().catch(async error => {
  console.error(error); fs.mkdirSync(output, { recursive: true });
  fs.writeFileSync(path.join(output, 'failure.json'), JSON.stringify({ message: error.message, stack: error.stack, passed, pageErrors: errors }, null, 2));
  if (browser) await browser.close().catch(() => {}); server.close(); process.exitCode = 1;
});
