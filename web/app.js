/* InstaAnki: the interface runs entirely on this device. */
(() => {
  'use strict';
  const playerNodes = new Map();
  const $ = (selector, root = document) => (root === document && playerNodes.get(selector)) || root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const L = window.Learning;
  const G = window.VisualGuidance;
  const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const native = window.AndroidNative || null;
  const audio = $('#lesson-audio');
  const SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2];
  const CATALOG_URL = 'https://raw.githubusercontent.com/blsmohamme972-lab/InstaAnki/main/content/catalog-v2.json';
  const app = {
    lessons: [], books: [], feed: [], index: 0, tab: 'feed', feedMode: 'all', specialty: '', tag: '',
    topicModel: null, topicDraft: [],
    modal: null, previousFocus: null, resumeOnClose: false, captions: true, endHandled: false,
    frame: 0, lastClock: 0, exposure: 0, lastScene: '', currentImage: '', imageReady: false, catalog: null,
    catalogCheckedAt: null, downloading: false, info: { version: '0.2.0', versionCode: 3 }, toastTimer: 0,
    bypassNextRecall: null, bypassEntryRecall: false, entryWasDue: false,
    pendingQuestion: null, explanationContext: null, lastQuestionResult: null,
    bundledLessons: [], bundledBooks: [], distribution: null, collectionGeneration: 0, collectionWarnings: [],
    sourceUrl: '', lastPaint: 0, flowKey: '', endingId: '', endingNode: '', preloads: [],
  };
  for (const id of ['lesson-image', 'image-viewport', 'camera-layer', 'visual-stage', 'lesson-caption', 'scene-heading', 'lesson-title', 'spotlight', 'teaching-pointer', 'focus-label', 'pointer-tip', 'pointer-shaft', 'pointer-outline', 'pointer-head', 'pointer-hand', 'target-region', 'seek', 'current-time', 'duration-time', 'lesson-ending', 'clinical-gallery', 'recap-map', 'feed-status', 'lesson-question-button']) {
    playerNodes.set(`#${id}`, document.getElementById(id));
  }
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
  const setText = (node, value) => { const text = String(value ?? ''); if (node.textContent !== text) node.textContent = text; };
  function playbackDuration(lesson = current()) {
    const actual = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : Number(lesson?.durationSeconds) || 1;
    const end = Number(lesson?.presentation?.effectiveEndSeconds);
    return Number.isFinite(end) && end > 0 ? Math.min(end, actual) : actual;
  }
  function stopFrames() { if (app.frame) cancelAnimationFrame(app.frame); app.frame = 0; app.lastClock = 0; }
  function syncImmersive() { native?.setImmersive?.(app.tab === 'feed' && !!current() && !app.modal); }
  function startFrames() {
    if (!app.frame && !audio.paused && !audio.ended && document.visibilityState === 'visible' && app.tab === 'feed' && !app.modal) app.frame = requestAnimationFrame(tick);
  }
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
      syncLessonFlow();
    }
    document.body.classList.toggle('reduced-motion', !!settings().reduceMotion);
  }
  function rebuildFeed(preferredId) {
    pauseAudio();
    const dailyIds = settings().dailyTopicIds || [];
    const focusedLessons = app.topicModel ? app.topicModel.filterLessons(app.lessons, dailyIds) : app.lessons;
    const visibleFocused = focusedLessons.filter(lesson => !L.get(lesson.id).hidden);
    let lessons = app.feedMode === 'due' ? L.due(app.lessons) : app.feedMode === 'saved' ? app.lessons.filter(x => L.get(x.id).liked && !L.get(x.id).hidden) : L.getFeed(focusedLessons);
    if (app.specialty) lessons = lessons.filter(x => x.specialty === app.specialty || x.primarySpecialtyId === app.specialty);
    if (app.tag) lessons = lessons.filter(x => x.tags?.some(t => t.id === app.tag));
    if (preferredId && app.bypassNextRecall === preferredId && !lessons.some(x => x.id === preferredId)) {
      const explicitlyChosen = byId(preferredId); if (explicitlyChosen) lessons = [explicitlyChosen, ...lessons];
    }
    app.feed = lessons;
    app.index = Math.max(0, lessons.findIndex(x => x.id === preferredId));
    document.body.classList.toggle('collection-empty', app.lessons.length === 0);
    syncImmersive();
    $('#filter-indicator').hidden = !app.specialty && !app.tag;
    $$('[data-feed]').forEach(button => button.classList.toggle('selected', button.dataset.feed === app.feedMode));
    if (!lessons.length) {
      pauseAudio(); app.sourceUrl = ''; app.preloads.length = 0; audio.removeAttribute('src'); audio.load();
      $('#lesson-card').hidden = true; $('#feed-empty').hidden = false;
      const heading = app.feedMode === 'saved' ? 'Your saved collection' : app.feedMode === 'due' ? 'A little breathing room' : app.specialty || app.tag ? 'No lessons in this view' : 'Your gallery is ready to grow';
      const copy = app.feedMode === 'saved' ? 'Tap the heart on a lesson to keep it here. Your saved lessons stay on this device.' : app.feedMode === 'due' ? 'Nothing is due right now. Watch a new lesson, or practise a familiar one whenever you like.' : app.specialty || app.tag ? 'Try another specialty or clear the current filters.' : 'Import a lesson package from Settings to begin your learning collection.';
      $('#feed-empty').innerHTML = `<div class="empty-emblem">${app.feedMode === 'saved' ? icons.book : icons.recall}</div><h1>${esc(heading)}</h1><p>${esc(copy)}</p><button class="secondary-button empty-button" data-action="${app.specialty || app.tag ? 'clear-filters' : 'all-feed'}" type="button">${app.specialty || app.tag ? 'Clear filters' : 'Explore the feed'}</button>`;
      if (app.feedMode === 'all' && dailyIds.length && !app.specialty && !app.tag) {
        $('#feed-empty').innerHTML = `<div class="empty-emblem">${icons.book}</div><h1>No lessons in your daily topics yet.</h1><p>${esc(app.topicModel?.summary(dailyIds) || 'Your selected topics')}<br>Choose more tags or All to explore the available lessons.</p><button class="secondary-button empty-button" type="button" data-action="daily-topics">Choose daily topics</button>`;
      }
      if (app.feedMode === 'all' && visibleFocused.length && !app.specialty && !app.tag) {
        $('#feed-empty').innerHTML = `<div class="empty-emblem">${icons.recall}</div><h1>Today’s new-lesson limit is reached.</h1><p>Your topics still have lessons available. Continue with your due reviews, or adjust the daily limit.</p><button class="secondary-button empty-button" type="button" data-action="review-home">Open due reviews</button><button class="quiet-button" type="button" data-action="new-limit">Adjust daily limit</button>`;
      }
      if (app.feedMode === 'all' && focusedLessons.length && !visibleFocused.length && !app.specialty && !app.tag) {
        $('#feed-empty').innerHTML = `<div class="empty-emblem">${icons.book}</div><h1>Your lessons are hidden.</h1><p>Restore a lesson to see it here again. Its existing review schedule and notes are kept.</p><button class="secondary-button empty-button" data-action="feedback-history" type="button">Manage hidden lessons</button>`;
      }
      if (!app.lessons.length) {
        $('#feed-empty').innerHTML = `<span class="welcome-kicker">YOUR LEARNING GALLERY</span><div class="welcome-mark" aria-hidden="true">${icons.play}<span>${icons.book}</span></div><span class="collection-count"><span class="status-dot"></span>0 lessons on this device</span><h1>A fresh place<br>to learn.</h1><p>Your collection starts here. Add a lesson package when you’re ready.</p><div class="welcome-actions"><button class="primary-button full-width" data-action="import-pack" type="button">Import lesson package ${icons.arrow}</button><button class="secondary-button full-width" data-action="check-updates" type="button">Check for updates</button></div>${app.books[0] ? `<button class="welcome-source" type="button" data-book="${esc(app.books[0].id)}">${icons.book}<span><small>APPROVED SOURCE</small>${esc(app.books[0].title)}<em>${esc(app.books[0].author)} · ${esc(app.books[0].year)}</em></span>${icons.arrow}</button>` : ''}`;
      }
      $('#feed-status').textContent = 'No lessons in this view';
      $('#lesson-question-button').disabled = true;
      return;
    }
    $('#lesson-card').hidden = false; $('#feed-empty').hidden = true; $('#lesson-question-button').disabled = false;
    setLesson(app.index, false);
  }
  function flushExposure() {
    const lesson = current();
    if (lesson && app.exposure > 0 && L && !L.loadError) { const elapsed = app.exposure; app.exposure = 0; L.expose(lesson.id, elapsed); }
    app.lastClock = 0;
  }
  function pauseAudio() { audio.pause(); stopFrames(); flushExposure(); }
  function preloadNext() {
    // Keep only the current media and the next poster warm; no hidden players or
    // whole-library image/audio fetches on mobile.
    app.preloads.length = 0;
    const next = app.feed[app.index + 1];
    if (next?.poster) { const image = new Image(); image.decoding = 'async'; image.src = asset(next.poster, next._baseUrl); app.preloads.push(image); }
    for (const item of current()?.presentation?.clinicalGallery?.images || []) {
      const image = new Image(); image.decoding = 'async'; image.src = asset(item.url, current()._baseUrl); app.preloads.push(image);
    }
  }
  function setLesson(index, shouldPlay = settings().autoPlay) {
    pauseAudio();
    app.index = clamp(index, 0, app.feed.length - 1);
    const lesson = current(); if (!lesson) return;
    app.bypassEntryRecall = app.bypassNextRecall === lesson.id;
    app.bypassNextRecall = null;
    const entryCard = L.get(lesson.id).card;
    app.entryWasDue = !!entryCard && entryCard.reps > 0 && new Date(entryCard.due).getTime() <= Date.now();
    app.endHandled = false; app.lastScene = ''; app.currentImage = ''; app.exposure = 0; app.lastClock = 0;
    app.flowKey = ''; app.endingId = ''; app.endingNode = ''; app.lastPaint = 0;
    $('#lesson-ending').hidden = true; $('#clinical-gallery').replaceChildren(); $('#recap-map').replaceChildren();
    $('#visual-stage').classList.remove('has-ending');
    $('#lesson-title').textContent = lesson.title;
    $('#lesson-specialty').textContent = lesson.specialty || 'Medical learning';
    $('#lesson-position').textContent = `${String(app.index + 1).padStart(2, '0')} / ${String(app.feed.length).padStart(2, '0')}`;
    $('#locus-label').textContent = lesson.locus ? `${lesson.locus.room || 'Memory gallery'} · ${lesson.locus.anchor || 'Recall anchor'}` : 'Your memory gallery';
    $('#lesson-tags').innerHTML = (lesson.tags || []).slice(0, 3).map(tag => `<span>${esc(tag.label)}</span>`).join('');
    $('#lesson-image').alt = `${lesson.title} — illustrated memory scene`;
    $('#lesson-caption').textContent = lesson.scenes?.[0]?.caption || 'Press play to enter the lesson.';
    app.sourceUrl = asset(lesson.audioUrl, lesson._baseUrl); audio.src = app.sourceUrl;
    audio.playbackRate = clamp(settings().speed || 1, .5, 2);
    audio.load();
    $('#seek').value = '0'; $('#seek').style.setProperty('--progress', '0%');
    $('#duration-time').textContent = time(lesson.presentation?.effectiveEndSeconds || lesson.durationSeconds);
    $('#current-time').textContent = '0:00'; $('#speed-button').textContent = `${audio.playbackRate}×`;
    paintFrame(); syncIndicators(); updatePlayButtons(); preloadNext();
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
    if (!current() || app.modal || app.tab !== 'feed' || document.visibilityState !== 'visible') return;
    const explaining = app.explanationContext?.lessonId === current().id;
    if (app.pendingQuestion?.lessonId === current().id && !explaining) { resumePendingQuestion(); return; }
    if (app.lastQuestionResult?.lessonId === current().id && !explaining) { watchLesson(current().id); return; }
    if (maybeGateRecall(current())) return;
    if (audio.ended || audio.currentTime >= playbackDuration()) {
      handlePlaybackEnd(true); return;
    }
    try { await audio.play(); }
    catch (error) { updatePlayButtons(); if (reportError && !['NotAllowedError', 'AbortError'].includes(error.name)) toast('The audio could not start. Try again or check this lesson package.'); }
  }
  function updatePlayButtons() {
    const playing = !audio.paused && !audio.ended;
    const explaining = app.explanationContext?.lessonId === current()?.id;
    const waiting = app.pendingQuestion?.lessonId === current()?.id && !explaining && !playing;
    const replay = app.lastQuestionResult?.lessonId === current()?.id && !explaining && !playing;
    $('#visual-stage').classList.toggle('is-playing', playing);
    $('#play-button').innerHTML = playing ? icons.pause : waiting ? icons.recall : icons.play;
    $('#play-button').setAttribute('aria-label', playing ? 'Pause lesson' : waiting ? 'Answer question' : replay ? 'Replay video' : 'Play lesson');
    $('#center-play').innerHTML = waiting ? icons.recall : icons.play;
    $('#center-play').setAttribute('aria-label', waiting ? 'Answer question' : replay ? 'Replay video' : 'Play lesson');
    $('#center-play').hidden = playing || !!app.modal || audio.currentTime > .25;
    syncLessonFlow();
  }
  function syncLessonFlow() {
    const lesson = current(); if (!lesson) return;
    const question = app.modal?.kind === 'quiz' && app.modal.lessonId === lesson.id ? app.modal : null;
    const pending = app.pendingQuestion?.lessonId === lesson.id;
    const explaining = app.explanationContext?.question?.lessonId === lesson.id;
    const result = app.lastQuestionResult?.lessonId === lesson.id;
    const step = question ? (question.answered ? 'result' : 'answer') : explaining ? 'watch' : pending ? 'answer' : result ? 'result' : 'watch';
    const outro = lesson.presentation?.clinicalGallery || lesson.realImageOutro;
    const outroStart = Number(outro?.startSeconds ?? outro?.start);
    const outroEnd = Math.min(Number(outro?.endSeconds ?? outro?.end) || playbackDuration(), playbackDuration());
    const inOutro = outro && audio.currentTime >= outroStart && audio.currentTime < outroEnd;
    const flowKey = [lesson.id, step, !!explaining, !!app.explanationContext?.question?.answered, !!pending, !!inOutro, inOutro ? Math.ceil(outroEnd - audio.currentTime) : '', app.index, app.feed.length].join(':');
    if (flowKey === app.flowKey) return;
    app.flowKey = flowKey;
    const names = ['watch', 'answer', 'result'];
    $$('[data-lesson-step]').forEach(item => {
      item.classList.toggle('is-current', item.dataset.lessonStep === step);
      item.classList.toggle('is-complete', names.indexOf(item.dataset.lessonStep) < names.indexOf(step));
      if (item.dataset.lessonStep === step) item.setAttribute('aria-current', 'step'); else item.removeAttribute('aria-current');
    });
    $('#feed-status').textContent = explaining ? (app.explanationContext.question.answered ? 'Replay · your answer is saved' : 'Explanation · your question is saved') : pending ? 'Your question is ready' : inOutro ? `Recap · question in ${Math.ceil(outroEnd - audio.currentTime)}s` : step === 'result' ? 'Answer saved · continue when ready' : 'Swipe up for the next lesson';
    const button = $('#lesson-question-button');
    button.textContent = explaining ? (app.explanationContext.question.answered ? 'Return to result' : 'Return to question') : pending ? 'Answer question' : step === 'result' ? 'View answer' : 'Go to question';
    button.classList.toggle('is-ready', !!pending);
    const next = $('[data-action="next"]');
    next.innerHTML = `${app.index >= app.feed.length - 1 ? 'Finish' : 'Next'}${icons.arrow}`;
    next.setAttribute('aria-label', app.index >= app.feed.length - 1 ? 'Finish this selection' : 'Next lesson');
  }
  function showFeedComplete() {
    pauseAudio();
    openModal('feed-complete', 'You reached the end.', 'CURRENT TOPICS', `<p class="modal-intro">You have reached the end of this selection. Choose another topic, review what is due, or replay this explanation.</p><div class="quiz-actions"><button class="primary-button full-width" type="button" data-action="daily-topics">Choose daily topics</button><button class="secondary-button full-width" type="button" data-action="review-home">Open due reviews</button>${current() ? `<button class="quiet-button full-width" type="button" data-watch-lesson="${esc(current().id)}">Watch this explanation again</button>` : ''}</div>`);
  }
  function nextLesson(direction = 1) {
    if (!app.feed.length) return;
    pauseAudio();
    if (app.feedMode === 'due') {
      const due = new Set(L.due(app.lessons).map(lesson => lesson.id));
      const remaining = direction > 0 ? app.feed.slice(app.index + 1) : app.feed.slice(0, app.index).reverse();
      const preferred = remaining.find(lesson => due.has(lesson.id))?.id;
      if (!preferred) { showTab('review', false); toast('Review selection finished. Remaining due questions are listed here.'); return; }
      rebuildFeed(preferred); if (current() && settings().autoPlay) playAudio(false); return;
    }
    if (direction > 0 && app.index >= app.feed.length - 1) { showFeedComplete(); return; }
    if (direction < 0 && app.index === 0) { toast('This is the first lesson in this selection.'); return; }
    setLesson(app.index + direction);
  }
  function renderEnding(lesson, now) {
    const gallery = lesson.presentation?.clinicalGallery;
    const recap = lesson.presentation?.recap;
    const start = Number(gallery?.startSeconds);
    const end = Number(gallery?.endSeconds) || playbackDuration(lesson);
    const visible = gallery?.images?.length >= 3 && gallery.images.length <= 6 && Number.isFinite(start) && now >= start && now <= end + .05;
    $('#lesson-ending').hidden = !visible;
    $('#visual-stage').classList.toggle('has-ending', !!visible);
    if (!visible) return false;
    if (app.endingId !== lesson.id) {
      app.endingId = lesson.id;
      $('#clinical-gallery').dataset.count = String(gallery.images.length);
      $('#clinical-gallery').style.setProperty('--gallery-rows', String(Math.ceil(gallery.images.length / 2)));
      $('#clinical-gallery').innerHTML = gallery.images.map((item, index) => `<button type="button" class="clinical-tile" data-clinical-image="${index}" aria-label="Inspect ${esc(item.title || `clinical image ${index + 1}`)} and source"><img src="${esc(asset(item.url, lesson._baseUrl))}" alt="${esc(item.alt || item.title || 'Clinical image')}" decoding="async"><span class="clinical-label">${esc(item.shortLabel || item.title || `Clinical view ${index + 1}`)}</span></button>`).join('');
      const nodes = recap?.nodes || [];
      $('#recap-map').innerHTML = nodes.map((node, index) => `${index && (recap.edges || []).some(edge => edge.from === nodes[index - 1].id && edge.to === node.id) ? '<span class="recap-arrow" aria-hidden="true">→</span>' : ''}<span class="recap-node" data-recap-node="${esc(node.id)}">${esc(node.label)}</span>`).join('');
    }
    const active = (recap?.cueBindings || []).find(cue => now >= Number(cue.startSeconds) && now < Number(cue.endSeconds));
    const activeId = active?.nodeId || '';
    if (app.endingNode !== activeId) {
      app.endingNode = activeId;
      $$('[data-recap-node]').forEach(node => {
        const selected = node.dataset.recapNode === activeId;
        node.classList.toggle('is-active', selected);
        if (selected) node.setAttribute('aria-current', 'step'); else node.removeAttribute('aria-current');
      });
    }
    const focus = settings().reduceMotion || motionPreference.matches ? -1 : Math.min(gallery.images.length - 1, Math.floor((now - start) / Math.max(1, (end - start) / gallery.images.length)));
    $$('.clinical-tile').forEach((tile, index) => tile.classList.toggle('is-emphasized', focus === index));
    return true;
  }
  function paintFrame(force = true) {
    const lesson = current(); if (!lesson) return;
    const clock = performance.now();
    if (force === false && clock - app.lastPaint < 32) return;
    app.lastPaint = clock;
    const duration = playbackDuration(lesson);
    const now = Math.min(audio.currentTime || 0, duration);
    $('#center-play').hidden = !audio.paused || !!app.modal || now > .25;
    setText($('#current-time'), time(now)); setText($('#duration-time'), time(duration));
    if (document.activeElement !== $('#seek')) $('#seek').value = String(now / duration * 100);
    $('#seek').style.setProperty('--progress', `${clamp(now / duration * 100, 0, 100)}%`);
    $('#seek').setAttribute('aria-valuetext', `${time(now)} of ${time(duration)}`);
    syncLessonFlow();
    const scene = lesson.scenes?.find(item => now >= item.start && now < item.end) || lesson.scenes?.[lesson.scenes.length - 1] || {};
    const outroStart = Number(lesson.realImageOutro?.start);
    const isOutro = !lesson.presentation?.clinicalGallery && Number.isFinite(outroStart) && now >= outroStart && !!lesson.realImages?.length;
    const isReal = !!lesson.realImages?.length && (isOutro || scene.kind === 'clinical');
    const clinicalImage = lesson.realImages?.find(item => item.url === scene.image) || lesson.realImages?.[0];
    const image = isOutro ? lesson.realImages[0].url : scene.image || lesson.poster;
    const url = asset(image, lesson._baseUrl);
    if (url !== app.currentImage) {
      app.currentImage = url; app.imageReady = false;
      $('#teaching-pointer').setAttribute('hidden', ''); $('#focus-label').hidden = true;
      $('#spotlight').style.opacity = '0'; $('#lesson-image').src = url;
    }
    $('#visual-stage').classList.toggle('is-real', !!isReal); $('#real-image-badge').hidden = !isReal;
    $('#lesson-image').alt = isReal ? clinicalImage?.title || 'Clinical image' : `${lesson.title} — illustrated memory scene`;
    if (isReal) $('#real-image-badge > span:nth-child(2)').textContent = `REAL CLINICAL IMAGE · ${clinicalImage.license || 'SOURCE'}`;
    const sceneKey = `${scene.id || ''}:${!!isReal}:${isOutro}`;
    if (sceneKey !== app.lastScene) {
      app.lastScene = sceneKey;
      $('#lesson-caption').textContent = isOutro ? clinicalImage.caption || clinicalImage.title : scene.caption || clinicalImage?.caption || '';
      $('#scene-heading').textContent = scene.caption || '';
    }
    $('#scene-heading').classList.toggle('visible', !isReal && !!scene.caption && app.captions);
    $('#lesson-caption').hidden = !app.captions;
    const frame = $('#visual-stage'), imageElement = $('#lesson-image'), layer = $('#camera-layer');
    const guidance = lesson.visualGuidance;
    frame.classList.toggle('has-guidance', !!guidance);
    const active = G?.resolve(guidance, now, image, lesson.realImageOutro);
    frame.dataset.cueId = active?.cue.id || '';
    frame.dataset.targetId = '';
    $('#scene-heading').textContent = active?.cue.text || (isOutro ? clinicalImage?.caption : scene.caption) || '';
    $('#scene-heading').classList.toggle('visible', app.captions && !!$('#scene-heading').textContent && (!isReal || !!guidance));
    $('#teaching-pointer').setAttribute('hidden', ''); $('#focus-label').hidden = true;
    $('#spotlight').style.opacity = '0';
    // The original coordinate map belongs only to its original image. The
    // three-image recap never reuses an arrow from that image's coordinates.
    if (renderEnding(lesson, now)) { layer.style.transform = 'none'; return; }
    // Use the actual untransformed image box, including clinical-image insets.
    // All three projections share this geometry; no overlay gets a separate animation.
    const imageViewport = $('#image-viewport');
    const box = { x: imageViewport.offsetLeft + layer.offsetLeft, y: imageViewport.offsetTop + layer.offsetTop, width: layer.clientWidth, height: layer.clientHeight };
    const still = isReal || !!settings().reduceMotion || motionPreference.matches;
    const camera = G?.cameraAt(guidance, active, now, image, still);
    let geometry = app.imageReady && G?.geometry(box, imageElement.naturalWidth, imageElement.naturalHeight, camera);
    if (!geometry) { layer.style.transform = 'none'; return; }
    const imageSpec = guidance?.images?.[image];
    // A changed/corrupt image never inherits a coordinate from its predecessor.
    const target = active?.target;
    if (target && camera && !still) {
      // A new cue can sit near the opposite edge from the previous camera pose.
      // Pull that transition back toward the full image until its actual target
      // remains on screen; never pin an arrow to a different image coordinate.
      const inside = value => { const point = value.project(target.x, target.y); return point.x >= 2 && point.x <= frame.clientWidth - 2 && point.y >= 2 && point.y <= frame.clientHeight - 2; };
      if (!inside(geometry)) {
        geometry = G.geometry(box, imageElement.naturalWidth, imageElement.naturalHeight, { x: .5, y: .5, scale: 1 });
        let low = 0, high = 1;
        for (let attempt = 0; attempt < 9; attempt++) {
          const fraction = (low + high) / 2;
          const candidate = G.geometry(box, imageElement.naturalWidth, imageElement.naturalHeight, { x: .5 + (camera.x - .5) * fraction, y: .5 + (camera.y - .5) * fraction, scale: 1 + (camera.scale - 1) * fraction });
          if (inside(candidate)) { low = fraction; geometry = candidate; } else high = fraction;
        }
      }
    }
    layer.style.transform = `translate(${geometry.panX}px, ${geometry.panY}px) scale(${geometry.scale})`;
    if (!target || !imageSpec || imageSpec.width !== imageElement.naturalWidth || imageSpec.height !== imageElement.naturalHeight) return;
    const tip = geometry.project(target.x, target.y);
    const focus = geometry.project(target.spotX ?? target.x, target.spotY ?? target.y);
    const rx = Math.max(8, target.rx * geometry.width * geometry.scale);
    const ry = Math.max(8, target.ry * geometry.height * geometry.scale);
    if (tip.x < 0 || tip.x > frame.clientWidth || tip.y < 0 || tip.y > frame.clientHeight) return;
    const pointer = G.pointer(tip, box);
    const svg = $('#teaching-pointer');
    svg.setAttribute('viewBox', `0 0 ${frame.clientWidth} ${frame.clientHeight}`);
    $('#pointer-tip').setAttribute('cx', tip.x); $('#pointer-tip').setAttribute('cy', tip.y);
    $('#pointer-shaft').setAttribute('d', pointer.shaft); $('#pointer-outline').setAttribute('d', pointer.shaft);
    $('#pointer-head').setAttribute('d', pointer.head); $('#pointer-hand').setAttribute('transform', pointer.hand);
    const region = $('#target-region');
    for (const [key, value] of Object.entries({ cx: focus.x, cy: focus.y, rx, ry })) region.setAttribute(key, value);
    $('#spotlight').style.background = `radial-gradient(ellipse ${rx}px ${ry}px at ${focus.x}px ${focus.y}px, transparent 0%, transparent 85%, rgba(3,12,20,${isReal ? .12 : .18}) 140%, rgba(3,12,20,${isReal ? .25 : .38}) 220%)`;
    $('#spotlight').style.opacity = '1';
    svg.removeAttribute('hidden'); frame.dataset.targetId = active.cue.targetId;
    $('#focus-label').textContent = target.label; $('#focus-label').hidden = false;
  }
  function tick(clock) {
    app.frame = 0;
    if (!audio.paused && !audio.ended && !audio.seeking && audio.readyState >= 3 && document.visibilityState === 'visible' && app.tab === 'feed' && !app.modal) {
      if (app.lastClock) app.exposure += Math.min(.5, Math.max(0, (clock - app.lastClock) / 1000));
      app.lastClock = clock;
      if (app.exposure >= 1) { const amount = app.exposure; app.exposure = 0; if (!L.loadError) L.expose(current().id, amount); }
      paintFrame(false);
      if (handlePlaybackEnd()) return;
    } else app.lastClock = 0;
    startFrames();
  }
  function handlePlaybackEnd(explicit = false) {
    if (!current() || app.endHandled || app.modal || app.tab !== 'feed' || document.visibilityState !== 'visible' || !app.sourceUrl || audio.currentSrc !== app.sourceUrl) return false;
    const duration = playbackDuration();
    if (audio.currentTime < duration - (audio.ended ? .04 : 0) || (!explicit && audio.paused && !audio.ended)) return false;
    app.endHandled = true;
    pauseAudio();
    if (audio.currentTime > duration + .03) audio.currentTime = duration;
    paintFrame(); updatePlayButtons();
    finishLessonPlayback();
    return true;
  }
  function showTab(tab, resume = true) {
    if (!['feed', 'publications', 'review', 'insights', 'settings'].includes(tab)) return;
    const previousTab = app.tab;
    if (tab !== 'feed') pauseAudio();
    app.tab = tab;
    document.body.classList.toggle('feed-active', tab === 'feed');
    syncImmersive();
    $$('.screen').forEach(screen => { screen.hidden = screen.id !== `screen-${tab}`; });
    $$('[data-tab]').forEach(button => { button.classList.toggle('active', button.dataset.tab === tab); if (button.dataset.tab === tab) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current'); });
    if (tab === 'publications') renderPublications();
    if (tab === 'review') renderReview();
    if (tab === 'insights') renderInsights();
    if (tab === 'settings') renderSettings();
    if (tab === 'feed') {
      if (previousTab !== 'feed' && resume && current()) {
        const card = L.get(current().id).card;
        app.entryWasDue = !!card && card.reps > 0 && new Date(card.due).getTime() <= Date.now();
        app.bypassEntryRecall = false;
      }
      syncIndicators(); paintFrame(); if (resume && current() && !maybeGateRecall(current()) && settings().autoPlay && !app.modal) playAudio(false);
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
    const empty = app.lessons.length === 0;
    $('#screen-publications').innerHTML = `<span class="page-eyebrow">THE SOURCE COLLECTION</span><h1 class="page-heading" id="publications-heading">From page to memory.</h1><p class="page-intro">${empty ? 'Your original source is ready. No lessons are installed on this device.' : 'Your publications, transformed one learning objective at a time.'}</p>${empty ? '<div class="installed-summary"><b>0</b><span>lessons on this device</span></div>' : ''}${app.books.map(book => `<button class="surface-card publication-card" type="button" data-book="${esc(book.id)}" aria-label="Open ${esc(book.title)}"><div class="book-top">${cover(book)}<div class="book-details"><div class="book-year">${esc(book.year || '')} · PERSONAL COLLECTION</div><h2>${esc(book.title)}</h2><p>${esc(book.author)}<br>${Number(book.totalQuestions) || 0} source questions</p></div></div><div class="book-progress-head"><span>${empty ? 'Historical production' : 'Lessons produced'}</span><b>${Number(book.completedVideos) || 0} / ${Number(book.totalQuestions) || 0}</b></div><div class="progress-track"><div class="progress-fill" style="width:${clamp((Number(book.completedVideos) || 0) / Math.max(1, Number(book.totalQuestions)) * 100, 0, 100)}%"></div></div><div class="book-foot"><span>${empty ? 'Previously produced lessons are not bundled in this fresh collection.' : esc(book.sourceStatus || 'Source collection') + ' · ' + clamp((Number(book.completedVideos) || 0) / Math.max(1, Number(book.totalQuestions)) * 100, 0, 100).toFixed(1) + '%'}</span>${icons.arrow}</div></button>`).join('') || '<p class="empty-copy">Your publication collection is empty. Import a source-linked lesson package to begin.</p>'}<div class="library-summary"><div class="mini-stat"><b>${empty ? 0 : produced}</b><span>${empty ? 'Lessons on this device' : 'Lessons produced'}</span></div><div class="mini-stat"><b>${empty ? produced : Math.max(0, total - produced)}</b><span>${empty ? 'Historically produced' : 'Questions still to produce'}</span></div></div><div class="inline-note">${icons.lock}<span>${empty ? 'Historical production belongs to the source record. It does not mean those lessons are installed. New lesson production is paused.' : 'Production progress belongs to your source collection. Your personal review progress is tracked separately in Insights.'}</span></div><button class="secondary-button full-width" type="button" data-action="import-pack">Import a lesson package ${icons.arrow}</button>`;
    bindCoverFallbacks();
  }
  function lessonRow(lesson, action, suffix) {
    return `<button class="lesson-row" type="button" data-${action}="${esc(lesson.id)}"><img class="lesson-thumb" src="${esc(asset(lesson.poster, lesson._baseUrl))}" alt=""><span class="lesson-row-copy"><h3>${esc(lesson.title)}</h3><p>${esc(lesson.specialty || 'Medical learning')}${suffix ? ` · ${esc(suffix)}` : ''}</p></span><span class="row-arrow">${icons.arrow}</span></button>`;
  }
  function renderReview() {
    if (!app.lessons.length) {
      $('#screen-review').innerHTML = `<span class="page-eyebrow">A MOMENT TO REMEMBER</span><h1 class="page-heading" id="review-heading">Room for new memories.</h1><p class="page-intro">Your review queue will begin after you add and watch a lesson.</p><div class="surface-card review-hero"><span class="hero-orbit" aria-hidden="true"></span><div class="hero-count">0</div><p class="hero-subtitle">lessons on this device</p><p class="hero-detail">Import a lesson package to start. Your answers will guide its review schedule.</p><button class="primary-button full-width" type="button" data-action="import-pack">Import lesson package ${icons.arrow}</button></div><div class="inline-note">${icons.lock}<span>Your learning stays on this device. An empty collection does not change any history restored from a backup.</span></div>`;
      return;
    }
    const due = L.due(app.lessons);
    const started = app.lessons.filter(lesson => L.get(lesson.id).enrolledAt);
    $('#screen-review').innerHTML = `<span class="page-eyebrow">A MOMENT TO REMEMBER</span><h1 class="page-heading" id="review-heading">Due reviews.</h1><p class="page-intro">Start with the question. Let your memory do the work before the explanation.</p><div class="surface-card review-hero"><span class="hero-orbit" aria-hidden="true"></span><div class="hero-count">${due.length}</div><p class="hero-subtitle">${due.length === 1 ? 'lesson ready for recall' : 'lessons ready for recall'}</p><p class="hero-detail">${due.length ? 'These are due now, according to your review history.' : started.length ? 'Your next reviews will appear here when they are due.' : 'Your queue begins after you spend time with a lesson.'}</p><button class="primary-button full-width" type="button" data-action="${due.length ? 'start-review' : 'go-feed'}">${due.length ? 'Begin recall' : 'Explore your lessons'} ${icons.arrow}</button></div>${due.length ? `<div class="section-title"><h2>Due now</h2><span>${due.length} ${due.length === 1 ? 'lesson' : 'lessons'}</span></div><div class="lesson-list">${due.map(x => lessonRow(x, 'review-lesson', 'Ready to recall')).join('')}</div>` : ''}<div class="section-title"><h2>Practise anytime</h2><span>No schedule changes</span></div><div class="lesson-list">${app.lessons.map(x => lessonRow(x, 'practice-lesson', 'Quick question')).join('')}</div><div class="inline-note">${icons.recall}<span>Watching adds a lesson to your collection. Answers guide its review schedule. A replay or a like never counts as a correct answer.</span></div>`;
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
    $('#screen-settings').innerHTML = `<span class="page-eyebrow">MAKE IT YOURS</span><h1 class="page-heading" id="settings-heading">Your learning rhythm.</h1><p class="page-intro">Tune the pace. Keep control of your collection.</p>${app.collectionWarnings.length ? `<div class="collection-warning" role="status"><strong>Package needs attention</strong>${app.collectionWarnings.map(message => `<p>${esc(message)}</p>`).join('')}</div>` : ''}<section class="setting-section"><h2>Spaced recall</h2><div class="settings-card">${settingsAction('retention', 'Target recall', 'Higher targets generally mean more reviews.', `${Math.round((settings().retention || .9) * 100)}%`)}${settingsAction('new-limit', 'New lessons each day', 'A comfortable limit for the For you feed.', String(settings().newPerDay ?? 10))}${settingsAction('daily-topics', 'Daily lesson topics', 'Choose All, specialties, or several topic tags.', dailyTopicSummary())}</div></section><section class="setting-section"><h2>Playback</h2><div class="settings-card">${settingsAction('speed', 'Playback speed', 'Visuals follow the narration at every speed.', `${settings().speed || 1}×`)}${toggleRow('autoPlay', 'Autoplay lessons', 'Start narration when you enter a lesson.')}${toggleRow('reduceMotion', 'Reduce camera motion', 'Keep the memory scene steady.')}</div></section><section class="setting-section"><h2>Collection & updates</h2><div class="settings-card">${settingsAction('import-pack', 'Import lesson package', 'Add a ZIP from your device.')}${settingsAction('check-updates', 'Check for updates', app.catalogCheckedAt ? `Last checked ${dateLabel(app.catalogCheckedAt)}` : 'Find new content packages and app releases.')}${toggleRow('autoCheckUpdates', 'Check when opening', 'Check the catalog when a connection is available.')}</div></section><section class="setting-section"><h2>Your data</h2><div class="settings-card">${settingsAction('export-backup', 'Export learning backup', 'Save reviews, private notes and preferences.')}${settingsAction('import-backup', 'Restore learning backup', 'Restore a saved snapshot without removing media.')}${settingsAction('feedback-history', 'Reports & hidden lessons', 'Export feedback or restore a hidden lesson.')}${settingsAction('local-info', 'Stored on this device', `${app.lessons.length} lessons · No account required`)}</div></section><section class="setting-section"><h2>About</h2><div class="settings-card">${settingsAction('licenses', 'Open-source licenses', 'App credits and licenses, available offline.')}</div></section><p class="app-version">InstaAnki ${esc(app.info.version || '0.2.0')} · Personal learning<br>English · ${native ? 'Android' : 'Browser preview'}</p>`;
  }
  function openModal(kind, title, eyebrow, html, extra = {}) {
    const wasOpen = !!app.modal;
    if (!wasOpen) { app.previousFocus = document.activeElement; app.resumeOnClose = !audio.paused && kind !== 'quiz'; }
    pauseAudio();
    app.modal = { kind, ...extra };
    syncImmersive();
    $('#modal-sheet').dataset.kind = kind;
    $('#modal-backdrop').dataset.kind = kind;
    const quizLesson = kind === 'quiz' ? byId(extra.lessonId) : null;
    const quizPoster = quizLesson ? asset(quizLesson.poster, quizLesson._baseUrl) : '';
    $('#modal-backdrop').style.setProperty('--quiz-poster', quizPoster ? `url(${JSON.stringify(quizPoster)})` : 'none');
    $('#modal-actions').replaceChildren(); $('#modal-actions').hidden = true;
    $('#modal-title').textContent = title; $('#modal-eyebrow').textContent = eyebrow || '';
    $('#modal-body').innerHTML = html; $('#modal-backdrop').hidden = false; $('#app-shell').inert = true;
    document.body.classList.add('no-scroll');
    requestAnimationFrame(() => { const focus = $('#modal-body [autofocus]') || $('#modal-sheet'); focus.focus(); });
    updatePlayButtons();
  }
  function closeModal(resume = true) {
    if (!app.modal) return;
    if (app.modal.kind === 'quiz') preserveQuizState();
    const shouldResume = resume && app.resumeOnClose;
    app.modal = null; app.resumeOnClose = false;
    syncImmersive();
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
  const feedbackReasons = [
    ['bad_sound', 'Sound or audio'], ['bad_images', 'Images'],
    ['bad_timing', 'Timing or sync'], ['bad_mcq', 'Question or answer'],
    ['wrong_source', 'Wrong source'], ['other', 'Something else'],
  ];
  function showReport() {
    const lesson = current(); if (!lesson) return;
    const record = L.get(lesson.id);
    openModal('feedback', 'Help improve this lesson.', 'DISLIKE & REPORT', `<p class="modal-intro">${esc(lesson.title)}<br>Your choices stay on this device. You can export a report when you choose.</p><fieldset class="feedback-reasons"><legend>What needs attention?</legend>${feedbackReasons.map(([value, label]) => `<label class="feedback-choice"><input type="radio" name="feedback-reason" value="${value}"><span>${label}</span></label>`).join('')}</fieldset><label class="field-label" for="feedback-comment">Comment <span class="field-hint">(optional)</span></label><textarea id="feedback-comment" class="textarea" maxlength="4000" placeholder="Tell us what happened, or which moment needs checking."></textarea><label class="feedback-toggle"><input type="checkbox" id="feedback-save-report" checked><span>Save a local report<small>Includes the lesson, version and source reference.</small></span></label><label class="feedback-toggle"><input type="checkbox" id="feedback-dislike" ${record.disliked ? 'checked' : ''}><span>Mark this lesson as disliked</span></label><label class="feedback-toggle"><input type="checkbox" id="feedback-hide" ${record.hidden ? 'checked' : ''}><span>Hide this lesson<small>You can restore it in Settings. Your review history is kept.</small></span></label><div class="feedback-controls"><button class="primary-button full-width" type="button" data-action="save-feedback">Save choices</button><button class="quiet-button full-width" type="button" data-action="feedback-history">View saved reports</button></div>`, { lessonId: lesson.id });
    $('#modal-actions').append($('.feedback-controls', $('#modal-body'))); $('#modal-actions').hidden = false;
  }
  function saveFeedback() {
    if (app.modal?.kind !== 'feedback') return;
    const lesson = byId(app.modal.lessonId); if (!lesson) return;
    const report = $('#feedback-save-report').checked;
    const reason = $('input[name="feedback-reason"]:checked')?.value;
    if (report && !reason) { toast('Choose what needs attention, or turn off Save a local report.'); $('.feedback-reasons input')?.focus(); return; }
    const hidden = $('#feedback-hide').checked;
    const disliked = $('#feedback-dislike').checked;
    const hashes = { ...(lesson.assetHashes || {}), ...(lesson._assetHashes || {}) };
    for (const [path, item] of Object.entries(lesson.visualGuidance?.images || {})) if (/^[a-f0-9]{64}$/i.test(item.sha256 || '')) hashes[path] = item.sha256;
    for (const image of [...(lesson.realImages || []), ...(lesson.presentation?.clinicalGallery?.images || [])]) if (/^[a-f0-9]{64}$/i.test(image.sha256 || '')) hashes[image.url] = image.sha256;
    const safeHashes = Object.fromEntries(Object.entries(hashes).filter(([path, hash]) => /^[A-Za-z0-9][A-Za-z0-9._/-]{0,319}$/.test(path) && !path.split('/').some(part => !part || ['.', '..', '__proto__', 'constructor', 'prototype'].includes(part)) && /^[a-f0-9]{64}$/i.test(hash)).slice(0, 200));
    if (report) L.reportFeedback(lesson.id, { reason, comment: $('#feedback-comment').value.trim(), lessonVersion: lesson.version || 1, source: lesson.source || {}, assetHashes: safeHashes });
    L.setDisliked(lesson.id, disliked); L.setHidden(lesson.id, hidden);
    closeModal(false);
    if (hidden) { rebuildFeed(); if (settings().autoPlay && current()) playAudio(false); }
    syncIndicators();
    toast(hidden ? 'Lesson hidden. Your learning history is kept.' : report ? 'Report saved on this device. Export it from Settings when ready.' : 'Your lesson preferences were saved.');
  }
  function showFeedbackHistory() {
    const reports = L.getFeedback();
    const hidden = app.lessons.filter(lesson => L.get(lesson.id).hidden);
    openModal('feedback-history', 'Your reports & hidden lessons.', 'YOUR FEEDBACK', `<p class="modal-intro">Reports stay on this device until you export them. Exports contain your reports and lesson references.</p><button class="primary-button full-width" type="button" data-action="export-feedback" ${reports.length ? '' : 'disabled'}>${native?.shareFeedback ? 'Share' : 'Export'} ${reports.length} ${reports.length === 1 ? 'report' : 'reports'}</button>${native?.exportFeedback ? `<button class="secondary-button full-width" type="button" data-action="save-feedback-file" ${reports.length ? '' : 'disabled'} style="margin-top:10px">Save feedback file</button>` : ''}<h3>Hidden lessons · ${hidden.length}</h3>${hidden.length ? hidden.map(lesson => `<div class="hidden-lesson-row"><span>${esc(lesson.title)}</span><button class="secondary-button" type="button" data-unhide-lesson="${esc(lesson.id)}">Restore</button></div>`).join('') : '<p class="empty-copy">No lessons are hidden.</p>'}<h3>Saved reports · ${reports.length}</h3>${reports.length ? reports.slice().reverse().map(report => `<div class="feedback-report"><strong>${esc(feedbackReasons.find(([key]) => key === report.reason)?.[1] || report.reason)} · ${esc(byId(report.lessonId)?.title || report.lessonId)}</strong><p>${esc(dateLabel(report.createdAt))} · Version ${esc(report.lessonVersion || 'unknown')}</p>${report.comment ? `<p>${esc(report.comment)}</p>` : ''}</div>`).join('') : '<p class="empty-copy">Use Report on a lesson to save feedback.</p>'}`);
  }
  async function exportFeedback() {
    if (await L.shareFeedback()) return;
    downloadJSON(JSON.parse(L.exportFeedback()), `InstaAnki-feedback-${new Date().toISOString().slice(0, 10)}.json`);
    toast('Your feedback export is ready to save.');
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
    const images = [...new Map([...(lesson.realImages || []), ...(lesson.presentation?.clinicalGallery?.images || [])].map(image => [image.url, image])).values()];
    openModal('source', imagesOnly ? 'The real-world view.' : 'Trace it to the source.', imagesOnly ? 'IMAGE CREDITS' : 'LESSON REFERENCES', `${imagesOnly ? '' : lessonSources}${images.map(image => imageCredit(image, lesson._baseUrl)).join('')}`);
  }
  function isProductionPaused(book) {
    return app.bundledBooks.find(item => item.id === book.id)?.productionPaused === true;
  }
  function showBook(id) {
    refreshProductionProgress();
    const book = app.books.find(item => item.id === id); if (!book) return;
    const questions = book.questions || [];
    const paused = isProductionPaused(book);
    const installed = app.lessons.filter(lesson => lesson.source?.bookId === id).length;
    openModal('book', book.title, 'PUBLICATION PROGRESS', `<p class="modal-intro">${esc(book.author)} · ${esc(book.year)}<br>${Number(book.completedVideos) || 0} lessons historically produced from ${Number(book.totalQuestions) || 0} source questions.<br><strong>${installed} ${installed === 1 ? 'lesson' : 'lessons'} on this device.</strong></p><div class="source-block"><h3>${paused ? 'New lesson production is paused.' : `Next question to produce: ${book.nextQuestionNumber ? `Q${esc(book.nextQuestionNumber)}` : 'All source questions covered'}`}</h3><p>${paused ? 'Work is limited to app and existing-lesson repairs. Source questions remain listed for reference.' : 'Completed questions are tracked individually. Skipped question numbers remain in the production plan.'}</p><button class="quiet-button" type="button" data-copy-plan="${esc(book.id)}">${paused ? 'Copy collection brief' : 'Copy the next-batch brief'} ↗</button></div><div class="question-key"><span><i class="done"></i>Historically produced</span><span><i></i>Not yet produced</span></div><div class="question-grid">${questions.map(q => `<button class="question-cell ${q.status === 'produced' ? 'produced' : q.status === 'needs_review' ? 'needs-review' : ''}" type="button" data-question="${q.number}" data-question-book="${esc(book.id)}" aria-label="Question ${q.number}, ${q.status === 'produced' ? 'lesson produced' : q.status === 'needs_review' ? 'source needs review' : 'not yet produced'}">${q.number}</button>`).join('')}</div>`, { bookId: id });
  }
  function quizMode(lesson, requested) {
    if (requested === 'practice') return 'practice';
    const record = L.get(lesson.id);
    const due = record.card?.due ? new Date(record.card.due).getTime() : 0;
    return due > Date.now() ? 'practice' : 'review';
  }
  function quizSnapshot(state) {
    return { ...state, returnLocation: state.returnLocation ? { ...state.returnLocation, feedIds: [...(state.returnLocation.feedIds || [])] } : null, reviewSeen: [...(state.reviewSeen || [])] };
  }
  function notifyLessonFlow() {
    if (typeof syncLessonFlow === 'function') syncLessonFlow();
  }
  function preserveQuizState() {
    if (app.modal?.kind !== 'quiz') return;
    const state = quizSnapshot(app.modal);
    if (state.answered) app.lastQuestionResult = state;
    else app.pendingQuestion = state;
    notifyLessonFlow();
  }
  function openQuizState(state) {
    const lesson = byId(state?.lessonId);
    if (!lesson?.quiz?.options?.length) return false;
    const title = state.questionKind === 'new' ? 'New lesson question' : state.questionKind === 'due' ? 'Due review' : 'Practice question';
    const eyebrow = state.answered ? 'ANSWER RESULT' : state.questionKind === 'due' ? 'REVIEW DUE · ANSWER FIRST' : state.questionKind === 'new' ? 'LESSON QUESTION' : 'NO SCHEDULE CHANGE';
    app.resumeOnClose = false;
    openModal('quiz', title, eyebrow, '', quizSnapshot(state));
    app.resumeOnClose = false;
    if (app.modal.answered) app.lastQuestionResult = quizSnapshot(app.modal);
    else app.pendingQuestion = quizSnapshot(app.modal);
    renderQuiz();
    $('#modal-body').scrollTop = 0;
    requestAnimationFrame(() => {
      if (app.modal?.attemptId !== state.attemptId) return;
      if (app.modal.answered) $('.quiz-result')?.scrollIntoView({ behavior: 'auto', block: 'nearest' });
      else $('#modal-body').scrollTop = 0;
    });
    notifyLessonFlow();
    return true;
  }
  function resumePendingQuestion(id = current()?.id) {
    const context = app.explanationContext;
    const state = context?.lessonId === id && !context.question?.answered ? context.question : app.pendingQuestion;
    if (!state || state.lessonId !== id || state.answered) return false;
    if (context?.lessonId === id) app.explanationContext = null;
    return openQuizState(state);
  }
  function resumeLastQuestionResult(id = current()?.id) {
    const state = app.lastQuestionResult;
    if (!state || state.lessonId !== id || !state.answered) return false;
    if (app.explanationContext?.lessonId === id) app.explanationContext = null;
    return openQuizState(state);
  }
  function finishLessonPlayback() {
    const lesson = current(); if (!lesson) return;
    const context = app.explanationContext;
    if (context?.lessonId === lesson.id && context.question) {
      app.explanationContext = null;
      openQuizState(context.question);
      return;
    }
    if (context) app.explanationContext = null;
    if (resumePendingQuestion(lesson.id) || resumeLastQuestionResult(lesson.id)) return;
    const assisted = app.entryWasDue && app.bypassEntryRecall;
    showQuiz(lesson, assisted ? 'practice' : 'review', 'feed', { assisted });
  }
  function selectQuizAnswer(index) {
    const state = app.modal, lesson = byId(state?.lessonId);
    if (state?.kind !== 'quiz' || state.answered || !lesson?.quiz || !Number.isInteger(index) || index < 0 || index >= lesson.quiz.options.length) return;
    state.selected = index;
    state.dontKnow = false;
    $$('[data-answer]', $('#modal-body')).forEach(button => {
      const selected = Number(button.dataset.answer) === index;
      button.classList.toggle('selected', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
    $('[data-action="submit-answer"]', $('#modal-sheet')).disabled = false;
    app.pendingQuestion = quizSnapshot(state);
  }
  function restoreQuizLocation(state) {
    const location = state.returnLocation;
    const tab = state.origin === 'review' ? 'review' : location?.tab || 'feed';
    if (tab !== 'feed') { showTab(tab, false); return; }
    const savedFeed = location?.feedIds?.map(byId).filter(Boolean);
    const orderChanged = savedFeed?.length && savedFeed.map(item => item.id).join('|') !== app.feed.map(item => item.id).join('|');
    const changed = location && (orderChanged || app.feedMode !== location.feedMode || app.specialty !== location.specialty || app.tag !== location.tag || current()?.id !== state.lessonId);
    if (location) { app.feedMode = location.feedMode; app.specialty = location.specialty; app.tag = location.tag; }
    showTab('feed', false);
    if (changed) {
      app.bypassNextRecall = state.lessonId; rebuildFeed(state.lessonId);
      if (savedFeed?.length && savedFeed.some(item => item.id === state.lessonId)) {
        // Grading changes due-first ordering. Continue along the selection the
        // learner entered, instead of treating a replayed item as its new end.
        app.feed = savedFeed;
        app.bypassNextRecall = state.lessonId;
        setLesson(savedFeed.findIndex(item => item.id === state.lessonId), false);
      }
    }
    notifyLessonFlow();
  }
  function showQuiz(lesson, requested = 'review', origin = 'feed', options = {}) {
    if (!lesson?.quiz?.options?.length) { toast('This lesson does not include a recall question.'); return; }
    // An interrupted question keeps its attempt. Explicit practice starts a new
    // practice attempt and can never inherit a scheduled-review mode.
    if (requested !== 'practice' && app.pendingQuestion?.lessonId === lesson.id && !app.pendingQuestion.answered) {
      openQuizState(app.pendingQuestion); return;
    }
    const mode = quizMode(lesson, requested);
    const hasReviewed = Number(L.get(lesson.id).card?.reps) > 0;
    const attemptId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const state = {
      kind: 'quiz', lessonId: lesson.id, mode, origin, attemptId, selected: -1, answered: false,
      questionKind: mode === 'practice' ? 'practice' : hasReviewed ? 'due' : 'new',
      assisted: !!options.assisted,
      returnLocation: options.returnLocation || { tab: app.tab, feedMode: app.feedMode, specialty: app.specialty, tag: app.tag, lessonId: current()?.id, feedIndex: app.index, feedLength: app.feed.length, feedIds: app.feed.map(item => item.id) },
      reviewSeen: [...(options.reviewSeen || [])],
    };
    if (app.lastQuestionResult?.lessonId === lesson.id) app.lastQuestionResult = null;
    app.explanationContext = null;
    openQuizState(state);
  }
  function renderQuiz() {
    const state = app.modal; const lesson = byId(state?.lessonId); if (!lesson) return;
    const quiz = lesson.quiz;
    const result = state.result;
    const steps = state.questionKind === 'new' ? ['Watch', 'Answer', 'Result'] : ['Answer', 'Result', state.origin === 'review' ? 'Next review' : 'Done'];
    const step = state.questionKind === 'new' ? state.answered ? 2 : 1 : state.answered ? 1 : 0;
    const context = state.assisted ? 'You watched the explanation. This is practice; your due review stays in the review list.' : state.questionKind === 'due' ? 'This review is due. Answer from memory before replaying the video.' : state.mode === 'practice' ? 'Practice only. This answer will not change your review date.' : 'Choose one answer to finish this lesson, then check it.';
    const seen = new Set([...(state.reviewSeen || []), state.lessonId]);
    const nextReview = state.origin === 'review' && L.due(app.lessons).some(item => !seen.has(item.id));
    const hasNextLesson = (state.returnLocation?.feedIndex ?? app.index) < (state.returnLocation?.feedLength ?? app.feed.length) - 1;
    const continueLabel = state.origin === 'review' ? nextReview ? 'Next review' : 'Back to review' : state.origin === 'practice' ? state.returnLocation?.tab === 'review' ? 'Back to review' : 'Return to video' : hasNextLesson ? state.returnLocation?.feedMode === 'due' ? 'Next review' : 'Next lesson' : state.returnLocation?.feedMode === 'due' ? 'Finish review' : 'Finish lesson';
    const schedule = state.assisted ? 'Practice recorded. This review is still due for an answer from memory.' : state.mode === 'practice' || result?.practice || (state.answered && !result?.scheduled) ? 'Practice recorded. Your review schedule has not changed.' : state.answered ? `Answer saved. Next review: ${dateLabel(result.due)}` : '';
    const optionList = `${state.answered ? '' : `<p class="quiz-choice-count">Choose 1 of ${quiz.options.length} answers</p>`}<div class="quiz-options" role="group" aria-label="${state.answered ? 'Answer options' : `Choose 1 of ${quiz.options.length} answers`}">${quiz.options.map((option, index) => `<button type="button" class="quiz-option ${state.selected === index ? 'selected' : ''} ${state.answered && index === quiz.correctIndex ? 'correct' : ''} ${state.answered && state.selected === index && index !== quiz.correctIndex ? 'incorrect' : ''}" data-answer="${index}" aria-pressed="${state.selected === index}" ${state.answered ? 'disabled' : ''}><span class="option-letter">${String.fromCharCode(65 + index)}</span><span class="option-text">${esc(option)}${state.answered && index === quiz.correctIndex ? '<small class="answer-marker">Correct answer</small>' : state.answered && state.selected === index ? '<small class="answer-marker">Your answer</small>' : ''}</span></button>`).join('')}</div>`;
    const resultPanel = state.answered ? `<div class="quiz-result ${result.correct ? '' : 'missed'}" role="status" tabindex="-1"><h3>${result.correct ? 'Correct' : state.dontKnow ? 'Answer explained' : 'Incorrect'}</h3><p class="correct-answer"><strong>Correct answer:</strong> ${String.fromCharCode(65 + quiz.correctIndex)}. ${esc(quiz.options[quiz.correctIndex])}</p><p>${esc(quiz.explanation)}</p><span class="schedule-note">${esc(schedule)}</span></div><details class="answered-options"><summary>View all answer options</summary>${optionList}</details>` : optionList;
    const actions = state.answered ? `<div class="quiz-actions"><button type="button" class="primary-button full-width" data-action="quiz-continue">${continueLabel} ${icons.arrow}</button><button type="button" class="secondary-button full-width" data-watch-lesson="${esc(lesson.id)}">Replay video</button></div>` : `<div class="quiz-actions"><button type="button" class="primary-button full-width" data-action="submit-answer" ${state.selected < 0 ? 'disabled' : ''}>Check my answer</button><button type="button" class="secondary-button full-width" data-action="dont-know">I don’t know yet</button><button type="button" class="quiet-button full-width" data-watch-lesson="${esc(lesson.id)}">${L.get(lesson.id).watchedSeconds > 0 ? 'Replay video' : 'Watch video first'}</button></div>`;
    $('#modal-body').innerHTML = `<ol class="lesson-steps quiz-steps" aria-label="Lesson progress">${steps.map((label, index) => `<li class="${index < step ? 'is-complete' : index === step ? 'is-current' : ''}" ${index === step ? 'aria-current="step"' : ''}><span>${index + 1}</span>${esc(label)}</li>`).join('')}</ol><h3 class="quiz-lesson-title">${esc(lesson.title)}</h3>${state.answered ? '' : `<p class="quiz-context-note">${esc(context)}</p>`}<p class="quiz-prompt">${esc(quiz.prompt)}</p>${resultPanel}${actions}`;
    const footer = $('#modal-actions'), controls = $('.quiz-actions', $('#modal-body'));
    if (footer && controls) { footer.replaceChildren(controls); footer.hidden = false; }
  }
  function submitAnswer(dontKnow = false) {
    const state = app.modal; if (state?.kind !== 'quiz' || state.answered || (!dontKnow && state.selected < 0)) return;
    if (L.loadError) { toast('Restore your learning backup before recording an answer.'); return; }
    const lesson = byId(state.lessonId);
    try {
      state.result = L.grade(lesson.id, dontKnow ? false : state.selected === lesson.quiz.correctIndex, state.attemptId, state.mode);
      if (dontKnow) { state.selected = -1; state.dontKnow = true; }
      state.answered = true;
      if (app.pendingQuestion?.attemptId === state.attemptId) app.pendingQuestion = null;
      app.lastQuestionResult = quizSnapshot(state);
      renderQuiz(); syncIndicators(); notifyLessonFlow();
      $('#modal-eyebrow').textContent = 'ANSWER RESULT';
      $('.quiz-result')?.focus({ preventScroll: true });
      $('.quiz-result')?.scrollIntoView({ behavior: settings().reduceMotion ? 'auto' : 'smooth', block: 'nearest' });
    } catch (error) { toast(error.message || 'Your answer could not be saved.'); }
  }
  function continueQuiz() {
    const state = app.modal; if (state?.kind !== 'quiz' || !state.answered) return;
    closeModal(false);
    if (state.origin === 'review') {
      const seen = [...new Set([...(state.reviewSeen || []), state.lessonId])];
      const due = L.due(app.lessons);
      const next = due.find(x => !seen.includes(x.id));
      showTab('review', false);
      if (next) showQuiz(next, 'review', 'review', { reviewSeen: seen, returnLocation: state.returnLocation });
      else toast(due.length ? 'Session finished. Items still due remain in your review list.' : 'Your due review session is complete.');
    } else {
      restoreQuizLocation(state);
      if (state.origin === 'feed') nextLesson();
    }
  }
  function watchLesson(id) {
    const active = app.modal?.kind === 'quiz' && app.modal.lessonId === id ? app.modal : null;
    const saved = active || (app.pendingQuestion?.lessonId === id ? app.pendingQuestion : app.lastQuestionResult?.lessonId === id ? app.lastQuestionResult : null);
    if (saved) {
      const card = L.get(id).card;
      // Once a due explanation is revealed, the preserved attempt is assisted
      // practice. Replaying an answered question keeps its original result.
      if (!saved.answered && Number(card?.reps) > 0 && new Date(card.due).getTime() <= Date.now()) {
        saved.mode = 'practice'; saved.questionKind = 'practice'; saved.assisted = true;
      }
      app.explanationContext = { lessonId: id, question: quizSnapshot(saved) };
      if (!saved.answered) app.pendingQuestion = quizSnapshot(saved);
    } else app.explanationContext = null;
    closeModal(false); app.feedMode = 'all'; app.specialty = ''; app.tag = '';
    app.bypassNextRecall = id;
    showTab('feed', false); rebuildFeed(id);
    if (!current() || current().id !== id) { const lesson = byId(id); if (lesson) { app.feed = [lesson, ...app.feed.filter(x => x.id !== id)]; app.index = 0; app.bypassNextRecall = id; setLesson(0, true); } }
    else playAudio(false);
    notifyLessonFlow();
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
  function dailyTopicSummary() {
    const ids = settings().dailyTopicIds || [];
    return !ids.length ? 'All' : ids.length === 1 ? app.topicModel?.get(ids[0])?.label || '1 tag' : `${ids.length} tags`;
  }
  function updateTopicCount() {
    const count = app.topicModel?.filterLessons(app.lessons, app.topicDraft).length || 0;
    $('#daily-topic-count').textContent = `${count} available ${count === 1 ? 'lesson' : 'lessons'} · Up to ${settings().newPerDay || 10} new each day`;
    const all = $('[data-action="daily-topics-all"]');
    all.classList.toggle('selected', !app.topicDraft.length); all.setAttribute('aria-pressed', String(!app.topicDraft.length));
  }
  function renderTopicOptions() {
    const query = $('#daily-topic-search')?.value.trim() || '';
    const selected = new Set(app.topicDraft);
    const renderNode = (node, depth = 0) => {
      const count = app.topicModel.filterLessons(app.lessons, [node.id]).length;
      const children = node.children || [];
      return `<div class="daily-topic-node"><label class="daily-topic-option"><input type="checkbox" data-daily-tag="${esc(node.id)}" ${selected.has(node.id) ? 'checked' : ''}><span><strong>${esc(node.label)}</strong><small>${children.length ? 'Includes its subtopics' : esc(node.facet || 'Topic')}</small></span><em>${count}</em></label>${children.length ? `<details class="daily-topic-children" ${query ? 'open' : ''}><summary>Browse ${children.length} ${children.length === 1 ? 'topic' : 'topics'}</summary>${children.map(child => renderNode(child, depth + 1)).join('')}</details>` : ''}</div>`;
    };
    const nodes = app.topicModel?.tree(query) || [];
    $('#daily-topic-options').innerHTML = nodes.length ? nodes.map(node => renderNode(node)).join('') : '<p class="empty-copy">No tags match that search.</p>';
    const unavailable = app.topicDraft.filter(id => !app.topicModel?.get(id));
    $('#daily-topic-unavailable').innerHTML = unavailable.length ? `<p class="field-hint">These saved tags are unavailable. Remove them or choose All.</p>${unavailable.map(id => `<button type="button" class="topic-unavailable" data-remove-daily-tag="${esc(id)}">${esc(id)} <span aria-hidden="true">×</span><span class="visually-hidden">Remove tag</span></button>`).join('')}` : '';
    updateTopicCount();
  }
  function showDailyTopics() {
    app.topicDraft = [...(settings().dailyTopicIds || [])];
    openModal('daily-topics', 'Choose your daily topics.', 'SPACED RECALL', `<p class="modal-intro">Choose one or more specialties or topic tags for your For you feed. A parent tag includes its subtopics. Your choice is saved on this device.</p><button type="button" class="choice-button daily-topics-all" data-action="daily-topics-all" aria-pressed="false">All <span>Every topic</span></button><label class="visually-hidden" for="daily-topic-search">Search topic tags</label><input id="daily-topic-search" class="text-field" type="search" placeholder="Search specialties or subtopics…" autocomplete="off"><p id="daily-topic-count" class="field-hint" aria-live="polite"></p><div id="daily-topic-unavailable"></div><div id="daily-topic-options" class="daily-topic-options"></div><div class="daily-topic-footer"><button class="primary-button full-width" type="button" data-action="save-daily-topics">Save selection</button><p class="field-hint">The Due tab keeps all scheduled reviews available.</p></div>`);
    renderTopicOptions();
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
    const generation = ++app.collectionGeneration;
    const clone = value => JSON.parse(JSON.stringify(value));
    const lessons = new Map(clone(app.bundledLessons).map(lesson => [lesson.id, lesson]));
    const books = new Map(clone(app.bundledBooks).map(book => [book.id, book]));
    const allowedBooks = new Map(app.bundledBooks.map(book => [book.id, book]));
    const warnings = [];
    const previousLessons = new Map(app.lessons.map(lesson => [lesson.id, lesson]));
    const packs = native?.listPacks ? JSON.parse(native.listPacks() || '[]') : [];
    if (!Array.isArray(packs)) throw new Error('The installed package list could not be read. Reopen the app and try again.');
    for (const pack of packs) {
      try {
        if (!pack?.manifest || !pack.baseUrl) throw new Error('Missing content package metadata.');
        const data = Array.isArray(pack.manifest.lessons) ? pack.manifest.lessons : await fetchJSON(new URL(pack.manifest.lessonsFile || 'lessons.json', pack.baseUrl));
        const imported = Array.isArray(data) ? data : data.lessons;
        if (!Array.isArray(imported) || imported.some(x => !validLesson(x))) throw new Error('The lesson package uses an unsupported lesson format.');
        const publications = Array.isArray(pack.manifest.books) ? pack.manifest.books : [];
        if (imported.some(lesson => !allowedBooks.has(lesson.source?.bookId)) || publications.some(book => !allowedBooks.has(book.id))) {
          throw new Error('A package from a different book is hidden. This collection accepts only the original bundled publication. Its files and your learning history are preserved.');
        }
        for (const book of publications) {
          const original = allowedBooks.get(book.id);
          if (['title', 'author', 'year', 'totalQuestions'].some(key => book[key] != null && String(book[key]) !== String(original[key]))) throw new Error('A package has publication details that do not match the original book. It is hidden; its files and your learning history are preserved.');
        }
        for (const lesson of imported) {
          const previous = lessons.get(lesson.id);
          const paths = new Set([lesson.audioUrl, lesson.poster, ...(lesson.scenes || []).map(scene => scene.image), ...(lesson.realImages || []).map(image => image.url), ...(lesson.presentation?.clinicalGallery?.images || []).map(image => image.url)]);
          const hashes = Object.fromEntries(Object.entries(pack.manifest.sha256 || {}).filter(([path, hash]) => paths.has(path) && /^[a-f0-9]{64}$/i.test(hash)));
          const item = { ...clone(lesson), _baseUrl: pack.baseUrl, _assetHashes: hashes };
          if (!previous || Number(item.version || 1) >= Number(previous.version || 1)) lessons.set(item.id, item);
        }
        for (const book of publications) {
          const previous = books.get(book.id);
          const item = { ...previous, ...clone(book), _baseUrl: pack.baseUrl };
          if (!book.coverUrl && previous?.coverUrl) item.coverUrl = asset(previous.coverUrl, previous._baseUrl);
          books.set(item.id, item);
        }
      } catch (error) { console.warn('A content pack could not be loaded:', error); warnings.push(error.message || 'One content package could not be read. The rest of your collection is available.'); }
    }
    // Commit one fresh catalog. Removed/replaced packs cannot leave stale books
    // or lessons behind, and an older in-flight import cannot undo a newer one.
    if (generation !== app.collectionGeneration) return false;
    app.lessons = [...lessons.values()]; app.books = [...books.values()]; app.collectionWarnings = [...new Set(warnings)];
    if (warnings.length) toast(app.collectionWarnings[0]);
    for (const key of ['pendingQuestion', 'lastQuestionResult', 'explanationContext']) {
      const id = app[key]?.lessonId;
      if (id && (!lessons.has(id) || JSON.stringify(previousLessons.get(id)?.quiz) !== JSON.stringify(lessons.get(id)?.quiz))) app[key] = null;
    }
    if (app.modal?.lessonId && (!lessons.has(app.modal.lessonId) || (app.modal.kind === 'quiz' && JSON.stringify(previousLessons.get(app.modal.lessonId)?.quiz) !== JSON.stringify(lessons.get(app.modal.lessonId)?.quiz)))) {
      const id = app.modal.lessonId; closeModal(false);
      if (app.pendingQuestion?.lessonId === id) app.pendingQuestion = null;
      if (app.lastQuestionResult?.lessonId === id) app.lastQuestionResult = null;
    }
    return true;
  }
  async function checkUpdates(interactive = true) {
    if (interactive) openModal('updates', 'Your collection, up to date.', 'CONTENT & APP', '<p class="modal-intro">Checking the release catalog…</p>');
    try {
      const catalog = await fetchJSON(CATALOG_URL);
      if (catalog.schemaVersion !== 1 || !Array.isArray(catalog.packs)) throw new Error('The catalog format is not supported by this app version.');
      app.catalog = catalog; app.catalogCheckedAt = new Date().toISOString();
      if (interactive && app.modal?.kind === 'updates') renderUpdates();
      else if (!app.modal && (appUpdateCandidate(catalog) || catalog.packs.some(pack => packTargetsApp(pack) && !packIsCurrent(pack)))) {
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
  function currentPackageName() { return app.info.packageName || 'com.instaanki.app'; }
  function isFreshApp() { return app.distribution?.profile === 'fresh' || currentPackageName() === 'com.instaanki.fresh'; }
  function packTargetsApp(pack) {
    // A shared catalog must not reintroduce the legacy starter collection into
    // the explicitly empty fresh app. Manual source-valid imports are separate.
    return !isFreshApp() || (Array.isArray(pack?.targetPackageNames) && pack.targetPackageNames.includes('com.instaanki.fresh'));
  }
  function appUpdateCandidate(catalog = app.catalog) {
    if (!catalog) return null;
    const identity = currentPackageName();
    const apps = Array.isArray(catalog.apps) ? catalog.apps : catalog.apps && typeof catalog.apps === 'object'
      ? Object.entries(catalog.apps).filter(([, value]) => value && typeof value === 'object').map(([name, value]) => ({ packageName: name, ...value })) : [];
    return [...apps, catalog.latestApp].filter(candidate => {
      if (!candidate || typeof candidate !== 'object' || !Number.isInteger(candidate.versionCode) || candidate.versionCode <= Number(app.info.versionCode || 1)) return false;
      if (candidate.packageName !== identity && !(identity === 'com.instaanki.app' && !isFreshApp() && candidate.packageName == null)) return false;
      try { return new URL(candidate.url).protocol === 'https:'; } catch (_) { return false; }
    }).sort((a, b) => b.versionCode - a.versionCode)[0] || null;
  }
  function packCompatibility(pack) {
    // The repaired app uses a separate catalog. Every offered package must
    // state its minimum explicitly; missing/invalid data is not permission to
    // send a newer content format to an older player.
    const minimum = pack.minAppVersionCode;
    if (!Number.isInteger(minimum) || minimum < 1 || minimum > 2147483647) {
      return { minimum: null, message: 'This package has a missing or invalid app-version requirement. Check for a corrected catalog before downloading.' };
    }
    const installed = app.info.versionCode;
    if (!Number.isInteger(installed) || installed < 1 || installed > 2147483647) {
      return { minimum, message: 'Your installed app version could not be verified. Reopen InstaAnki before downloading an update.' };
    }
    if (installed < minimum) {
      return { minimum, message: `This package requires InstaAnki app build ${minimum} or later. Your installed app is build ${installed}. Update the app first.` };
    }
    return { minimum, message: '' };
  }
  function packUpdateCard(pack) {
    const compatibility = packCompatibility(pack);
    return `<div class="update-card" data-update-pack="${esc(pack.id)}"><h3>${esc(pack.title)}</h3><p>Version ${esc(pack.version)} · ${amount(Number(pack.sizeBytes) || 0)}</p>${compatibility.message ? `<p class="update-requirement" role="status">${esc(compatibility.message)}</p><button class="secondary-button full-width" type="button" disabled>${compatibility.minimum == null ? 'Package unavailable' : 'App update required'}</button>` : `<button class="secondary-button full-width" type="button" data-download-pack="${esc(pack.id)}" ${app.downloading ? 'disabled' : ''}>Download and install</button>`}</div>`;
  }
  function renderUpdates() {
    const catalog = app.catalog; if (!catalog) return;
    const availableApp = appUpdateCandidate(catalog);
    const targeted = catalog.packs.filter(packTargetsApp);
    const packs = targeted.filter(pack => !packIsCurrent(pack));
    $('#modal-body').innerHTML = `<p class="modal-intro">Checked ${esc(dateLabel(app.catalogCheckedAt))}. Content downloads are separate from your installed app.</p>${availableApp ? `<div class="update-card"><h3>InstaAnki ${esc(availableApp.version)}</h3><p>${esc(availableApp.notes || 'An updated Android app is available.')}</p><button class="primary-button full-width" type="button" data-action="open-app-update">Open Android update ↗</button></div>` : '<div class="source-block"><h3>No newer app release listed.</h3><p>Your installed version is ' + esc(app.info.version) + '.</p></div>'}<h3>Available lesson packages</h3>${packs.length ? packs.map(packUpdateCard).join('') : `<p class="empty-copy">${targeted.length ? 'All published lessons in this catalog are already on this device.' : isFreshApp() ? 'No lesson packages are published for this fresh app yet. You can still choose a source-linked ZIP to import from your device.' : 'There are no downloadable packages in this catalog yet. You can still import a personal ZIP from your device.'}</p>`}<div id="download-progress" class="download-progress" ${app.downloading ? '' : 'hidden'}><span>Preparing download…</span><div class="progress-track"><div class="progress-fill" style="width:0%"></div></div></div>`;
  }
  function downloadPack(id) {
    const pack = app.catalog?.packs.find(x => x.id === id); if (!pack) return;
    if (!packTargetsApp(pack)) { toast('This package is not published for the fresh app. Choose a compatible package or import a source-linked ZIP yourself.'); return; }
    const compatibility = packCompatibility(pack);
    if (compatibility.message) { toast(compatibility.message); return; }
    if (!native?.downloadPack && !native?.downloadPackVerified && !native?.downloadPackCompatible) { toast('Install the Android app to download and install a lesson package.'); return; }
    if (!/^[a-f0-9]{64}$/i.test(pack.sha256 || '') || !pack.url) { toast('This package is missing a valid download checksum.'); return; }
    if (native.downloadPackCompatible && (!Number.isSafeInteger(pack.sizeBytes) || pack.sizeBytes < 1)) { toast('This package is missing a valid download size. Check for a corrected catalog before downloading.'); return; }
    app.downloading = true; renderUpdates();
    if (native.downloadPackCompatible) native.downloadPackCompatible(pack.url, pack.sha256, pack.sizeBytes, compatibility.minimum);
    else if (native.downloadPackVerified && Number.isSafeInteger(pack.sizeBytes) && pack.sizeBytes > 0) native.downloadPackVerified(pack.url, pack.sha256, pack.sizeBytes);
    else native.downloadPack(pack.url, pack.sha256);
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
    const paused = isProductionPaused(book);
    const existing = app.lessons.filter(lesson => lesson.source?.bookId === book.id).map(lesson => lesson.id);
    const text = paused
      ? `${existing.length ? `Repair the InstaAnki app and its existing ${existing.length} lessons only.` : 'Repair the InstaAnki app only. This fresh collection has no installed lessons.'}\nDo not create new videos, lessons, narration, or mnemonic artwork until an explicit new user request.\nOriginal publication: ${book.title} (${book.author}, ${book.year}).\nBook ID: ${book.id}\nProduced source question numbers: ${done.join(', ') || 'none'}.\nExisting lesson IDs: ${existing.join(', ') || 'none'}.\nHistorical produced lesson IDs: ${(book.questions || []).filter(q => q.status === 'produced' && q.lessonId).map(q => q.lessonId).join(', ') || 'none'}.\nKeep the original book as the only active publication. Preserve lesson IDs, reviews, private notes, preferences, source references, and produced counts.\nAllowed work: app errors, interface and playback repairs, lossless media optimization, feedback, and update delivery.\n${remaining.length} source questions remain unproduced; new production is paused.`
      : `Continue the InstaAnki collection for ${book.title} (${book.author}, ${book.year}).\nBook ID: ${book.id}\nCompleted source question numbers: ${done.join(', ') || 'none'}.\n${remaining.length} source questions remain.\nNext batch: ${remaining.slice(0, 10).map(n => `Q${n}`).join(', ')}.\nKeep stable lesson IDs, English narration, source references, licensed real clinical images, and the existing JSON content format. Use the original 2D visual-mnemonic style and the fixed symbol dictionary. Do not mark questions complete until their media and MCQs are produced and checked.`;
    try { await navigator.clipboard.writeText(text); toast(paused ? 'The collection brief was copied.' : 'The next-batch brief was copied.'); }
    catch (_) { openModal('copy-plan', paused ? 'Your collection brief.' : 'Your next-batch brief.', paused ? 'APP REPAIRS ONLY' : 'CONTINUE PRODUCTION', `<p class="modal-intro">${paused ? 'Share this brief when asking for app or existing-lesson updates.' : 'Copy this brief into your next content-generation conversation.'}</p><textarea class="textarea" readonly autofocus>${esc(text)}</textarea>`); }
  }
  const actions = {
    play: () => audio.paused ? playAudio() : pauseAudio(), next: () => nextLesson(),
    like: () => { if (current()) { L.like(current().id); syncIndicators(); } },
    note: showNote, source: () => showSource(false), 'image-credit': () => showSource(true),
    report: showReport, 'save-feedback': saveFeedback, 'feedback-history': showFeedbackHistory, 'export-feedback': exportFeedback,
    'save-feedback-file': () => { if (!native?.exportFeedback?.(L.exportFeedback())) downloadJSON(JSON.parse(L.exportFeedback()), `InstaAnki-feedback-${new Date().toISOString().slice(0, 10)}.json`); },
    speed: showSpeed, filters: showFilters, 'local-info': showLocalInfo, licenses: showLicenses,
    captions: showTranscript,
    'close-modal': () => closeModal(),
    'clear-filters': () => { closeModal(false); app.specialty = ''; app.tag = ''; rebuildFeed(); },
    'all-feed': () => { app.feedMode = 'all'; rebuildFeed(); },
    'go-feed': () => { showTab('feed'); },
    'quiz-now': () => { if (current()) showQuiz(current(), 'practice', 'practice'); },
    'lesson-question': () => { if (current()) { pauseAudio(); finishLessonPlayback(); } },
    'review-home': () => { closeModal(false); showTab('review'); },
    'save-note': () => { if (app.modal?.lessonId) { L.note(app.modal.lessonId, $('#note-input').value); closeModal(); toast('Your private note was saved.'); } },
    'submit-answer': () => submitAnswer(false), 'dont-know': () => submitAnswer(true), 'quiz-continue': continueQuiz,
    'start-review': () => { const lesson = L.due(app.lessons)[0]; if (lesson) showQuiz(lesson, 'review', 'review'); },
    retention: showRetention, 'new-limit': showNewLimit, 'daily-topics': showDailyTopics,
    'daily-topics-all': () => { app.topicDraft = []; renderTopicOptions(); },
    'save-daily-topics': () => {
      L.setSetting('dailyTopicIds', app.topicDraft);
      const preferred = current()?.id;
      closeModal(false); app.specialty = ''; app.tag = ''; app.feedMode = 'all';
      rebuildFeed(preferred); if (app.tab === 'settings') renderSettings();
      toast('Your daily topics were saved.');
    },
    'save-retention': () => { L.setSetting('retention', Number($('#retention-input').value) / 100); closeModal(); renderSettings(); toast('Your recall target was updated.'); },
    'save-new-limit': () => { const value = Number($('#new-limit-input').value); if (!Number.isInteger(value) || value < 1 || value > 50) { toast('Choose a whole number from 1 to 50.'); return; } L.setSetting('newPerDay', value); closeModal(); renderSettings(); rebuildFeed(current()?.id); },
    'import-pack': () => { if (native?.importZip) native.importZip(); else toast('ZIP lesson import is available in the Android app.'); },
    'export-backup': () => { if (native?.exportBackup) native.exportBackup(); else { downloadJSON(L.backup(), `InstaAnki-backup-${new Date().toISOString().slice(0, 10)}.json`); toast('Your learning backup is ready to save.'); } },
    'import-backup': () => { if (native?.importBackup) native.importBackup(); else $('#backup-file').click(); },
    'check-updates': () => checkUpdates(true),
    'open-app-update': () => { const candidate = appUpdateCandidate(); if (candidate) external(candidate.url); else toast('No compatible app update is listed for this installation.'); },
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
        else if (question?.status === 'produced') toast(`Question ${button.dataset.question} was produced previously. Its lesson is not installed on this device.`);
        else toast(`Question ${button.dataset.question} has ${question?.status === 'needs_review' ? 'source details that still need review' : 'not been produced as a lesson yet'}.`);
        return;
      }
      if (button.dataset.watchLesson) { watchLesson(button.dataset.watchLesson); return; }
      if (button.hasAttribute('data-clinical-image')) {
        const lesson = current(); const image = lesson?.presentation?.clinicalGallery?.images?.[Number(button.dataset.clinicalImage)];
        if (image) openModal('clinical-image', image.title || 'Clinical image', 'FULL IMAGE & SOURCE', imageCredit(image, lesson._baseUrl));
        return;
      }
      if (button.dataset.unhideLesson) {
        L.setHidden(button.dataset.unhideLesson, false); rebuildFeed(current()?.id); showFeedbackHistory(); toast('Lesson restored with its existing review history.'); return;
      }
      if (button.hasAttribute('data-seek-scene')) {
        const target = Number(button.dataset.seekScene); closeModal(false);
        if (Number.isFinite(audio.duration)) { audio.currentTime = clamp(target, 0, playbackDuration()); app.lastClock = 0; paintFrame(); playAudio(false); }
        return;
      }
      if (button.dataset.reviewLesson) { showQuiz(byId(button.dataset.reviewLesson), 'review', 'review'); return; }
      if (button.dataset.practiceLesson) { showQuiz(byId(button.dataset.practiceLesson), 'practice', 'practice'); return; }
      if (button.hasAttribute('data-answer') && app.modal?.kind === 'quiz' && !app.modal.answered) { selectQuizAnswer(Number(button.dataset.answer)); return; }
      if (button.dataset.speed) {
        const speed = Number(button.dataset.speed); L.setSetting('speed', speed); audio.playbackRate = speed; $('#speed-button').textContent = `${speed}×`; closeModal(); if (app.tab === 'settings') renderSettings(); return;
      }
      if (button.hasAttribute('data-specialty')) { app.specialty = button.dataset.specialty; closeModal(false); rebuildFeed(); return; }
      if (button.hasAttribute('data-topic')) { app.tag = button.dataset.topic; closeModal(false); rebuildFeed(); return; }
      if (button.dataset.removeDailyTag) { app.topicDraft = app.topicDraft.filter(id => id !== button.dataset.removeDailyTag); renderTopicOptions(); return; }
      if (button.dataset.downloadPack) downloadPack(button.dataset.downloadPack);
    } catch (error) { console.error(error); toast(error.message || 'That action could not be completed.'); }
  });
  document.addEventListener('change', event => {
    if (event.target.hasAttribute('data-daily-tag') && app.modal?.kind === 'daily-topics') {
      const id = event.target.dataset.dailyTag;
      app.topicDraft = event.target.checked ? [...new Set([...app.topicDraft, id])] : app.topicDraft.filter(item => item !== id);
      // A shared topic can appear under several specialties; keep its checkboxes consistent.
      $$('[data-daily-tag]').forEach(input => { input.checked = app.topicDraft.includes(input.dataset.dailyTag); });
      updateTopicCount(); return;
    }
    if (event.target.hasAttribute('data-captions')) { app.captions = event.target.checked; $('#caption-button').setAttribute('aria-pressed', String(app.captions)); paintFrame(); return; }
    const key = event.target.dataset?.setting; if (!key) return;
    L.setSetting(key, event.target.checked); syncIndicators(); paintFrame();
    if (key === 'autoCheckUpdates' && event.target.checked && navigator.onLine) checkUpdates(false);
  });
  document.addEventListener('input', event => {
    if (event.target.id === 'retention-input') $('#retention-value').textContent = event.target.value;
    if (event.target.id === 'daily-topic-search') renderTopicOptions();
  });
  $('#seek').addEventListener('input', event => { if (Number.isFinite(audio.duration)) { audio.currentTime = Number(event.target.value) / 100 * playbackDuration(); app.lastClock = 0; paintFrame(); } });
  audio.addEventListener('play', () => {
    if (app.modal || app.tab !== 'feed' || document.visibilityState !== 'visible') { pauseAudio(); return; }
    app.lastClock = 0; updatePlayButtons(); paintFrame(); startFrames();
  });
  audio.addEventListener('pause', () => { stopFrames(); flushExposure(); updatePlayButtons(); paintFrame(); });
  audio.addEventListener('loadedmetadata', paintFrame);
  $('#lesson-image').addEventListener('load', () => {
    const image = $('#lesson-image');
    app.imageReady = image.currentSrc === app.currentImage && image.naturalWidth > 0;
    paintFrame();
  });
  $('#lesson-image').addEventListener('error', () => { app.imageReady = false; paintFrame(); });
  audio.addEventListener('timeupdate', () => { paintFrame(); handlePlaybackEnd(); });
  audio.addEventListener('seeking', () => { app.lastClock = 0; paintFrame(); });
  audio.addEventListener('seeked', paintFrame);
  audio.addEventListener('ratechange', paintFrame);
  audio.addEventListener('error', () => { updatePlayButtons(); if (current()) { $('#lesson-caption').textContent = 'The narration file is unavailable. Reimport this lesson package to restore playback.'; } });
  audio.addEventListener('ended', () => { flushExposure(); updatePlayButtons(); handlePlaybackEnd(true); });
  window.addEventListener('resize', paintFrame);
  if (window.ResizeObserver) new ResizeObserver(paintFrame).observe($('#visual-stage'));
  motionPreference.addEventListener?.('change', paintFrame);
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
  let lastSwipeAt = 0;
  $('#visual-stage').addEventListener('touchstart', event => {
    if (event.target.closest('button') || app.modal || event.touches.length !== 1) { touchStart = null; return; }
    touchStart = { x: event.touches[0].clientX, y: event.touches[0].clientY, at: performance.now() };
  }, { passive: true });
  $('#visual-stage').addEventListener('touchend', event => {
    if (!touchStart || !event.changedTouches.length) return;
    const deltaY = event.changedTouches[0].clientY - touchStart.y;
    const deltaX = event.changedTouches[0].clientX - touchStart.x;
    if (Math.abs(deltaY) > 62 && Math.abs(deltaY) > Math.abs(deltaX) * 1.4 && performance.now() - touchStart.at < 950) { lastSwipeAt = performance.now(); nextLesson(deltaY < 0 ? 1 : -1); }
    touchStart = null;
  }, { passive: true });
  $('#visual-stage').addEventListener('touchcancel', () => { touchStart = null; }, { passive: true });
  $('#visual-stage').addEventListener('click', event => {
    if (event.target.closest('button, .scene-heading, .lesson-copy') || app.modal || performance.now() - lastSwipeAt < 500) return;
    actions.play();
  });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState !== 'visible') pauseAudio(); });
  window.addEventListener('instaanki:background', pauseAudio);
  window.addEventListener('learning:changed', () => { syncIndicators(); paintFrame(); });
  window.addEventListener('instaanki:error', event => { app.downloading = false; toast(event.detail?.message || 'The operation could not be completed.'); if (app.modal?.kind === 'updates') renderUpdates(); });
  window.addEventListener('instaanki:import-started', () => { pauseAudio(); toast('Preparing your lesson package…'); });
  window.addEventListener('instaanki:download-progress', event => {
    const box = $('#download-progress'); if (!box) return; box.hidden = false;
    const detail = event.detail || {};
    box.querySelector('span').textContent = detail.percent == null ? `Downloaded ${amount(detail.receivedBytes)}` : `Downloaded ${detail.percent}% · ${amount(detail.receivedBytes)}`;
    box.querySelector('.progress-fill').style.width = `${clamp(detail.percent || 0, 0, 100)}%`;
  });
  window.addEventListener('instaanki:pack-imported', async () => {
    app.downloading = false; const id = current()?.id; pauseAudio();
    try {
      if (await loadNativePacks() === false) return;
      rebuildFeed(id); syncIndicators();
      if (app.tab === 'settings') renderSettings(); if (app.tab === 'publications') renderPublications(); if (app.tab === 'review') renderReview();
      if (app.modal?.kind === 'updates') renderUpdates(); toast(app.collectionWarnings[0] || 'Your collection is updated. Learning history was preserved.');
      window.dispatchEvent(new CustomEvent('instaanki:collection-reloaded', { detail: { lessons: app.lessons.length, books: app.books.length } }));
    } catch (error) { console.error(error); toast(error.message || 'The collection could not be refreshed. Reopen the app and try again.'); }
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
      let nativeInfo = {};
      if (native?.getAppInfo) { try { nativeInfo = JSON.parse(native.getAppInfo()) || {}; } catch (_) { } }
      const fresh = document.querySelector('meta[name="instaanki-distribution"]')?.content === 'fresh';
      const results = await Promise.allSettled([fetchJSON('data/lessons.json'), fetchJSON('data/books.json'), fetchJSON('data/taxonomy.json'), fresh ? fetchJSON('data/distribution.json') : Promise.resolve(null)]);
      if (fresh) {
        const marker = results[3].status === 'fulfilled' && results[3].value;
        if (marker?.schemaVersion !== 1 || marker.profile !== 'fresh' || marker.app?.packageName !== 'com.instaanki.fresh') throw new Error('The fresh app identity could not be opened. Reinstall its complete app package.');
        app.distribution = marker;
        app.info = { ...app.info, ...marker.app };
      }
      app.info = { ...app.info, ...nativeInfo };
      if (results[0].status === 'fulfilled') {
        const raw = results[0].value;
        app.bundledLessons = (Array.isArray(raw) ? raw : raw.lessons || []).filter(validLesson);
      }
      if (results[1].status === 'fulfilled') { const raw = results[1].value; app.bundledBooks = Array.isArray(raw) ? raw : raw.books || []; }
      await loadNativePacks();
      const loadedTags = new Map();
      for (const lesson of app.lessons) {
        const specialtyId = lesson.primarySpecialtyId || (lesson.tags || []).find(tag => tag.id?.startsWith('specialty.'))?.id;
        for (const tag of lesson.tags || []) {
          const previous = loadedTags.get(tag.id);
          loadedTags.set(tag.id, { ...tag, status: 'active', specialty_ids: [...new Set([...(previous?.specialty_ids || []), ...(specialtyId ? [specialtyId] : [])])] });
        }
      }
      const fallbackTags = [...loadedTags.values()];
      app.topicModel = window.TopicSelection.create(results[2].status === 'fulfilled' ? results[2].value : { tags: fallbackTags });
      if (!app.lessons.length && results[0].status === 'rejected') throw new Error('Your lesson collection could not be opened. Use Settings to import a package, or reopen the app.');
      rebuildFeed(); syncIndicators(); syncImmersive();
      if (settings().autoPlay && current()) playAudio(false);
      if (settings().autoCheckUpdates && navigator.onLine) checkUpdates(false);
    } catch (error) {
      $('#feed-empty').classList.add('boot-error');
      $('#feed-empty').innerHTML = `<div class="empty-emblem">${icons.book}</div><h1>Let’s open your collection.</h1><p>${esc(error.message)}</p><button class="secondary-button empty-button" type="button" data-tab="settings">Open settings</button>`;
    }
  }
  boot();
})();
