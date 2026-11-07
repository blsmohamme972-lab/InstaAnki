/* Regression checks for narrated, image-anchored guidance in the real player.
 * Run with npm's Playwright dependency, or set PLAYWRIGHT_MODULE to an existing
 * Playwright installation. These checks use DOM image bounds, not guidance.js
 * projection functions, as the geometric reference.
 */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { loadRajaStarterFixture, routeRajaStarterFixture } = require('./helpers/raja-starter-fixture.cjs');

const root = path.resolve(__dirname, '..');
const web = path.join(root, 'web');
const output = path.join(root, 'test-results', 'guidance');
const fixture = loadRajaStarterFixture(web);
const lessons = fixture.lessons;
const sizes = [{ width: 360, height: 640 }, { width: 390, height: 844 }, { width: 430, height: 932 }];
const mime = {
  '.html': 'text/html', '.js': 'application/javascript', '.json': 'application/json',
  '.css': 'text/css', '.mp3': 'audio/mpeg', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.ogg': 'audio/ogg', '.wav': 'audio/wav',
};
const csp = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; media-src 'self' blob:; connect-src 'self' https:; font-src 'self' data:; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'";

// A byte-range server keeps seeking representative of the offline WebView host.
const server = http.createServer((request, response) => {
  let relative;
  try { relative = decodeURIComponent(new URL(request.url, 'http://local').pathname).replace(/^\/+/, '') || 'index.html'; }
  catch (_) { response.writeHead(400).end(); return; }
  const file = path.resolve(web, relative);
  if (!file.startsWith(web + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    response.writeHead(404).end('Not found'); return;
  }
  const data = fs.readFileSync(file);
  response.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
  response.setHeader('Content-Security-Policy', csp);
  response.setHeader('Accept-Ranges', 'bytes');
  const range = /^bytes=(\d+)-(\d*)$/.exec(request.headers.range || '');
  if (range) {
    const start = Number(range[1]);
    const end = Math.min(data.length - 1, range[2] ? Number(range[2]) : data.length - 1);
    if (start >= data.length || end < start) { response.writeHead(416, { 'Content-Range': `bytes */${data.length}` }).end(); return; }
    response.writeHead(206, { 'Content-Range': `bytes ${start}-${end}/${data.length}`, 'Content-Length': end - start + 1 });
    response.end(data.subarray(start, end + 1)); return;
  }
  response.setHeader('Content-Length', data.length);
  response.end(data);
});

const results = [];
const geometry = [];
const errors = [];
let browser;
let origin;

async function check(name, fn) {
  await fn(); const scoped = fixture.label + ': ' + name; results.push(scoped); console.log('PASS ' + scoped);
}

// Playwright's waitForFunction uses evaluation inside the page and is blocked
// by the native shell's CSP. CDP evaluate calls do not need unsafe-eval.
async function until(page, predicate, argument, timeout = 10000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await page.evaluate(predicate, argument)) return;
    await page.waitForTimeout(30);
  }
  throw new Error('Browser condition timed out: ' + predicate.toString());
}

