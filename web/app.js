/* InstaAnki: the interface runs entirely on this device. */
(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const L = window.Learning;
  const native = window.AndroidNative || null;
  const audio = $('#lesson-audio');
  const SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2];
  const CATALOG_URL = 'https://raw.githubusercontent.com/blsmohamme972-lab/InstaAnki/main/content/catalog.json';
  const app = {
    lessons: [], books: [], feed: [], index: 0, tab: 'feed', feedMode: 'all', specialty: '', tag: '',
    modal: null, previousFocus: null, resumeOnClose: false, captions: true, endHandled: false,
    frame: 0, lastClock: 0, exposure: 0, lastScene: '', currentImage: '', catalog: null,
    catalogCheckedAt: null, downloading: false, info: { version: '0.1.0', versionCode: 1 }, toastTimer: 0,
    bypassNextRecall: null, bypassEntryRecall: false, entryWasDue: false,
  };
  const icons = {
    arrow: '<svg viewBox="0 0 24 24"><path d="m9 5 7 7-7 7"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg>',
    recall: '<svg viewBox="0 0 24 24"><path d="M4 10a8 8 0 1 1 .6 6M4 4v6h6M12 7v5l3 2"/></svg>',
    book: '<svg viewBox="0 0 24 24"><path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-2H4zM13 7a3 3 0 0 1 3-3h5v15h-4a4 4 0 0 0-4 2"/></svg>',
    lock: '<svg viewBox="0 0 24 24"><rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>',
    play: '<svg viewBox="0 0 24 24"><path d="m8 5 11 7-11 7Z" fill="currentColor" stroke="none"/></svg>',
    pause: '<svg viewBox="0 0 24 24"><path d="M8 5v14M16 5v14" stroke-width="3.5"/></svg>',
  };
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clamp = (n, min, max) => Math.max(min, Math.min(max, Number(n) || 0));
  const settings = () => L?.state?.settings || {};
  const current = () => app.feed[app.index] || null;
  const byId = id => app.lessons.find(lesson => lesson.id === id);
  const time = seconds => { const n = Math.max(0, Math.floor(Number(seconds) || 0)); return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}`; };
  const amount = bytes => bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.ceil((bytes || 0) / 1024)} KB`;
  const dateLabel = value => { const date = new Date(value); return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(date) : 'Scheduled automatically'; };
  function asset(path, base) {
    if (!path) return '';
    try {
      const url = new URL(String(path).replace(/^\/(?!\/)/, ''), base || document.baseURI);
      if (url.protocol === 'https:' || (url.protocol === 'http:' && url.origin === location.origin)) return url.href;
    } catch (_) { /* Invalid package paths never become executable URLs. */ }
    return '';
  }
  function external(url) {
    try {
      const target = new URL(url);
      if (target.protocol !== 'https:') throw new Error('Only HTTPS source links are supported.');
      if (native?.openExternal) native.openExternal(target.href);
      else window.open(target.href, '_blank', 'noopener,noreferrer');
    } catch (error) { toast(error.message || 'This source link is unavailable.'); }
  }
  function toast(message) {
    const box = $('#toast'); clearTimeout(app.toastTimer); box.textContent = message; box.hidden = false;
    app.toastTimer = setTimeout(() => { box.hidden = true; }, 4300);
  }
  function syncWarning() {
    const warning = $('#state-warning');
    warning.hidden = !L?.loadError;
    warning.textContent = L?.loadError ? 'Your saved learning history could not be read. Restore a backup in Settings before recording new progress.' : '';
  }
  function syncIndicators() {
    if (!L) return;
    const due = L.due(app.lessons).length;
    $('#nav-review-badge').textContent = due > 99 ? '99+' : due;
    $('#nav-review-badge').hidden = due === 0;
    $('#feed-due-count').textContent = due;
    $('#feed-due-count').hidden = due === 0;
    const lesson = current();
    if (lesson) {
      const record = L.get(lesson.id);
      $('#like-button').setAttribute('aria-pressed', String(!!record.liked));
      $('#like-button').setAttribute('aria-label', record.liked ? 'Unsave lesson' : 'Save lesson');
      $('#like-button').querySelector('span:last-child').textContent = record.liked ? 'Saved' : 'Save';
      $('#feed-status').textContent = record.enrolledAt ? 'Added to spaced reviews' : 'Recall, woven into your feed';
    }
    document.body.classList.toggle('reduced-motion', !!settings().reduceMotion);
  }
  function rebuildFeed(preferredId) {
    pauseAudio();
    let lessons = app.feedMode === 'due' ? L.due(app.lessons) : app.feedMode === 'saved' ? app.lessons.filter(x => L.get(x.id).liked) : L.getFeed(app.lessons);
    if (app.specialty) lessons = lessons.filter(x => x.specialty === app.specialty || x.primarySpecialtyId === app.specialty);
    if (app.tag) lessons = lessons.filter(x => x.tags?.some(t => t.id === app.tag));
    if (preferredId && app.bypassNextRecall === preferredId && !lessons.some(x => x.id === preferredId)) {
      const explicitlyChosen = byId(preferredId); if (explicitlyChosen) lessons = [explicitlyChosen, ...lessons];
    }
    app.feed = lessons;
    app.index = Math.max(0, lessons.findIndex(x => x.id === preferredId));
    $('#filter-indicator').hidden = !app.specialty && !app.tag;
    $$('[data-feed]').forEach(button => button.classList.toggle('selected', button.dataset.feed === app.feedMode));
    if (!lessons.length) {
      pauseAudio(); $('#lesson-card').hidden = true; $('#feed-empty').hidden = false;
      const heading = app.feedMode === 'saved' ? 'Your saved collection' : app.feedMode === 'due' ? 'A little breathing room' : app.specialty || app.tag ? 'No lessons in this view' : 'Your gallery is ready to grow';
      const copy = app.feedMode === 'saved' ? 'Tap the heart on a lesson to keep it here. Your saved lessons stay on this device.' : app.feedMode === 'due' ? 'Nothing is due right now. Watch a new lesson, or practise a familiar one whenever you like.' : app.specialty || app.tag ? 'Try another specialty or clear the current filters.' : 'Import a lesson package from Settings to begin your learning collection.';
      $('#feed-empty').innerHTML = `<div class="empty-emblem">${app.feedMode === 'saved' ? icons.book : icons.recall}</div><h1>${esc(heading)}</h1><p>${esc(copy)}</p><button class="secondary-button empty-button" data-action="${app.specialty || app.tag ? 'clear-filters' : 'all-feed'}" type="button">${app.specialty || app.tag ? 'Clear filters' : 'Explore the feed'}</button>`;
      $('#quiz-now').disabled = true;
      return;
    }
    $('#lesson-card').hidden = false; $('#feed-empty').hidden = true; $('#quiz-now').disabled = false;
    setLesson(app.index, false);
  }
  function flushExposure() {
    const lesson = current();
    if (lesson && app.exposure > 0 && L && !L.loadError) { const elapsed = app.exposure; app.exposure = 0; L.expose(lesson.id, elapsed); }
    app.lastClock = 0;
  }
  function pauseAudio() { audio.pause(); flushExposure(); }
  function setLesson(index, shouldPlay = settings().autoPlay) {
    pauseAudio();
    app.index = clamp(index, 0, app.feed.length - 1);
    const lesson = current(); if (!lesson) return;
    app.bypassEntryRecall = app.bypassNextRecall === lesson.id;
    app.bypassNextRecall = null;
    const entryCard = L.get(lesson.id).card;
    app.entryWasDue = !!entryCard && new Date(entryCard.due).getTime() <= Date.now();
    app.endHandled = false; app.lastScene = ''; app.currentImage = ''; app.exposure = 0; app.lastClock = 0;
    $('#lesson-title').textContent = lesson.title;
    $('#lesson-specialty').textContent = lesson.specialty || 'Medical learning';
    $('#lesson-position').textContent = `${String(app.index + 1).padStart(2, '0')} / ${String(app.feed.length).padStart(2, '0')}`;
    $('#locus-label').textContent = lesson.locus ? `${lesson.locus.room || 'Memory gallery'} · ${lesson.locus.anchor || 'Recall anchor'}` : 'Your memory gallery';
    $('#lesson-tags').innerHTML = (lesson.tags || []).slice(0, 3).map(tag => `<span>${esc(tag.label)}</span>`).join('');
    $('#lesson-image').alt = `${lesson.title} — illustrated memory scene`;
    $('#lesson-caption').textContent = lesson.scenes?.[0]?.caption || 'Press play to enter the lesson.';
    audio.src = asset(lesson.audioUrl, lesson._baseUrl);
    audio.playbackRate = clamp(settings().speed || 1, .5, 2);
    audio.load();
    $('#seek').value = '0'; $('#seek').style.setProperty('--progress', '0%');
    $('#duration-time').textContent = time(lesson.durationSeconds);
    $('#current-time').textContent = '0:00'; $('#speed-button').textContent = `${audio.playbackRate}×`;
    paintFrame(); syncIndicators(); updatePlayButtons();
    if (maybeGateRecall(lesson)) return;
    if (shouldPlay && app.tab === 'feed' && !app.modal) playAudio(false);
  }
  function maybeGateRecall(lesson) {
    if (!lesson || app.tab !== 'feed' || app.modal || app.bypassEntryRecall || !app.entryWasDue) return false;
    const card = L.get(lesson.id).card;
    if (card && new Date(card.due).getTime() <= Date.now()) { showQuiz(lesson, 'review', 'feed'); return true; }
    return false;
  }
  async function playAudio(reportError = true) {
    if (!current() || app.modal || maybeGateRecall(current())) return;
    if (audio.ended || (Number.isFinite(audio.duration) && audio.currentTime >= audio.duration - .1)) { audio.currentTime = 0; app.endHandled = false; }
    try { await audio.play(); }
    catch (error) { updatePlayButtons(); if (reportError && error.name !== 'NotAllowedError') toast('The audio could not start. Try again or check this lesson package.'); }
  }
  function updatePlayButtons() {
    const playing = !audio.paused && !audio.ended;
    $('#visual-stage').classList.toggle('is-playing', playing);
    $('#play-button').innerHTML = playing ? icons.pause : icons.play;
    $('#play-button').setAttribute('aria-label', playing ? 'Pause lesson' : 'Play lesson');
    $('#center-play').hidden = playing || !!app.modal;
  }
  function nextLesson(direction = 1) {
    if (!app.feed.length) return;
    pauseAudio();
    if (app.feedMode === 'due') {
      const preferred = app.feed[(app.index + direction + app.feed.length) % app.feed.length]?.id;
      rebuildFeed(preferred); if (current() && settings().autoPlay) playAudio(false); return;
    }
    if (app.feed.length === 1) { toast('This is the only lesson in the current view. Change filters to explore more.'); return; }
    setLesson((app.index + direction + app.feed.length) % app.feed.length);
  }
  function paintFrame() {
    const lesson = current(); if (!lesson) return;
    const now = audio.currentTime || 0;
    const duration = Number.isFinite(audio.duration) ? audio.duration : Number(lesson.durationSeconds) || 1;
    $('#current-time').textContent = time(now); $('#duration-time').textContent = time(duration);
    if (document.activeElement !== $('#seek')) $('#seek').value = String(now / duration * 100);
    $('#seek').style.setProperty('--progress', `${clamp(now / duration * 100, 0, 100)}%`);
    $('#seek').setAttribute('aria-valuetext', `${time(now)} of ${time(duration)}`);
    const scene = lesson.scenes?.find(item => now >= item.start && now < item.end) || lesson.scenes?.[lesson.scenes.length - 1] || {};
    const outroStart = Number(lesson.realImageOutro?.start);
    const isOutro = Number.isFinite(outroStart) && now >= outroStart && !!lesson.realImages?.length;
    const isReal = !!lesson.realImages?.length && (isOutro || scene.kind === 'clinical');
    const clinicalImage = lesson.realImages?.find(item => item.url === scene.image) || lesson.realImages?.[0];
    const image = isOutro ? lesson.realImages[0].url : scene.image || lesson.poster;
    const url = asset(image, lesson._baseUrl);
    if (url !== app.currentImage) { app.currentImage = url; $('#lesson-image').src = url; }
    $('#visual-stage').classList.toggle('is-real', !!isReal); $('#real-image-badge').hidden = !isReal;
    $('#lesson-image').alt = isReal ? clinicalImage.title : `${lesson.title} — illustrated memory scene`;
    if (isReal) $('#real-image-badge > span:nth-child(2)').textContent = `REAL CLINICAL IMAGE · ${clinicalImage.license || 'SOURCE'}`;
    const sceneKey = `${scene.id || ''}:${!!isReal}:${isOutro}`;
    if (sceneKey !== app.lastScene) {
      app.lastScene = sceneKey;
      $('#lesson-caption').textContent = isOutro ? clinicalImage.caption || clinicalImage.title : scene.caption || clinicalImage?.caption || '';
      $('#scene-heading').textContent = scene.caption || '';
    }
    $('#scene-heading').classList.toggle('visible', !isReal && !!scene.caption && app.captions);
    $('#lesson-caption').hidden = !app.captions;
    const elapsed = Math.max(0, Number(scene.end) - Number(scene.start));
    const position = elapsed ? clamp((now - Number(scene.start)) / elapsed, 0, 1) : 0;
    const eased = position * position * (3 - 2 * position);
    const from = scene.camera?.from || { x: .5, y: .5, scale: 1 };
    const to = scene.camera?.to || from;
    const frame = $('#visual-stage'); const imageElement = $('#lesson-image');
    const frameWidth = frame.clientWidth; const frameHeight = frame.clientHeight;
    const fit = Math.min(frameWidth / (imageElement.naturalWidth || frameWidth), frameHeight / (imageElement.naturalHeight || frameHeight));
    const imageWidth = (imageElement.naturalWidth || frameWidth) * fit;
    const imageHeight = (imageElement.naturalHeight || frameHeight) * fit;
    let scale = 1, panX = 0, panY = 0;
    if (!isReal && !settings().reduceMotion) {
      const x = clamp(Number(from.x ?? .5) + (Number(to.x ?? .5) - Number(from.x ?? .5)) * eased, 0, 1);
      const y = clamp(Number(from.y ?? .5) + (Number(to.y ?? .5) - Number(from.y ?? .5)) * eased, 0, 1);
      scale = clamp(Number(from.scale || 1) + (Number(to.scale || 1) - Number(from.scale || 1)) * eased, 1, 2.2);
      const maxX = Math.max(0, (imageWidth * scale - frameWidth) / 2);
      const maxY = Math.max(0, (imageHeight * scale - frameHeight) / 2);
      panX = Math.max(-maxX, Math.min(maxX, (.5 - x) * imageWidth * scale));
      panY = Math.max(-maxY, Math.min(maxY, (.5 - y) * imageHeight * scale));
      $('#camera-layer').style.transformOrigin = '50% 50%';
      $('#camera-layer').style.transform = `translate(${panX}px, ${panY}px) scale(${scale})`;
    } else $('#camera-layer').style.transform = 'none';
    const spot = scene.spotlight;
    const focusX = frameWidth / 2 + (clamp(spot?.x ?? .5, 0, 1) - .5) * imageWidth * scale + panX;
    const focusY = frameHeight / 2 + (clamp(spot?.y ?? .5, 0, 1) - .5) * imageHeight * scale + panY;
    // On shorter phones, an upper caption can cover a cue near the top of the
    // picture (for example, the four locks). Move it away from that focal point.
    $('#scene-heading').classList.toggle('caption-low', !isReal && !!spot && focusY < 80 + $('#scene-heading').offsetHeight);
    if (spot && !isReal && !settings().reduceMotion && !audio.paused) {
      const radius = clamp(spot.r || .2, .06, .6) * Math.min(imageWidth, imageHeight) * scale;
      $('#spotlight').style.background = `radial-gradient(circle at ${focusX}px ${focusY}px, transparent 0, transparent ${radius * .48}px, rgba(0,8,15,.13) ${radius}px, rgba(0,8,15,.2) 100%)`;
      $('#spotlight').style.opacity = '1';
    } else $('#spotlight').style.opacity = '0';
  }
  function tick(clock) {
    if (!audio.paused && !audio.ended && !audio.seeking && audio.readyState >= 3 && document.visibilityState === 'visible' && app.tab === 'feed' && !app.modal) {
      if (app.lastClock) app.exposure += Math.min(.5, Math.max(0, (clock - app.lastClock) / 1000));
      app.lastClock = clock;
      if (app.exposure >= 1) { const amount = app.exposure; app.exposure = 0; if (!L.loadError) L.expose(current().id, amount); }
      paintFrame();
    } else app.lastClock = 0;
    app.frame = requestAnimationFrame(tick);
  }
  function showTab(tab, resume = true) {
    if (!['feed', 'publications', 'review', 'insights', 'settings'].includes(tab)) return;
    const previousTab = app.tab;
    if (tab !== 'feed') pauseAudio();
    app.tab = tab;
    $$('.screen').forEach(screen => { screen.hidden = screen.id !== `screen-${tab}`; });
    $$('[data-tab]').forEach(button => { button.classList.toggle('active', button.dataset.tab === tab); if (button.dataset.tab === tab) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current'); });
    if (tab === 'publications') renderPublications();
    if (tab === 'review') renderReview();
    if (tab === 'insights') renderInsights();
    if (tab === 'settings') renderSettings();
    if (tab === 'feed') {
      if (previousTab !== 'feed' && resume && current()) {
        const card = L.get(current().id).card;
        app.entryWasDue = !!card && new Date(card.due).getTime() <= Date.now();
        app.bypassEntryRecall = false;
      }
      syncIndicators(); if (resume && current() && !maybeGateRecall(current()) && settings().autoPlay && !app.modal) playAudio(false);
    }
  }
  function cover(book) {
    return `<div class="book-cover"><span class="cover-kicker">PUBLICATION</span><span class="cover-fallback-title">${esc(book.title)}</span><span class="cover-author">${esc(book.author)}</span>${book.coverUrl ? `<img src="${esc(asset(book.coverUrl, book._baseUrl))}" alt="Cover of ${esc(book.title)}" data-cover>` : ''}</div>`;
  }
  function bindCoverFallbacks() { $$('img[data-cover]').forEach(img => { img.addEventListener('error', () => { img.hidden = true; }, { once: true }); if (img.complete && !img.naturalWidth) img.hidden = true; }); }
  function refreshProductionProgress() {
    for (const book of app.books) {
      const total = Number(book.totalQuestions);
      if (!Number.isInteger(total) || total < 1) continue;
      const questions = new Map((book.questions || []).map(question => [Number(question.number), { ...question }]));
      const completed = new Set((book.completedQuestionNumbers || []).map(Number).filter(number => Number.isInteger(number) && number > 0 && number <= total));
      for (const [number, question] of questions) if (question.status === 'produced' && number > 0 && number <= total) completed.add(number);
      for (const lesson of app.lessons) {
        const number = Number(lesson.source?.questionNumber);
        if (lesson.source?.bookId !== book.id || !Number.isInteger(number) || number < 1 || number > total) continue;
        completed.add(number);
        questions.set(number, { ...questions.get(number), number, status: 'produced', lessonId: lesson.id });
      }
      book.questions = Array.from({ length: total }, (_, index) => {
        const number = index + 1;
        return { number, status: completed.has(number) ? 'produced' : 'ready', lessonId: null, ...questions.get(number) };
      });
      book.completedQuestionNumbers = [...completed].sort((a, b) => a - b);
      book.completedVideos = completed.size;
      book.progress = completed.size / total;
      book.nextQuestionNumber = book.questions.find(question => question.status !== 'produced')?.number || null;
    }
  }
  function renderPublications() {
    refreshProductionProgress();
    const produced = app.books.reduce((n, book) => n + Number(book.completedVideos || 0), 0);
    const total = app.books.reduce((n, book) => n + Number(book.totalQuestions || 0), 0);
    $('#screen-publications').innerHTML = `<span class="page-eyebrow">THE SOURCE COLLECTION</span><h1 class="page-heading" id="publications-heading">From page to memory.</h1><p class="page-intro">Your publications, transformed one learning objective at a time.</p>${app.books.map(book => `<button class="surface-card publication-card" type="button" data-book="${esc(book.id)}" aria-label="Open ${esc(book.title)}"><div class="book-top">${cover(book)}<div class="book-details"><div class="book-year">${esc(book.year || '')} · PERSONAL COLLECTION</div><h2>${esc(book.title)}</h2><p>${esc(book.author)}<br>${Number(book.totalQuestions) || 0} source questions</p></div></div><div class="book-progress-head"><span>Lessons produced</span><b>${Number(book.completedVideos) || 0} / ${Number(book.totalQuestions) || 0}</b></div><div class="progress-track"><div class="progress-fill" style="width:${clamp((Number(book.completedVideos) || 0) / Math.max(1, Number(book.totalQuestions)) * 100, 0, 100)}%"></div></div><div class="book-foot"><span>${esc(book.sourceStatus || 'Source collection')} · ${clamp((Number(book.completedVideos) || 0) / Math.max(1, Number(book.totalQuestions)) * 100, 0, 100).toFixed(1)}%</span>${icons.arrow}</div></button>`).join('') || '<p class="empty-copy">Your publication collection is empty. Import a source-linked lesson package to begin.</p>'}<div class="library-summary"><div class="mini-stat"><b>${produced}</b><span>Lessons produced</span></div><div class="mini-stat"><b>${Math.max(0, total - produced)}</b><span>Questions still to produce</span></div></div><div class="inline-note">${icons.lock}<span>Production progress belongs to your source collection. Your personal review progress is tracked separately in Insights.</span></div><button class="secondary-button full-width" type="button" data-action="import-pack">Import a lesson package ${icons.arrow}</button>`;
    bindCoverFallbacks();
  }
  function lessonRow(lesson, action, suffix) {
    return `<button class="lesson-row" type="button" data-${action}="${esc(lesson.id)}"><img class="lesson-thumb" src="${esc(asset(lesson.poster, lesson._baseUrl))}" alt=""><span class="lesson-row-copy"><h3>${esc(lesson.title)}</h3><p>${esc(lesson.specialty || 'Medical learning')}${suffix ? ` · ${esc(suffix)}` : ''}</p></span><span class="row-arrow">${icons.arrow}</span></button>`;
  }
  function renderReview() {
    const due = L.due(app.lessons);
    const started = app.lessons.filter(lesson => L.get(lesson.id).enrolledAt);
    $('#screen-review').innerHTML = `<span class="page-eyebrow">A MOMENT TO REMEMBER</span><h1 class="page-heading" id="review-heading">Make it stay.</h1><p class="page-intro">Start with the question. Let your memory do the work before the explanation.</p><div class="surface-card review-hero"><span class="hero-orbit" aria-hidden="true"></span><div class="hero-count">${due.length}</div><p class="hero-subtitle">${due.length === 1 ? 'lesson ready for recall' : 'lessons ready for recall'}</p><p class="hero-detail">${due.length ? 'These are due now, according to your review history.' : started.length ? 'Your next reviews will appear here when they are due.' : 'Your queue begins after you spend time with a lesson.'}</p><button class="primary-button full-width" type="button" data-action="${due.length ? 'start-review' : 'go-feed'}">${due.length ? 'Begin recall' : 'Explore your lessons'} ${icons.arrow}</button></div>${due.length ? `<div class="section-title"><h2>Due now</h2><span>${due.length} ${due.length === 1 ? 'lesson' : 'lessons'}</span></div><div class="lesson-list">${due.map(x => lessonRow(x, 'review-lesson', 'Ready to recall')).join('')}</div>` : ''}<div class="section-title"><h2>Practise anytime</h2><span>No schedule changes</span></div><div class="lesson-list">${app.lessons.map(x => lessonRow(x, 'practice-lesson', 'Quick question')).join('')}</div><div class="inline-note">${icons.recall}<span>Watching adds a lesson to your collection. Answers guide its review schedule. A replay or a like never counts as a correct answer.</span></div>`;
  }
  function renderInsights() {
    const stats = L.stats();
    const specialties = [...new Set(app.lessons.map(x => x.specialty || 'Medical learning'))];
    const recent = [...(L.state.reviews || [])].reverse().slice(0, 5);
    const minutes = Math.floor(Number(stats.watchedSeconds || 0) / 60);
    const accuracy = Number.isFinite(stats.accuracy) ? stats.accuracy : 0;
    $('#screen-insights').innerHTML = `<span class="page-eyebrow">YOUR OWN EVIDENCE</span><h1 class="page-heading" id="insights-heading">Small moments add up.</h1><p class="page-intro">A clear view of the learning you have actually done, saved only on this device.</p><div class="metric-grid"><div class="metric-card accent"><span class="metric-label">Scheduled recalls</span><b class="metric-value">${stats.reviewCount || 0}</b><span class="metric-footnote">Practice checks tracked separately</span></div><div class="metric-card"><span class="metric-label">Correct answers</span><b class="metric-value">${stats.reviewCount ? Math.round(accuracy) + '<span class="metric-unit">%</span>' : '—'}</b><span class="metric-footnote">${stats.reviewCount ? `${stats.correctCount || 0} of ${stats.reviewCount}` : 'Answer a question to begin'}</span></div><div class="metric-card"><span class="metric-label">Focused watch time</span><b class="metric-value">${minutes}<span class="metric-unit">min</span></b><span class="metric-footnote">${time(stats.watchedSeconds || 0)} played in the foreground</span></div><div class="metric-card"><span class="metric-label">Learning streak</span><b class="metric-value">${stats.streak || 0}<span class="metric-unit">${stats.streak === 1 ? 'day' : 'days'}</span></b><span class="metric-footnote">Days with scheduled recall</span></div></div><div class="section-title"><h2>Across your specialties</h2><span>Lessons started</span></div><div class="surface-card">${specialties.map(name => { const all = app.lessons.filter(x => (x.specialty || 'Medical learning') === name); const enrolled = all.filter(x => L.get(x.id).enrolledAt).length; return `<div class="specialty-row"><div class="specialty-head">${esc(name)}<span>${enrolled} / ${all.length}</span></div><div class="progress-track"><div class="progress-fill" style="width:${enrolled / Math.max(1, all.length) * 100}%"></div></div></div>`; }).join('') || '<p class="empty-copy">Import lessons to see your specialties here.</p>'}</div><div class="section-title"><h2>Recent recall</h2><span>${(L.state.reviews || []).length} recorded</span></div>${recent.length ? `<div class="surface-card">${recent.map(review => { const lesson = byId(review.lessonId || review.id); const when = review.at || review.timestamp || review.reviewedAt; return `<div class="recent-row"><span class="answer-dot ${review.correct ? '' : 'missed'}">${review.correct ? '✓' : '↻'}</span><div><h3>${esc(lesson?.title || 'Lesson recall')}</h3><p>${review.correct ? 'Correct recall' : 'Revisit the explanation'}${when ? ` · ${esc(dateLabel(when))}` : ''}${review.practice ? ' · Practice' : ''}</p></div></div>`; }).join('')}</div>` : '<p class="empty-copy">Answer a question to begin your private recall history.</p>'}`;
  }
  function toggleRow(key, title, description) {
    return `<div class="setting-row"><div class="setting-copy"><h3>${esc(title)}</h3><p>${esc(description)}</p></div><label class="switch"><input type="checkbox" data-setting="${key}" aria-label="${esc(title)}" ${settings()[key] ? 'checked' : ''}><span class="switch-track"></span></label></div>`;
  }
  function settingsAction(action, title, description, value = '') {
    return `<button class="setting-row" type="button" data-action="${action}"><span class="setting-copy"><h3>${esc(title)}</h3>${description ? `<p>${esc(description)}</p>` : ''}</span>${value ? `<span class="setting-value">${esc(value)}</span>` : icons.arrow}</button>`;
  }
  function renderSettings() {
    $('#screen-settings').innerHTML = `<span class="page-eyebrow">MAKE IT YOURS</span><h1 class="page-heading" id="settings-heading">Your learning rhythm.</h1><p class="page-intro">Tune the pace. Keep control of your collection.</p><section class="setting-section"><h2>Spaced recall</h2><div class="settings-card">${settingsAction('retention', 'Target recall', 'Higher targets generally mean more reviews.', `${Math.round((settings().retention || .9) * 100)}%`)}${settingsAction('new-limit', 'New lessons each day', 'A comfortable limit for the For you feed.', String(settings().newPerDay ?? 10))}</div></section><section class="setting-section"><h2>Playback</h2><div class="settings-card">${settingsAction('speed', 'Playback speed', 'Visuals follow the narration at every speed.', `${settings().speed || 1}×`)}${toggleRow('autoPlay', 'Autoplay lessons', 'Start narration when you enter a lesson.')}${toggleRow('reduceMotion', 'Reduce camera motion', 'Keep the memory scene steady.')}</div></section><section class="setting-section"><h2>Collection & updates</h2><div class="settings-card">${settingsAction('import-pack', 'Import lesson package', 'Add a ZIP from your device.')}${settingsAction('check-updates', 'Check for updates', app.catalogCheckedAt ? `Last checked ${dateLabel(app.catalogCheckedAt)}` : 'Find new content packages and app releases.')}${toggleRow('autoCheckUpdates', 'Check when opening', 'Check the catalog when a connection is available.')}</div></section><section class="setting-section"><h2>Your data</h2><div class="settings-card">${settingsAction('export-backup', 'Export learning backup', 'Save reviews, private notes and preferences.')}${settingsAction('import-backup', 'Restore learning backup', 'Restore a saved snapshot without removing media.')}${settingsAction('local-info', 'Stored on this device', `${app.lessons.length} lessons · No account required`)}</div></section><section class="setting-section"><h2>About</h2><div class="settings-card">${settingsAction('licenses', 'Open-source licenses', 'App credits and licenses, available offline.')}</div></section><p class="app-version">InstaAnki ${esc(app.info.version || '0.1.0')} · Personal learning<br>English · ${native ? 'Android' : 'Browser preview'}</p>`;
  }
  function openModal(kind, title, eyebrow, html, extra = {}) {
    const wasOpen = !!app.modal;
    if (!wasOpen) { app.previousFocus = document.activeElement; app.resumeOnClose = !audio.paused && kind !== 'quiz'; }
    pauseAudio();
    app.modal = { kind, ...extra };
    $('#modal-title').textContent = title; $('#modal-eyebrow').textContent = eyebrow || '';
    $('#modal-body').innerHTML = html; $('#modal-backdrop').hidden = false; $('#app-shell').inert = true;
    document.body.classList.add('no-scroll');
    requestAnimationFrame(() => { const focus = $('#modal-body [autofocus]') || $('#modal-sheet'); focus.focus(); });
    updatePlayButtons();
  }
  function closeModal(resume = true) {
    if (!app.modal) return;
    const shouldResume = resume && app.resumeOnClose;
    app.modal = null; app.resumeOnClose = false;
    $('#modal-backdrop').hidden = true; $('#app-shell').inert = false; document.body.classList.remove('no-scroll');
    if (app.previousFocus?.isConnected) app.previousFocus.focus({ preventScroll: true });
    updatePlayButtons();
    if (shouldResume && app.tab === 'feed') playAudio(false);
  }
  function showSpeed() {
    openModal('speed', 'Set your pace.', 'PLAYBACK', `<p class="modal-intro">Narration, camera movements and captions stay together. Your choice becomes the default for each lesson.</p><div class="choice-grid">${SPEEDS.map(speed => `<button type="button" class="choice-button ${Number(settings().speed || 1) === speed ? 'selected' : ''}" data-speed="${speed}">${speed}×</button>`).join('')}</div>`);
  }
  function showFilters() {
    const specialties = [...new Set(app.lessons.map(x => x.specialty).filter(Boolean))];
    const tags = [...new Map(app.lessons.flatMap(x => x.tags || []).map(t => [t.id, t])).values()];
    openModal('filters', 'Choose your focus.', 'YOUR GALLERY', `<p class="modal-intro">Keep the feed broad, or explore one specialty or topic.</p><h3>Specialty</h3><div class="choice-list"><button type="button" class="choice-button ${!app.specialty ? 'selected' : ''}" data-specialty="">All specialties<span class="count-label">${app.lessons.length}</span></button>${specialties.map(name => `<button type="button" class="choice-button ${app.specialty === name ? 'selected' : ''}" data-specialty="${esc(name)}">${esc(name)}<span class="count-label">${app.lessons.filter(x => x.specialty === name).length}</span></button>`).join('')}</div><h3>Topic</h3><div class="choice-list"><button type="button" class="choice-button ${!app.tag ? 'selected' : ''}" data-topic="">All topics</button>${tags.map(tag => `<button type="button" class="choice-button ${app.tag === tag.id ? 'selected' : ''}" data-topic="${esc(tag.id)}">${esc(tag.label)}</button>`).join('')}</div><button class="quiet-button full-width" type="button" data-action="clear-filters">Clear all filters</button>`);
  }
  function showNote() {
    const lesson = current(); if (!lesson) return;
    openModal('note', 'A note to your future self.', 'PRIVATE NOTES', `<p class="modal-intro">${esc(lesson.title)}</p><label class="field-label" for="note-input">Your note</label><textarea class="textarea" id="note-input" maxlength="10000" placeholder="What would help you remember this?" autofocus>${esc(L.get(lesson.id).note || '')}</textarea><p class="field-hint">This note stays on this device and is included in your learning backup.</p><button class="primary-button full-width" type="button" data-action="save-note" style="margin-top:18px">Save note</button>`, { lessonId: lesson.id });
  }
  function showTranscript() {
    const lesson = current(); if (!lesson) return;
    openModal('transcript', 'Read along.', 'CAPTIONS & TRANSCRIPT', `<div class="setting-row captions-setting"><div class="setting-copy"><h3>Show caption headlines</h3><p>Keep the key idea visible over the scene.</p></div><label class="switch"><input type="checkbox" data-captions aria-label="Show caption headlines" ${app.captions ? 'checked' : ''}><span class="switch-track"></span></label></div><p class="modal-intro">Tap a passage to return to that moment in the lesson.</p>${(lesson.scenes || []).map(scene => `<button type="button" class="transcript-scene" data-seek-scene="${Number(scene.start) || 0}"><small>${time(scene.start)} — ${time(scene.end)}</small><strong>${esc(scene.caption || 'Narration')}</strong><p>${esc(scene.transcript || scene.caption || '')}</p></button>`).join('')}`);
  }
  function imageCredit(image, base) {
    return `<div class="source-block"><h3>${esc(image.title || 'Clinical image')}</h3><img class="source-image" src="${esc(asset(image.url, base))}" alt="${esc(image.title || 'Clinical image')}"><p>${esc(image.caption || '')}</p>${image.displayNotes ? `<p style="margin-top:8px">${esc(image.displayNotes)}</p>` : ''}<span class="license-pill">${esc(image.license || 'See source license')}</span><p>${esc(image.attribution || image.author || '')}</p>${image.sourceUrl ? `<a href="${esc(image.sourceUrl)}" data-external>View original source ↗</a>` : ''}${image.licenseUrl ? ` <a href="${esc(image.licenseUrl)}" data-external>Read license ↗</a>` : ''}</div>`;
  }
  function showSource(imagesOnly = false) {
    const lesson = current(); if (!lesson) return;
    const source = lesson.source || {};
    const pages = Array.isArray(source.answerPages) ? source.answerPages.join(', ') : source.answerPages;
    const symbols = (lesson.mnemonicSymbols || []).map(item => `<div><dt>${esc(item.symbol)}</dt><dd>${esc(item.meaning)}</dd></div>`).join('');
    const corroboration = (source.corroboratingSources || []).map(reference => `<div class="source-block"><h3>${esc(reference.title)}</h3><p>${esc(reference.supports || '')}</p>${reference.doi ? `<p style="margin-top:7px">DOI: ${esc(reference.doi)}</p>` : ''}${reference.url ? `<a href="${esc(reference.url)}" data-external>Read supporting reference ↗</a>` : ''}</div>`).join('');
    const lessonSources = `<div class="source-block"><h3>${esc(source.bookTitle || 'Source-linked lesson')}</h3><p>${source.questionNumber ? `Question ${esc(source.questionNumber)}` : ''}${source.page ? ` · Page ${esc(source.page)}` : ''}${pages ? `<br>Answer pages ${esc(pages)}` : ''}</p>${source.verificationNote ? `<p style="margin-top:10px">${esc(source.verificationNote)}</p>` : ''}</div><div class="source-block"><h3>The memory scene</h3><p>The illustrated scene is a visual memory cue. The clinical images below are real, published examples with their own source credits.</p>${lesson.locus ? `<p style="margin-top:8px">Memory location: ${esc(lesson.locus.room)} · ${esc(lesson.locus.anchor)}</p>` : ''}${symbols ? `<dl class="symbol-map">${symbols}</dl>` : ''}</div>${corroboration}`;
    openModal('source', imagesOnly ? 'The real-world view.' : 'Trace it to the source.', imagesOnly ? 'IMAGE CREDITS' : 'LESSON REFERENCES', `${imagesOnly ? '' : lessonSources}${(lesson.realImages || []).map(image => imageCredit(image, lesson._baseUrl)).join('')}`);
  }
  function showBook(id) {
    refreshProductionProgress();
    const book = app.books.find(item => item.id === id); if (!book) return;
    const questions = book.questions || [];
    openModal('book', book.title, 'PUBLICATION PROGRESS', `<p class="modal-intro">${esc(book.author)} · ${esc(book.year)}<br>${Number(book.completedVideos) || 0} lessons produced from ${Number(book.totalQuestions) || 0} source questions.</p><div class="source-block"><h3>Next question to produce: ${book.nextQuestionNumber ? `Q${esc(book.nextQuestionNumber)}` : 'All source questions covered'}</h3><p>Completed questions are tracked individually. Skipped question numbers remain in the production plan.</p><button class="quiet-button" type="button" data-copy-plan="${esc(book.id)}">Copy the next-batch brief ↗</button></div><div class="question-key"><span><i class="done"></i>Produced</span><span><i></i>Not yet produced</span></div><div class="question-grid">${questions.map(q => `<button class="question-cell ${q.status === 'produced' ? 'produced' : q.status === 'needs_review' ? 'needs-review' : ''}" type="button" data-question="${q.number}" data-question-book="${esc(book.id)}" aria-label="Question ${q.number}, ${q.status === 'produced' ? 'lesson produced' : q.status === 'needs_review' ? 'source needs review' : 'not yet produced'}">${q.number}</button>`).join('')}</div>`, { bookId: id });
  }
  function quizMode(lesson, requested) {
    if (requested === 'practice') return 'practice';
    const record = L.get(lesson.id);
    const due = record.card?.due ? new Date(record.card.due).getTime() : 0;
    return due > Date.now() ? 'practice' : 'review';
  }
  function showQuiz(lesson, requested = 'review', origin = 'feed') {
    if (!lesson?.quiz?.options?.length) { toast('This lesson does not include a recall question.'); return; }
    const mode = quizMode(lesson, requested);
    const attemptId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    app.resumeOnClose = false;
    openModal('quiz', mode === 'practice' ? 'A quick memory check.' : 'What stayed with you?', mode === 'practice' ? 'PRACTICE · NO SCHEDULE CHANGE' : 'ACTIVE RECALL', '', { lessonId: lesson.id, mode, origin, attemptId, selected: -1, answered: false });
    app.resumeOnClose = false; renderQuiz();
  }
  function renderQuiz() {
    const state = app.modal; const lesson = byId(state?.lessonId); if (!lesson) return;
    const quiz = lesson.quiz;
    const result = state.result;
    $('#modal-body').innerHTML = `<p class="modal-intro">${esc(lesson.specialty || 'Medical learning')}${lesson.source?.questionNumber ? ` · Source Q${lesson.source.questionNumber}` : ''}</p><p class="quiz-prompt">${esc(quiz.prompt)}</p><div role="group" aria-label="Answer options">${quiz.options.map((option, index) => `<button type="button" class="quiz-option ${state.selected === index ? 'selected' : ''} ${state.answered && index === quiz.correctIndex ? 'correct' : ''} ${state.answered && state.selected === index && index !== quiz.correctIndex ? 'incorrect' : ''}" data-answer="${index}" aria-pressed="${state.selected === index}" ${state.answered ? 'disabled' : ''}><span class="option-letter">${String.fromCharCode(65 + index)}</span><span>${esc(option)}</span></button>`).join('')}</div>${state.answered ? `<div class="quiz-result ${result.correct ? '' : 'missed'}" role="status"><h3>${result.correct ? 'You remembered.' : 'Keep this connection.'}</h3><p>${esc(quiz.explanation)}</p><span class="schedule-note">${state.mode === 'practice' || result.practice || !result.scheduled ? 'Practice recorded. Your scheduled review has not moved.' : `Next review: ${esc(dateLabel(result.due))}`}</span></div><div class="quiz-actions"><button type="button" class="primary-button full-width" data-action="quiz-continue">${state.origin === 'review' ? 'Continue recall' : state.origin === 'practice' ? 'Done' : 'Continue the feed'} ${icons.arrow}</button><button type="button" class="quiet-button full-width" data-watch-lesson="${esc(lesson.id)}">Revisit the explanation</button></div>` : `<div class="quiz-actions"><button type="button" class="primary-button full-width" data-action="submit-answer" ${state.selected < 0 ? 'disabled' : ''}>Check my answer</button><button type="button" class="secondary-button full-width" data-action="dont-know">I don’t know yet</button><button type="button" class="quiet-button full-width" data-watch-lesson="${esc(lesson.id)}">Watch the explanation first</button></div>`}`;
  }
  function submitAnswer(dontKnow = false) {
    const state = app.modal; if (state?.kind !== 'quiz' || state.answered || (!dontKnow && state.selected < 0)) return;
    if (L.loadError) { toast('Restore your learning backup before recording an answer.'); return; }
    const lesson = byId(state.lessonId);
    try {
      if (dontKnow) { state.selected = -1; state.dontKnow = true; }
      state.result = L.grade(lesson.id, dontKnow ? false : state.selected === lesson.quiz.correctIndex, state.attemptId, state.mode);
      state.answered = true; renderQuiz(); syncIndicators();
      $('.quiz-result')?.scrollIntoView({ behavior: settings().reduceMotion ? 'auto' : 'smooth', block: 'nearest' });
    } catch (error) { toast(error.message || 'Your answer could not be saved.'); }
  }
  function continueQuiz() {
    const state = app.modal; if (!state) return;
    closeModal(false);
    if (state.origin === 'review') {
      const next = L.due(app.lessons).find(x => x.id !== state.lessonId);
      if (next) showQuiz(next, 'review', 'review'); else { showTab('review'); toast('Your due recall session is complete.'); }
    } else if (state.origin === 'feed') nextLesson();
    else { if (app.tab === 'review') renderReview(); if (app.tab === 'insights') renderInsights(); }
  }
  function watchLesson(id) {
    closeModal(false); app.feedMode = 'all'; app.specialty = ''; app.tag = '';
    app.bypassNextRecall = id;
    showTab('feed', false); rebuildFeed(id);
    if (!current() || current().id !== id) { const lesson = byId(id); if (lesson) { app.feed = [lesson, ...app.feed.filter(x => x.id !== id)]; app.index = 0; app.bypassNextRecall = id; setLesson(0, true); } }
    else playAudio(false);
  }
  function showLocalInfo() {
    openModal('local', 'Your collection is yours.', 'ON THIS DEVICE', `<div class="source-block"><h3>${native ? 'Native local storage' : 'Browser storage'}</h3><p>Your review history, saved lessons, notes and preferences are stored ${native ? 'in this app on your Android device' : 'in this browser'}. There is no account or automatic cloud sync.</p></div><div class="source-block"><h3>Keep a backup</h3><p>App updates preserve your learning data. Uninstalling the app or clearing its storage removes local data. Export a learning backup before changing devices.</p></div><div class="source-block"><h3>Content and learning progress</h3><p>Lesson packages contain media and questions. Your learning backup contains personal progress and notes. Replacing a lesson package does not reset your learning history.</p></div><button class="primary-button full-width" type="button" data-action="export-backup">Export learning backup</button>`);
  }
  async function showLicenses() {
    openModal('licenses', 'Open-source licenses.', 'CREDITS', '<p class="modal-intro">Opening the licenses included with your app…</p>');
    try {
      const response = await fetch('third-party-notices.txt');
      if (!response.ok) throw new Error('The local license file could not be opened.');
      const notices = await response.text();
      if (app.modal?.kind === 'licenses') $('#modal-body').innerHTML = `<p class="modal-intro">These notices are included on your device. Clinical image credits are listed in each lesson’s Source view.</p><pre class="license-notices">${esc(notices)}</pre>`;
    } catch (_) {
      if (app.modal?.kind === 'licenses') $('#modal-body').innerHTML = '<p class="modal-intro">The local license file could not be opened. Reinstall or update this app package to restore it.</p>';
    }
  }
  function showRetention() {
    const value = Math.round((settings().retention || .9) * 100);
    openModal('retention', 'How often should you recall?', 'SPACED REPETITION', `<p class="modal-intro">Choose the target recall level used by your review scheduler. Higher targets generally ask for more frequent reviews.</p><div class="range-value"><span id="retention-value">${value}</span>%</div><label class="visually-hidden" for="retention-input">Target recall percentage</label><input class="setting-range" id="retention-input" type="range" min="80" max="97" step="1" value="${value}"><div class="range-labels"><span>80% · Lighter</span><span>97% · More frequent</span></div><button class="primary-button full-width" type="button" data-action="save-retention" style="margin-top:25px">Save target</button>`);
  }
  function showNewLimit() {
    openModal('new-limit', 'Leave room for recall.', 'DAILY NEW LESSONS', `<p class="modal-intro">Set the maximum number of new lessons you want introduced each day. Due reviews remain available.</p><label class="field-label" for="new-limit-input">New lessons per day</label><input class="text-field" id="new-limit-input" type="number" min="1" max="50" step="1" value="${clamp(settings().newPerDay ?? 10, 1, 50)}"><button class="primary-button full-width" type="button" data-action="save-new-limit" style="margin-top:20px">Save daily limit</button>`);
  }
  async function fetchJSON(url) {
    const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 15000);
    try { const response = await fetch(url, { signal: controller.signal }); if (!response.ok) throw new Error(`Unable to load content (${response.status}).`); return await response.json(); }
    finally { clearTimeout(timeout); }
  }
  function validLesson(lesson) {
    return lesson && typeof lesson.id === 'string' && typeof lesson.title === 'string' && typeof lesson.audioUrl === 'string'
      && Array.isArray(lesson.scenes) && lesson.quiz && Array.isArray(lesson.quiz.options) && lesson.quiz.options.length >= 2
      && Number.isInteger(lesson.quiz.correctIndex) && lesson.quiz.correctIndex >= 0 && lesson.quiz.correctIndex < lesson.quiz.options.length;
  }
  async function loadNativePacks() {
    if (!native?.listPacks) return;
    const packs = JSON.parse(native.listPacks() || '[]');
    for (const pack of packs) {
      try {
        const data = Array.isArray(pack.manifest.lessons) ? pack.manifest.lessons : await fetchJSON(new URL(pack.manifest.lessonsFile || 'lessons.json', pack.baseUrl));
        const imported = Array.isArray(data) ? data : data.lessons;
        if (!Array.isArray(imported) || imported.some(x => !validLesson(x))) throw new Error('The lesson package uses an unsupported lesson format.');
        for (const lesson of imported) {
          const index = app.lessons.findIndex(x => x.id === lesson.id);
          const item = { ...lesson, _baseUrl: pack.baseUrl };
          if (index < 0) app.lessons.push(item); else if (Number(item.version || 1) >= Number(app.lessons[index].version || 1)) app.lessons[index] = item;
        }
        const books = Array.isArray(pack.manifest.books) ? pack.manifest.books : [];
        for (const book of books) {
          const index = app.books.findIndex(x => x.id === book.id);
          const previous = index >= 0 ? app.books[index] : null;
          const item = { ...previous, ...book, _baseUrl: pack.baseUrl };
          if (!book.coverUrl && previous?.coverUrl) item.coverUrl = asset(previous.coverUrl, previous._baseUrl);
          if (index < 0) app.books.push(item); else app.books[index] = item;
        }
      } catch (error) { console.warn('A content pack could not be loaded:', error); toast('One content package could not be read. The rest of your collection is available.'); }
    }
  }
  async function checkUpdates(interactive = true) {
    if (interactive) openModal('updates', 'Your collection, up to date.', 'CONTENT & APP', '<p class="modal-intro">Checking the release catalog…</p>');
    try {
      const catalog = await fetchJSON(CATALOG_URL);
      if (catalog.schemaVersion !== 1 || !Array.isArray(catalog.packs)) throw new Error('The catalog format is not supported by this app version.');
      app.catalog = catalog; app.catalogCheckedAt = new Date().toISOString();
      if (interactive && app.modal?.kind === 'updates') renderUpdates();
      else if (!app.modal && (Number(catalog.latestApp?.versionCode) > Number(app.info.versionCode || 1) || catalog.packs.some(pack => !packIsCurrent(pack)))) {
        openModal('updates', 'New learning is ready.', 'CONTENT & APP', ''); renderUpdates();
      }
      if (app.tab === 'settings') renderSettings();
    } catch (error) {
      if (interactive && app.modal?.kind === 'updates') $('#modal-body').innerHTML = '<div class="source-block"><h3>The catalog is unavailable right now.</h3><p>Your downloaded collection still works offline. Check your connection and try again later.</p></div><button class="secondary-button full-width" type="button" data-action="check-updates">Try again</button>';
    }
  }
  function packIsCurrent(pack) {
    const versions = pack.lessonVersions;
    if (versions && typeof versions === 'object' && Object.keys(versions).length) {
      return Object.entries(versions).every(([id, version]) => Number.isFinite(Number(version)) && byId(id) && Number(byId(id).version || 1) >= Number(version));
    }
    if (native?.listPacks) { try { return JSON.parse(native.listPacks()).some(p => p.packId === pack.id && String(p.manifest.version) === String(pack.version)); } catch (_) {} }
    return false;
  }
  function renderUpdates() {
    const catalog = app.catalog; if (!catalog) return;
    const availableApp = catalog.latestApp && Number(catalog.latestApp.versionCode) > Number(app.info.versionCode || 1);
    const packs = catalog.packs.filter(pack => !packIsCurrent(pack));
    $('#modal-body').innerHTML = `<p class="modal-intro">Checked ${esc(dateLabel(app.catalogCheckedAt))}. Content downloads are separate from your installed app.</p>${availableApp ? `<div class="update-card"><h3>InstaAnki ${esc(catalog.latestApp.version)}</h3><p>${esc(catalog.latestApp.notes || 'An updated Android app is available.')}</p><button class="primary-button full-width" type="button" data-action="open-app-update">Open Android update ↗</button></div>` : '<div class="source-block"><h3>No newer app release listed.</h3><p>Your installed version is ' + esc(app.info.version) + '.</p></div>'}<h3>Available lesson packages</h3>${packs.length ? packs.map(pack => `<div class="update-card"><h3>${esc(pack.title)}</h3><p>Version ${esc(pack.version)} · ${amount(Number(pack.sizeBytes) || 0)}</p><button class="secondary-button full-width" type="button" data-download-pack="${esc(pack.id)}" ${app.downloading ? 'disabled' : ''}>Download and install</button></div>`).join('') : `<p class="empty-copy">${catalog.packs.length ? 'All published lessons in this catalog are already on this device.' : 'There are no downloadable packages in this catalog yet. You can still import a personal ZIP from your device.'}</p>`}<div id="download-progress" class="download-progress" ${app.downloading ? '' : 'hidden'}><span>Preparing download…</span><div class="progress-track"><div class="progress-fill" style="width:0%"></div></div></div>`;
  }
  function downloadPack(id) {
    const pack = app.catalog?.packs.find(x => x.id === id); if (!pack) return;
    if (!native?.downloadPack) { toast('Install the Android app to download and install a lesson package.'); return; }
    if (!/^[a-f0-9]{64}$/i.test(pack.sha256 || '') || !pack.url) { toast('This package is missing a valid download checksum.'); return; }
    app.downloading = true; renderUpdates(); native.downloadPack(pack.url, pack.sha256);
  }
  function downloadJSON(data, filename) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 3000);
  }
  async function copyPlan(id) {
    refreshProductionProgress();
    const book = app.books.find(x => x.id === id); if (!book) return;
    const done = [...(book.completedQuestionNumbers || [])].sort((a, b) => a - b);
    const remaining = (book.questions || []).filter(q => q.status !== 'produced').map(q => q.number);
    const text = `Continue the InstaAnki collection for ${book.title} (${book.author}, ${book.year}).\nBook ID: ${book.id}\nCompleted source question numbers: ${done.join(', ') || 'none'}.\n${remaining.length} source questions remain.\nNext batch: ${remaining.slice(0, 10).map(n => `Q${n}`).join(', ')}.\nKeep stable lesson IDs, English narration, source references, licensed real clinical images, and the existing JSON content format. Use the original 2D visual-mnemonic style and the fixed symbol dictionary. Do not mark questions complete until their media and MCQs are produced and checked.`;
    try { await navigator.clipboard.writeText(text); toast('The next-batch brief was copied.'); }
    catch (_) { openModal('copy-plan', 'Your next-batch brief.', 'CONTINUE PRODUCTION', `<p class="modal-intro">Copy this brief into your next content-generation conversation.</p><textarea class="textarea" readonly autofocus>${esc(text)}</textarea>`); }
  }
  const actions = {
    play: () => audio.paused ? playAudio() : pauseAudio(), next: () => nextLesson(),
    like: () => { if (current()) { L.like(current().id); syncIndicators(); } },
    note: showNote, source: () => showSource(false), 'image-credit': () => showSource(true),
    speed: showSpeed, filters: showFilters, 'local-info': showLocalInfo, licenses: showLicenses,
    captions: showTranscript,
    'close-modal': () => closeModal(),
    'clear-filters': () => { closeModal(false); app.specialty = ''; app.tag = ''; rebuildFeed(); },
    'all-feed': () => { app.feedMode = 'all'; rebuildFeed(); },
    'go-feed': () => { showTab('feed'); },
    'quiz-now': () => { if (current()) showQuiz(current(), 'practice', 'practice'); },
    'save-note': () => { if (app.modal?.lessonId) { L.note(app.modal.lessonId, $('#note-input').value); closeModal(); toast('Your private note was saved.'); } },
    'submit-answer': () => submitAnswer(false), 'dont-know': () => submitAnswer(true), 'quiz-continue': continueQuiz,
    'start-review': () => { const lesson = L.due(app.lessons)[0]; if (lesson) showQuiz(lesson, 'review', 'review'); },
    retention: showRetention, 'new-limit': showNewLimit,
    'save-retention': () => { L.setSetting('retention', Number($('#retention-input').value) / 100); closeModal(); renderSettings(); toast('Your recall target was updated.'); },
    'save-new-limit': () => { const value = Number($('#new-limit-input').value); if (!Number.isInteger(value) || value < 1 || value > 50) { toast('Choose a whole number from 1 to 50.'); return; } L.setSetting('newPerDay', value); closeModal(); renderSettings(); rebuildFeed(current()?.id); },
    'import-pack': () => { if (native?.importZip) native.importZip(); else toast('ZIP lesson import is available in the Android app.'); },
    'export-backup': () => { if (native?.exportBackup) native.exportBackup(); else { downloadJSON(L.backup(), `InstaAnki-backup-${new Date().toISOString().slice(0, 10)}.json`); toast('Your learning backup is ready to save.'); } },
    'import-backup': () => { if (native?.importBackup) native.importBackup(); else $('#backup-file').click(); },
    'check-updates': () => checkUpdates(true),
    'open-app-update': () => { if (app.catalog?.latestApp?.url) external(app.catalog.latestApp.url); },
  };
  document.addEventListener('click', async event => {
    const link = event.target.closest('a[data-external]'); if (link) { event.preventDefault(); external(link.href); return; }
    const brand = event.target.closest('.brand'); if (brand) { event.preventDefault(); closeModal(false); showTab('feed'); return; }
    const button = event.target.closest('button'); if (!button || button.disabled) return;
    try {
      if (button.dataset.action) { await actions[button.dataset.action]?.(); return; }
      if (button.dataset.tab) { showTab(button.dataset.tab); return; }
      if (button.dataset.feed) { pauseAudio(); app.feedMode = button.dataset.feed; rebuildFeed(); if (current() && settings().autoPlay) playAudio(false); return; }
      if (button.dataset.book) { showBook(button.dataset.book); return; }
      if (button.dataset.copyPlan) { await copyPlan(button.dataset.copyPlan); return; }
      if (button.dataset.question) {
        const book = app.books.find(x => x.id === button.dataset.questionBook);
        const question = book?.questions?.find(x => x.number === Number(button.dataset.question));
        if (question?.lessonId && byId(question.lessonId)) watchLesson(question.lessonId);
        else toast(`Question ${button.dataset.question} has ${question?.status === 'needs_review' ? 'source details that still need review' : 'not been produced as a lesson yet'}.`);
        return;
      }
      if (button.dataset.watchLesson) { watchLesson(button.dataset.watchLesson); return; }
      if (button.hasAttribute('data-seek-scene')) {
        const target = Number(button.dataset.seekScene); closeModal(false);
        if (Number.isFinite(audio.duration)) { audio.currentTime = clamp(target, 0, audio.duration); app.lastClock = 0; paintFrame(); playAudio(false); }
        return;
      }
      if (button.dataset.reviewLesson) { showQuiz(byId(button.dataset.reviewLesson), 'review', 'review'); return; }
      if (button.dataset.practiceLesson) { showQuiz(byId(button.dataset.practiceLesson), 'practice', 'practice'); return; }
      if (button.hasAttribute('data-answer') && app.modal?.kind === 'quiz' && !app.modal.answered) { app.modal.selected = Number(button.dataset.answer); renderQuiz(); return; }
      if (button.dataset.speed) {
        const speed = Number(button.dataset.speed); L.setSetting('speed', speed); audio.playbackRate = speed; $('#speed-button').textContent = `${speed}×`; closeModal(); if (app.tab === 'settings') renderSettings(); return;
      }
      if (button.hasAttribute('data-specialty')) { app.specialty = button.dataset.specialty; closeModal(false); rebuildFeed(); return; }
      if (button.hasAttribute('data-topic')) { app.tag = button.dataset.topic; closeModal(false); rebuildFeed(); return; }
      if (button.dataset.downloadPack) downloadPack(button.dataset.downloadPack);
    } catch (error) { console.error(error); toast(error.message || 'That action could not be completed.'); }
  });
  document.addEventListener('change', event => {
    if (event.target.hasAttribute('data-captions')) { app.captions = event.target.checked; $('#caption-button').setAttribute('aria-pressed', String(app.captions)); paintFrame(); return; }
    const key = event.target.dataset?.setting; if (!key) return;
    L.setSetting(key, event.target.checked); syncIndicators();
    if (key === 'autoCheckUpdates' && event.target.checked && navigator.onLine) checkUpdates(false);
  });
  document.addEventListener('input', event => {
    if (event.target.id === 'retention-input') $('#retention-value').textContent = event.target.value;
  });
  $('#seek').addEventListener('input', event => { if (Number.isFinite(audio.duration)) { audio.currentTime = Number(event.target.value) / 100 * audio.duration; app.lastClock = 0; paintFrame(); } });
  audio.addEventListener('play', () => { app.lastClock = 0; updatePlayButtons(); });
  audio.addEventListener('pause', () => { flushExposure(); updatePlayButtons(); paintFrame(); });
  audio.addEventListener('loadedmetadata', paintFrame);
  $('#lesson-image').addEventListener('load', paintFrame);
  audio.addEventListener('timeupdate', paintFrame);
  audio.addEventListener('seeking', () => { app.lastClock = 0; });
  audio.addEventListener('error', () => { updatePlayButtons(); if (current()) { $('#lesson-caption').textContent = 'The narration file is unavailable. Reimport this lesson package to restore playback.'; } });
  audio.addEventListener('ended', () => {
    flushExposure(); updatePlayButtons();
    if (!app.endHandled && current()) {
      app.endHandled = true;
      // Revealing a due lesson before answering is assisted practice, not a
      // successful recall. A first learning pass still schedules its end MCQ.
      const mode = app.entryWasDue && app.bypassEntryRecall ? 'practice' : 'review';
      showQuiz(current(), mode, 'feed');
    }
  });
  window.addEventListener('resize', paintFrame);
  $('#modal-backdrop').addEventListener('click', event => { if (event.target === $('#modal-backdrop')) closeModal(); });
  document.addEventListener('keydown', event => {
    if (app.modal) {
      if (event.key === 'Escape') { event.preventDefault(); closeModal(); }
      if (event.key === 'Tab') {
        const nodes = $$('button:not(:disabled),[href],input:not(:disabled),textarea,select,[tabindex="0"]', $('#modal-sheet')).filter(el => el.offsetParent !== null);
        if (!nodes.length) { event.preventDefault(); return; }
        if (event.shiftKey && (document.activeElement === nodes[0] || document.activeElement === $('#modal-sheet'))) { event.preventDefault(); nodes[nodes.length - 1].focus(); }
        else if (!event.shiftKey && document.activeElement === nodes[nodes.length - 1]) { event.preventDefault(); nodes[0].focus(); }
      }
      return;
    }
    if (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'A'].includes(document.activeElement?.tagName)) return;
    if (app.tab === 'feed' && event.code === 'Space') { event.preventDefault(); actions.play(); }
    if (app.tab === 'feed' && event.key === 'ArrowDown') { event.preventDefault(); nextLesson(); }
    if (app.tab === 'feed' && event.key === 'ArrowUp') { event.preventDefault(); nextLesson(-1); }
  });
  let touchStart = null;
  $('#visual-stage').addEventListener('touchstart', event => {
    if (event.target.closest('button') || app.modal || event.touches.length !== 1) return;
    touchStart = { x: event.touches[0].clientX, y: event.touches[0].clientY, at: performance.now() };
  }, { passive: true });
  $('#visual-stage').addEventListener('touchend', event => {
    if (!touchStart || !event.changedTouches.length) return;
    const deltaY = event.changedTouches[0].clientY - touchStart.y;
    const deltaX = event.changedTouches[0].clientX - touchStart.x;
    if (Math.abs(deltaY) > 62 && Math.abs(deltaY) > Math.abs(deltaX) * 1.4 && performance.now() - touchStart.at < 950) nextLesson(deltaY < 0 ? 1 : -1);
    touchStart = null;
  }, { passive: true });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState !== 'visible') pauseAudio(); });
  window.addEventListener('instaanki:background', pauseAudio);
  window.addEventListener('learning:changed', syncIndicators);
  window.addEventListener('instaanki:error', event => { app.downloading = false; toast(event.detail?.message || 'The operation could not be completed.'); if (app.modal?.kind === 'updates') renderUpdates(); });
  window.addEventListener('instaanki:import-started', () => { pauseAudio(); toast('Preparing your lesson package…'); });
  window.addEventListener('instaanki:download-progress', event => {
    const box = $('#download-progress'); if (!box) return; box.hidden = false;
    const detail = event.detail || {};
    box.querySelector('span').textContent = detail.percent == null ? `Downloaded ${amount(detail.receivedBytes)}` : `Downloaded ${detail.percent}% · ${amount(detail.receivedBytes)}`;
    box.querySelector('.progress-fill').style.width = `${clamp(detail.percent || 0, 0, 100)}%`;
  });
  window.addEventListener('instaanki:pack-imported', async () => {
    app.downloading = false; const id = current()?.id;
    await loadNativePacks(); rebuildFeed(id); syncIndicators();
    if (app.tab === 'settings') renderSettings(); if (app.tab === 'publications') renderPublications(); if (app.tab === 'review') renderReview();
    if (app.modal?.kind === 'updates') renderUpdates(); toast('Your new lessons are ready. Learning history was preserved.');
  });
  window.addEventListener('instaanki:backup-exported', () => toast('Your learning backup was saved.'));
  window.addEventListener('instaanki:backup-imported', () => { L.load(); syncWarning(); syncIndicators(); closeModal(false); rebuildFeed(current()?.id); showTab(app.tab); toast('Your learning backup was restored.'); });
  $('#backup-file').addEventListener('change', async event => {
    const file = event.target.files?.[0]; if (!file) return;
    try { if (file.size > 32 * 1024 * 1024) throw new Error('Choose a backup smaller than 32 MB.'); L.restore(JSON.parse(await file.text())); L.load(); syncWarning(); syncIndicators(); rebuildFeed(current()?.id); showTab(app.tab); toast('Your learning backup was restored.'); }
    catch (error) { toast(error.message || 'This backup could not be restored.'); }
    finally { event.target.value = ''; }
  });
  window.InstaAnkiBack = () => { if (app.modal) { closeModal(); return true; } if (app.tab !== 'feed') { showTab('feed'); return true; } return false; };
  async function boot() {
    try {
      if (!L) throw new Error('The learning engine could not be loaded.');
      L.load(); syncWarning();
      if (native?.getAppInfo) { try { app.info = { ...app.info, ...JSON.parse(native.getAppInfo()) }; } catch (_) { } }
      const results = await Promise.allSettled([fetchJSON('data/lessons.json'), fetchJSON('data/books.json')]);
      if (results[0].status === 'fulfilled') {
        const raw = results[0].value;
        app.lessons = (Array.isArray(raw) ? raw : raw.lessons || []).filter(validLesson);
      }
      if (results[1].status === 'fulfilled') { const raw = results[1].value; app.books = Array.isArray(raw) ? raw : raw.books || []; }
      await loadNativePacks();
      if (!app.lessons.length && results[0].status === 'rejected') throw new Error('Your lesson collection could not be opened. Use Settings to import a package, or reopen the app.');
      rebuildFeed(); syncIndicators(); app.frame = requestAnimationFrame(tick);
      if (settings().autoPlay && current()) playAudio(false);
      if (settings().autoCheckUpdates && navigator.onLine) checkUpdates(false);
    } catch (error) {
      $('#feed-empty').classList.add('boot-error');
      $('#feed-empty').innerHTML = `<div class="empty-emblem">${icons.book}</div><h1>Let’s open your collection.</h1><p>${esc(error.message)}</p><button class="secondary-button empty-button" type="button" data-tab="settings">Open settings</button>`;
    }
  }
  boot();
})();