async function newPage(options = {}) {
  const context = await browser.newContext({
    viewport: sizes[1], deviceScaleFactor: 1, hasTouch: true, isMobile: true,
    ...options,
  });
  await context.route('https://**/*', route => route.abort());
  await routeRajaStarterFixture(context, fixture);
  await context.addInitScript(() => {
    localStorage.setItem('instaanki.state.v1', JSON.stringify({
      schemaVersion: 1,
      settings: { autoPlay: false, autoCheckUpdates: false, reduceMotion: false, speed: 1 },
      lessons: {}, reviews: [],
    }));
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  return { context, page };
}

async function open(page) {
  await page.goto(origin);
  await page.waitForSelector('#lesson-card:not([hidden])');
  await until(page, () => !!window.VisualGuidance && document.querySelector('#lesson-audio').readyState >= 1);
}

async function firstLesson(page) {
  const index = Number((await page.locator('#lesson-position').textContent()).split('/')[0]);
  await page.evaluate(() => document.activeElement?.blur());
  for (let current = index; current > 1; current--) await page.keyboard.press('ArrowUp');
  await until(page, () => document.querySelector('#lesson-audio').readyState >= 1);
}

function cueAt(lesson, time) {
  time = Math.min(time, lesson.presentation?.effectiveEndSeconds || Infinity);
  const narrated = lesson.visualGuidance.cues.find(cue => time >= cue.start && time < cue.end);
  if (narrated) return narrated;
  const outro = lesson.realImageOutro;
  if (outro && time >= outro.start && time < outro.end && lesson.visualGuidance.outroTargetId) {
    return { id: 'real-image-outro', sceneId: 'real-image-outro', targetId: lesson.visualGuidance.outroTargetId,
      start: outro.start, end: outro.end, text: '' };
  }
  return null;
}

function imageAt(lesson, time) {
  time = Math.min(time, lesson.presentation?.effectiveEndSeconds || Infinity);
  if (!lesson.presentation?.clinicalGallery && lesson.realImageOutro && time >= lesson.realImageOutro.start && lesson.realImages?.length) return lesson.realImages[0].url;
  return (lesson.scenes.find(scene => time >= scene.start && time < scene.end) || lesson.scenes.at(-1))?.image || lesson.poster;
}

function targetAt(lesson, time) {
  const gallery = lesson.presentation?.clinicalGallery;
  if (gallery && time >= gallery.startSeconds) return null;
  const cue = cueAt(lesson, time);
  const target = cue && lesson.visualGuidance.targets[cue.targetId];
  return target && target.image === imageAt(lesson, time) ? target : null;
}

async function frames(page, count = 2) {
  await page.evaluate(count => new Promise(resolve => {
    const advance = () => --count <= 0 ? resolve() : requestAnimationFrame(advance);
    requestAnimationFrame(advance);
  }), count);
}

async function seek(page, time) {
  await page.locator('#lesson-audio').evaluate((audio, time) => { audio.pause(); audio.currentTime = time; }, time);
  await until(page, time => {
    const audio = document.querySelector('#lesson-audio');
    return !audio.seeking && Math.abs(audio.currentTime - time) < 0.025;
  }, time);
  await frames(page);
  return page.locator('#lesson-audio').evaluate(audio => audio.currentTime);
}

async function assertAt(page, lesson, requestedTime, label) {
  // Read the browser's actual media time: MP3 seeking may round sub-microseconds.
  const time = await seek(page, requestedTime);
  return assertCurrent(page, lesson, time, label);
}

async function assertCurrent(page, lesson, time, label) {
  const cue = cueAt(lesson, time);
  const target = targetAt(lesson, time);
  const wantedImage = imageAt(lesson, time);
  await until(page, ({ cueId, targetId, image }) => {
    const stage = document.querySelector('#visual-stage');
    const picture = document.querySelector('#lesson-image');
    return picture.complete && picture.naturalWidth > 0 &&
      new URL(picture.currentSrc || picture.src).pathname.endsWith('/' + image) &&
      (stage.dataset.cueId || '') === cueId && (stage.dataset.targetId || '') === targetId;
  }, { cueId: cue?.id || '', targetId: target ? cue.targetId : '', image: wantedImage }).catch(async error => {
    const observed = await page.evaluate(() => ({time: document.querySelector('audio').currentTime, image: document.querySelector('#lesson-image').currentSrc, cueId: document.querySelector('#visual-stage').dataset.cueId, targetId: document.querySelector('#visual-stage').dataset.targetId}));
    throw new Error(`${label}: ${lesson.id} at ${time}; expected ${cue?.id || 'no cue'} / ${target ? cue.targetId : 'no target'}; observed ${JSON.stringify(observed)}. ${error.message}`);
  });
  await frames(page);

  const measured = await page.evaluate(target => {
    const picture = document.querySelector('#lesson-image');
    const stage = document.querySelector('#visual-stage');
    const pointer = document.querySelector('#teaching-pointer');
    const tip = document.querySelector('#pointer-tip');
    const shaft = document.querySelector('#pointer-shaft');
    const spotlight = document.querySelector('#spotlight');
    const imageRect = picture.getBoundingClientRect();
    const stageRect = stage.getBoundingClientRect();
    const imageStyle = getComputedStyle(picture);
    const pointerStyle = pointer && getComputedStyle(pointer);
    const spotStyle = getComputedStyle(spotlight);
    const visible = !!pointer && !pointer.hidden && pointer.getClientRects().length > 0 &&
      pointerStyle.display !== 'none' && pointerStyle.visibility !== 'hidden' && Number(pointerStyle.opacity) > 0;
    const base = {
      time: document.querySelector('#lesson-audio').currentTime,
      targetId: stage.dataset.targetId || '', cueId: stage.dataset.cueId || '',
      pointerVisible: visible, spotlightOpacity: Number(spotStyle.opacity),
      image: picture.currentSrc || picture.src,
      naturalWidth: picture.naturalWidth, naturalHeight: picture.naturalHeight,
      imageRect: { x: imageRect.x, y: imageRect.y, width: imageRect.width, height: imageRect.height },
      stageRect: { x: stageRect.x, y: stageRect.y, width: stageRect.width, height: stageRect.height },
      objectFit: imageStyle.objectFit, objectPosition: imageStyle.objectPosition,
      cameraTransform: getComputedStyle(document.querySelector('#camera-layer')).transform,
      horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
    };
    if (!target || !visible) return base;

    // Independent observation: use the IMG's final CSS bounding box, including
    // its parent transform and clinical insets, then fit the original bitmap.
    // No app/engine geometry helpers or its reported camera state are read.
    const fit = Math.min(imageRect.width / picture.naturalWidth, imageRect.height / picture.naturalHeight);
    const paintedWidth = picture.naturalWidth * fit;
    const paintedHeight = picture.naturalHeight * fit;
    const paintedLeft = imageRect.left + (imageRect.width - paintedWidth) / 2;
    const paintedTop = imageRect.top + (imageRect.height - paintedHeight) / 2;
    const expected = { x: paintedLeft + target.x * paintedWidth, y: paintedTop + target.y * paintedHeight };
    const expectedSpot = {
      x: paintedLeft + (target.spotX ?? target.x) * paintedWidth,
      y: paintedTop + (target.spotY ?? target.y) * paintedHeight,
    };
    const tipPoint = new DOMPoint(tip.cx.baseVal.value, tip.cy.baseVal.value).matrixTransform(tip.getScreenCTM());
    const endpoint = shaft.getPointAtLength(shaft.getTotalLength());
    const shaftPoint = new DOMPoint(endpoint.x, endpoint.y).matrixTransform(shaft.getScreenCTM());
    const spot = /\bat\s+(-?[\d.]+)px\s+(-?[\d.]+)px/.exec(spotStyle.backgroundImage);
    const spotRect = spotlight.getBoundingClientRect();
    return {
      ...base, expected, expectedSpot,
      tip: { x: tipPoint.x, y: tipPoint.y },
      shaftEnd: { x: shaftPoint.x, y: shaftPoint.y },
      spotlight: spot ? { x: spotRect.left + Number(spot[1]), y: spotRect.top + Number(spot[2]) } : null,
      spotlightBackground: spotStyle.backgroundImage,
    };
  }, target);

  const prefix = `${label}: ${lesson.id} @ ${time.toFixed(3)}s`;
  assert.equal(measured.horizontalOverflow, false, prefix + ' has horizontal overflow');
  assert.equal(measured.objectFit, 'contain', prefix + ' must retain the whole source bitmap');
  assert.match(measured.objectPosition, /^(50% 50%|center(?: center)?)$/, prefix + ' unexpected image alignment');
  if (!target) {
    assert.equal(measured.pointerVisible, false, prefix + ' must hide an unanchored pointer');
    assert.equal(measured.spotlightOpacity, 0, prefix + ' must hide an unanchored spotlight');
    return measured;
  }
  const declared = lesson.visualGuidance.images[target.image];
  assert.equal(measured.naturalWidth, declared.width, prefix + ' image width does not match the calibrated asset');
  assert.equal(measured.naturalHeight, declared.height, prefix + ' image height does not match the calibrated asset');
  assert.equal(measured.pointerVisible, true, prefix + ' lost its target pointer');
  assert.ok(measured.spotlightOpacity > 0, prefix + ' lost its spotlight');
  assert.ok(measured.spotlight, prefix + ' spotlight has no pixel-based focus: ' + measured.spotlightBackground);
  const error = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  const tipError = error(measured.tip, measured.expected);
  const spotError = error(measured.spotlight, measured.expectedSpot);
  const shaftError = error(measured.shaftEnd, measured.expected);
  assert.ok(tipError <= 1, `${prefix}: pointer misses the authored image feature by ${tipError.toFixed(3)}px`);
  assert.ok(spotError <= 1, `${prefix}: spotlight misses its image region by ${spotError.toFixed(3)}px`);
  assert.ok(shaftError <= 1, `${prefix}: arrow endpoint misses the image feature by ${shaftError.toFixed(3)}px`);
  assert.ok(measured.tip.x >= measured.stageRect.x - 1 && measured.tip.x <= measured.stageRect.x + measured.stageRect.width + 1 &&
    measured.tip.y >= measured.stageRect.y - 1 && measured.tip.y <= measured.stageRect.y + measured.stageRect.height + 1,
  prefix + ' target is outside the visible stage');
  geometry.push({ lesson: lesson.id, cue: cue.id, label, time, tipError, spotError, shaftError });
  return measured;
}

function targetedCues(lesson) {
  return lesson.visualGuidance.cues.filter(cue => cue.targetId && lesson.visualGuidance.targets[cue.targetId]);
}

async function main() {
  fs.mkdirSync(output, { recursive: true });
  assert.equal(lessons.length, 3, 'The starter collection must contain all three lessons');
  for (const lesson of lessons) {
    assert.equal(lesson.visualGuidance?.schemaVersion, 1, lesson.id + ' needs authored guidance before this suite can run');
    assert.ok(targetedCues(lesson).length, lesson.id + ' has no calibrated target cues');
  }
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true });
  const { context, page } = await newPage();
  await open(page);

  for (const size of sizes) {
    await check(`all authored cue tips and spotlight regions align at ${size.width}×${size.height}`, async () => {
      await page.setViewportSize(size);
      await firstLesson(page);
      for (const [lessonIndex, lesson] of lessons.entries()) {
        assert.equal(await page.locator('#lesson-title').textContent(), lesson.title);
        await until(page, () => document.querySelector('#lesson-audio').readyState >= 1);
        const saved = new Set();
        for (const cue of lesson.visualGuidance.cues) {
          const midpoint = (cue.start + cue.end) / 2;
          await assertAt(page, lesson, midpoint, `${size.width}×${size.height}`);
          const target = targetAt(lesson, midpoint);
          if (target) {
            const kind = lesson.realImages.some(image => image.url === target.image) ? 'clinical' : 'mnemonic';
            if (!saved.has(kind)) {
              saved.add(kind);
              await page.screenshot({ path: path.join(output, `${lesson.id}-${size.width}-${kind}.png`) });
            }
          }
        }
        assert.ok(saved.has('mnemonic'), lesson.id + ' has no tested mnemonic guidance');
        if (lesson.presentation?.clinicalGallery) {
          await assertAt(page, lesson, lesson.presentation.clinicalGallery.startSeconds + 1, 'narrated clinical gallery');
          assert.equal(await page.locator('#lesson-ending').isVisible(), true);
          assert.equal(await page.locator('#teaching-pointer').isVisible(), false, 'Gallery inherited a pointer from another image');
        } else await assertAt(page, lesson, lesson.realImageOutro.start + Math.min(2, (lesson.realImageOutro.end - lesson.realImageOutro.start) / 2), 'real-image outro');
        if (!saved.has('clinical')) {
          if (lesson.presentation?.clinicalGallery) assert.ok(lesson.presentation.clinicalGallery.images.length >= 3, lesson.id + ' has no clinical ending gallery');
          else assert.ok(lesson.visualGuidance.outroTargetId, lesson.id + ' has no calibrated clinical outro target');
          await page.screenshot({ path: path.join(output, `${lesson.id}-${size.width}-clinical.png`) });
        }
        if (lessonIndex < lessons.length - 1) await page.locator('[data-action="next"]').click();
      }
    });
  }

  const lesson = lessons[0];
  await page.setViewportSize(sizes[1]);
  await firstLesson(page);
  await check('forward and backward seeking select exact half-open cue intervals', async () => {
    const boundaries = [...new Set(lesson.visualGuidance.cues.flatMap(cue => [cue.start, cue.end]))]
      .filter(time => time > 0.03 && time < (lesson.presentation?.effectiveEndSeconds || lesson.durationSeconds) - 0.03);
    for (const boundary of boundaries) {
      await assertAt(page, lesson, boundary + 0.02, 'after boundary');
      await assertAt(page, lesson, boundary - 0.02, 'before boundary after backward seek');
      await assertAt(page, lesson, boundary, 'at boundary using actual media time');
    }
  });

  const candidates = targetedCues(lesson);
  const cue = candidates.find(item => item.end - item.start > 1) || candidates[0];
  const cueTime = (cue.start + cue.end) / 2;
  await check('paused guidance stays visible and motionless on its image feature', async () => {
    const before = await assertAt(page, lesson, cueTime, 'paused');
    await frames(page, 12);
    const after = await assertCurrent(page, lesson, cueTime, 'paused after twelve frames');
    assert.equal(after.time, before.time, 'Paused narration advanced');
    assert.equal(after.cameraTransform, before.cameraTransform, 'Paused camera drifted');
    assert.ok(Math.hypot(after.tip.x - before.tip.x, after.tip.y - before.tip.y) < 0.1, 'Paused pointer drifted');
  });

  await check('the Reduce camera motion setting preserves precise pointer and spotlight guidance', async () => {
    await page.locator('[data-tab="settings"]').click();
    await page.locator('[data-setting="reduceMotion"]').check();
    await page.locator('[data-tab="feed"]').click();
    assert.equal(await page.evaluate(() => Learning.state.settings.reduceMotion), true);
    const before = await assertAt(page, lesson, cue.start + (cue.end - cue.start) * 0.25, 'reduced motion first position');
    const after = await assertAt(page, lesson, cue.start + (cue.end - cue.start) * 0.75, 'reduced motion later position');
    assert.equal(after.cameraTransform, before.cameraTransform, 'Reduced-motion camera keeps animating');
    await page.locator('[data-tab="settings"]').click();
    await page.locator('[data-setting="reduceMotion"]').uncheck();
    await page.locator('[data-tab="feed"]').click();
  });

  await check('rate changes and live playback use the narration clock across a target boundary', async () => {
    const cues = lesson.visualGuidance.cues;
    const next = cues.find((candidate, index) => {
      const previous = cues[index - 1];
      return previous && previous.targetId && candidate.targetId && previous.targetId !== candidate.targetId &&
        Math.abs(previous.end - candidate.start) < 0.001 && previous.end - previous.start > 0.6 && candidate.end - candidate.start > 1;
    });
    assert.ok(next, 'The lesson needs one adjacent change of target for the playback regression');
    for (const rate of [0.75, 1.5, 2]) {
      await page.locator('#speed-button').click();
      await page.locator(`[data-speed="${rate}"]`).click();
      assert.equal(await page.locator('#lesson-audio').evaluate(audio => audio.playbackRate), rate);
      await assertAt(page, lesson, next.start - 0.25, `before live boundary at ${rate}×`);
      await page.locator('#play-button').click();
      await until(page, time => document.querySelector('#lesson-audio').currentTime > time + 0.15, next.start);
      await page.locator('#play-button').click();
      const actual = await page.locator('#lesson-audio').evaluate(audio => audio.currentTime);
      assert.ok(actual < next.end, 'Playback test overshot the target cue');
      await assertCurrent(page, lesson, actual, `live playback at ${rate}×`);
      await assertAt(page, lesson, next.start - 0.15, `backward seek at ${rate}×`);
    }
  });

  await check('resizing a paused clinical image keeps overlays attached to the bitmap', async () => {
    const clinical = candidates.find(item => lesson.realImages.some(image => image.url === lesson.visualGuidance.targets[item.targetId].image));
    assert.ok(clinical, 'Clinical guidance fixture is missing');
    const time = await seek(page, (clinical.start + clinical.end) / 2);
    for (const size of sizes) {
      await page.setViewportSize(size);
      await frames(page, 3);
      await assertCurrent(page, lesson, time, `paused clinical resize ${size.width}×${size.height}`);
    }
  });
  await context.close();

  await check('image loading hides the old pointer; late image completion cannot retarget a new scene', async () => {
    const { context: pendingContext, page: pendingPage } = await newPage();
    const clinical = candidates.find(item => lesson.realImages.some(image => image.url === lesson.visualGuidance.targets[item.targetId].image));
    const mnemonic = candidates.find(item => lesson.visualGuidance.targets[item.targetId].image === lesson.poster);
    const clinicalPath = lesson.visualGuidance.targets[clinical.targetId].image;
    let release;
    let requested;
    const gate = new Promise(resolve => { release = resolve; });
    const requestStarted = new Promise(resolve => { requested = resolve; });
    await pendingPage.route('**/' + clinicalPath, async route => {
      requested();
      await gate;
      await route.fulfill({ path: path.join(web, clinicalPath), contentType: mime[path.extname(clinicalPath)] });
    });
    try {
      await open(pendingPage);
      const mnemonicTime = (mnemonic.start + mnemonic.end) / 2;
      await assertAt(pendingPage, lesson, mnemonicTime, 'before pending clinical image');
      await seek(pendingPage, (clinical.start + clinical.end) / 2);
      await Promise.race([requestStarted, new Promise((_, reject) => setTimeout(() => reject(new Error('Expected image request did not start')), 5000))]);
      await frames(pendingPage, 3);
      const pending = await pendingPage.evaluate(() => {
        const pointer = document.querySelector('#teaching-pointer');
        return {
          loaded: document.querySelector('#lesson-image').complete,
          pointerVisible: !!pointer && !pointer.hidden && getComputedStyle(pointer).display !== 'none' && Number(getComputedStyle(pointer).opacity) > 0,
          spotlightOpacity: Number(getComputedStyle(document.querySelector('#spotlight')).opacity),
        };
      });
      assert.equal(pending.loaded, false, 'Delayed image unexpectedly finished loading');
      assert.equal(pending.pointerVisible, false, 'Stale pointer points at an image that is not ready');
      assert.equal(pending.spotlightOpacity, 0, 'Stale spotlight remains visible during image load');
      // Return to the previous bitmap before the delayed response arrives.
      await assertAt(pendingPage, lesson, mnemonicTime, 'backward seek while clinical image pending');
      release();
      await frames(pendingPage, 8);
      await assertCurrent(pendingPage, lesson, mnemonicTime, 'after stale clinical response');
      await assertAt(pendingPage, lesson, (clinical.start + clinical.end) / 2, 'clinical image after decode');
    } finally {
      release();
      await pendingContext.close();
    }
  });

  await check('null targets and targets authored for a different image remain unpointed', async () => {
    for (const variant of ['null', 'mismatched-image']) {
      const fixture = JSON.parse(JSON.stringify(lessons));
      const guidance = fixture[0].visualGuidance;
      const selectedCue = guidance.cues.find(item => item.id === cue.id);
      if (variant === 'null') selectedCue.targetId = null;
      else {
        const target = guidance.targets[selectedCue.targetId];
        target.image = Object.keys(guidance.images).find(image => image !== target.image);
        assert.ok(target.image, 'Mismatched-image regression requires a second calibrated bitmap');
      }
      const { context: invalidContext, page: invalidPage } = await newPage();
      await invalidPage.route('**/data/lessons.json', route => route.fulfill({ json: fixture }));
      try {
        await open(invalidPage);
        await seek(invalidPage, cueTime);
        await until(invalidPage, () => {
          const picture = document.querySelector('#lesson-image');
          return picture.complete && picture.naturalWidth > 0;
        });
        await frames(invalidPage, 3);
        const state = await invalidPage.evaluate(() => {
          const pointer = document.querySelector('#teaching-pointer');
          return {
            pointerVisible: !!pointer && !pointer.hidden && getComputedStyle(pointer).display !== 'none' && Number(getComputedStyle(pointer).opacity) > 0,
            spotlightOpacity: Number(getComputedStyle(document.querySelector('#spotlight')).opacity),
          };
        });
        assert.equal(state.pointerVisible, false, variant + ' target still renders an arrow');
        assert.equal(state.spotlightOpacity, 0, variant + ' target still renders a spotlight');
      } finally {
        await invalidContext.close();
      }
    }
  });

  await check('no uncaught player errors under the native-equivalent content policy', async () => assert.deepEqual(errors, []));
  await browser.close(); browser = null;
  await new Promise(resolve => server.close(resolve));
  const report = {
    passed: results.length, tests: results, geometrySamples: geometry.length,
    maxTipErrorPx: Math.max(0, ...geometry.map(item => item.tipError)),
    maxSpotlightErrorPx: Math.max(0, ...geometry.map(item => item.spotError)),
    maxArrowEndpointErrorPx: Math.max(0, ...geometry.map(item => item.shaftError)),
    viewports: sizes, physicalAndroidTested: false, samples: geometry,
  };
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(`Guidance browser checks passed: ${results.length}; ${geometry.length} independent geometric samples.`);
}

main().catch(async error => {
  console.error(error);
  fs.mkdirSync(output, { recursive: true });
  fs.writeFileSync(path.join(output, 'failure.json'), JSON.stringify({ error: error.message, stack: error.stack, passed: results, samples: geometry, pageErrors: errors }, null, 2) + '\n');
  if (browser) await browser.close().catch(() => {});
  server.close();
  process.exitCode = 1;
});
