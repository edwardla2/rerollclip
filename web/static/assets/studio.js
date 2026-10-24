/* Reroll Studio — browser editor.
 * Model: media (files added to this edit) and timeline items (references into media with
 * their own in/out). One file can appear on the timeline several times. Items play
 * back-to-back (ripple edit). Nothing leaves the browser until the person exports or asks
 * for a smart trim; export uploads each used file once, then asks the server to render a
 * schema-v1 manifest with the same renderer the Mac app uses. */
(() => {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const MAX_BYTES = 250 * 1024 * 1024;
  const WAVEFORM_MAX_BYTES = 150 * 1024 * 1024;  // decoding audio needs the whole file in memory
  const MAX_ITEMS = 30;          // server limit per render
  const MAX_LEN = 120;           // renderer limit per clip, seconds
  const MIN_LEN = 0.2;
  const PEAK_RATE = 50;          // waveform samples per second
  const ZOOM_MIN = 8, ZOOM_MAX = 160;  // timeline pixels per second
  const VIEW_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3];  // preview size, relative to "fit"
  const EXT = /\.(mp4|mov|webm|mkv)$/i;
  const SIZES = { 480: [480, 852], 720: [720, 1280], 1080: [1080, 1920] };
  const SIZE_NOTES = {
    480: '480 × 852 · smallest file, quickest export.',
    720: '720 × 1280 · a good balance of size and sharpness.',
    1080: '1080 × 1920 · full HD vertical, the size TikTok, Shorts and Reels use.',
  };
  const LAYOUT_NAMES = { fit_blur: 'Blur fill', center_crop: 'Crop' };
  const MEDIA_MIME = 'application/x-reroll-media';
  const uid = () => crypto.randomUUID().replace(/-/g, '');
  const icon = (name) => `<svg class="i" aria-hidden="true"><use href="#i-${name}"/></svg>`;

  const state = {
    projectId: loadProjectId(),
    media: new Map(),
    items: [],
    selected: null,    // timeline item id
    mediaSel: null,    // media id selected in the Media panel
    zoom: 36,          // timeline pixels per second
    view: 1,           // preview size relative to "fit"
    time: 0,           // playhead, seconds into the timeline
    playing: false,
    layout: 'fit_blur',
    size: '1080',
    trimLength: 8,
    dirty: false,
    exported: false,
    laneV: 64,
    laneA: 40,
  };

  const els = {
    app: $('#app'), frame: $('#frame'), fg: $('#v-fg'), bg: $('#v-bg'), canvas: $('#stage-canvas'),
    play: $('#play'), tcNow: $('#tc-now'), tcTotal: $('#tc-total'),
    mediaList: $('#media-list'), mediaCount: $('#media-count'), fileInput: $('#file-input'), drop: $('#drop'),
    tl: $('#tl'), track: $('#track'), audioLane: $('#audio-lane'), ruler: $('#ruler'), inner: $('#tl-inner'), scroll: $('#tl-scroll'),
    playhead: $('#playhead'), hoverline: $('#hoverline'), tlCount: $('#tl-count'), zoom: $('#zoom'),
    clipEmpty: $('#clip-empty'), clipFields: $('#clip-fields'), mediaFields: $('#media-fields'),
    clipName: $('#clip-name'), clipThumb: $('#clip-thumb'), clipRes: $('#clip-res'), clipIndex: $('#clip-index'),
    trimmer: $('#trimmer'), trimStrip: $('#trimmer-strip'), trimBright: $('#trimmer-bright'), rangeSel: $('#clip-range-sel'),
    fStart: $('#f-start'), fEnd: $('#f-end'), fLength: $('#f-length'), clipSourceLen: $('#clip-source-len'),
    exportOpen: $('#export-open'), dialog: $('#export-dialog'), toast: $('#toast'),
    undo: $('#undo'), redo: $('#redo'), saveState: $('#bar-hint'), stageFormat: $('#stage-format'), stageClip: $('#stage-clip'),
    viewPct: $('#view-pct'), viewFit: $('#view-fit'),
  };

  // ---------- helpers ----------

  function loadProjectId() {
    let id = null;
    try { id = localStorage.getItem('reroll.project') || localStorage.getItem('clipthat.project'); } catch (_) { /* storage blocked */ }
    if (id && /^[0-9a-f]{32}$/.test(id)) return id;
    return newProjectId();
  }
  function newProjectId() {
    const id = uid();
    try { localStorage.setItem('reroll.project', id); } catch (_) { /* fine without */ }
    return id;
  }
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const total = () => state.items.reduce((s, i) => s + i.length, 0);
  const startOf = (index) => state.items.slice(0, index).reduce((s, i) => s + i.length, 0);
  const mediaOf = (item) => state.media.get(item.mediaId);
  const selectedItem = () => state.items.find((i) => i.id === state.selected) || null;
  const round3 = (x) => Math.round(x * 1000) / 1000;
  const floor3 = (x) => Math.floor(x * 1000) / 1000;
  const displayName = (m) => m.name.replace(EXT, '');
  const extOf = (m) => (m.name.match(EXT)?.[1] || '').toUpperCase();
  const resLabel = (m) => (m.width && m.height ? `${Math.min(m.width, m.height)}p` : '');
  const usageOf = (id) => state.items.filter((i) => i.mediaId === id).length;

  function fmt(t) {
    t = Math.max(0, t || 0);
    const m = Math.floor(t / 60);
    const s = t - m * 60;
    return `${m}:${s.toFixed(1).padStart(4, '0')}`;
  }
  function fmtClock(t) {
    const all = Math.round(Math.max(0, t || 0));
    return `${Math.floor(all / 60)}:${String(all % 60).padStart(2, '0')}`;
  }
  function fmtBytes(n) {
    return n >= 1024 * 1024 * 1024 ? `${(n / 1024 / 1024 / 1024).toFixed(1)} GB` : `${Math.max(0.1, n / 1024 / 1024).toFixed(1)} MB`;
  }
  function locate(t) {
    let acc = 0;
    for (let k = 0; k < state.items.length; k++) {
      const len = state.items[k].length;
      if (t < acc + len - 1e-6 || k === state.items.length - 1) return { index: k, offset: clamp(t - acc, 0, len) };
      acc += len;
    }
    return null;
  }
  let toastTimer = 0;
  function toast(text, isError = false) {
    els.toast.textContent = text;
    els.toast.classList.toggle('is-error', isError);
    els.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { els.toast.hidden = true; }, isError ? 6000 : 3500);
  }
  function maxLengthFor(item, start = item.start) {
    return Math.min(MAX_LEN, mediaOf(item).duration - start);
  }
  function thumbAt(m, t) {
    if (!m.thumbs || !m.thumbs.length) return m.thumb || '';
    let best = m.thumbs[0];
    for (const th of m.thumbs) if (Math.abs(th.t - t) < Math.abs(best.t - t)) best = th;
    return best.url;
  }

  // ---------- panel layout (collapse + resize, remembered per browser) ----------

  const prefs = loadPrefs();
  function loadPrefs() {
    try { return JSON.parse(localStorage.getItem('reroll.layout') || '{}') || {}; } catch (_) { return {}; }
  }
  function savePrefs() {
    try { localStorage.setItem('reroll.layout', JSON.stringify(prefs)); } catch (_) { /* fine without */ }
  }
  function applyPrefs() {
    const set = (name, v) => (v ? els.app.style.setProperty(name, `${v}px`) : els.app.style.removeProperty(name));
    set('--side-w', prefs.side);
    set('--insp-w', prefs.insp);
    set('--tl-h', prefs.tl);
    const sideCollapsed = prefs.sideCollapsed ?? window.innerWidth < 1000;
    els.app.classList.toggle('side-collapsed', !!sideCollapsed);
    els.app.classList.toggle('insp-collapsed', !!prefs.inspCollapsed);
    const ts = $('#toggle-side');
    ts.setAttribute('aria-pressed', String(!!sideCollapsed));
    ts.setAttribute('aria-label', sideCollapsed ? 'Show media panel' : 'Hide media panel');
    ts.title = sideCollapsed ? 'Show panel' : 'Hide panel';
    ts.innerHTML = icon(sideCollapsed ? 'panel-left-open' : 'panel-left-close');
    const ti = $('#toggle-insp');
    ti.setAttribute('aria-pressed', String(!!prefs.inspCollapsed));
    ti.setAttribute('aria-label', prefs.inspCollapsed ? 'Show details panel' : 'Hide details panel');
    ti.title = prefs.inspCollapsed ? 'Show panel' : 'Hide panel';
    ti.innerHTML = icon(prefs.inspCollapsed ? 'panel-right-open' : 'panel-right-close');
  }
  function setSideCollapsed(v) { prefs.sideCollapsed = v; savePrefs(); applyPrefs(); }
  function setInspCollapsed(v) { prefs.inspCollapsed = v; savePrefs(); applyPrefs(); }
  $('#toggle-side').addEventListener('click', () => setSideCollapsed(!els.app.classList.contains('side-collapsed')));
  $('#toggle-insp').addEventListener('click', () => setInspCollapsed(!els.app.classList.contains('insp-collapsed')));

  function makeResizer(handle, { axis, read, limits, store }) {
    const apply = (v) => {
      const [lo, hi] = limits();
      prefs[store] = Math.round(clamp(v, lo, Math.max(lo, hi)));
      applyPrefs();
    };
    handle.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      handle.setPointerCapture(e.pointerId);
      handle.classList.add('is-active');
      document.body.classList.add('is-resizing', axis === 'x' ? 'rz-col' : 'rz-row');
      const origin = axis === 'x' ? e.clientX : e.clientY;
      const start = read();
      const sign = handle.dataset.sign === '-1' ? -1 : 1;
      const move = (ev) => apply(start + sign * ((axis === 'x' ? ev.clientX : ev.clientY) - origin));
      const up = () => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', up);
        handle.removeEventListener('pointercancel', up);
        handle.classList.remove('is-active');
        document.body.classList.remove('is-resizing', 'rz-col', 'rz-row');
        savePrefs();
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
      handle.addEventListener('pointercancel', up);
    });
    handle.addEventListener('keydown', (e) => {
      const sign = handle.dataset.sign === '-1' ? -1 : 1;
      const keys = axis === 'x' ? { ArrowLeft: -16, ArrowRight: 16 } : { ArrowUp: -16, ArrowDown: 16 };
      if (!(e.key in keys)) return;
      e.preventDefault();
      apply(read() + sign * keys[e.key]);
      savePrefs();
    });
    handle.addEventListener('dblclick', () => { delete prefs[store]; savePrefs(); applyPrefs(); });
  }
  const railW = () => $('.rail').getBoundingClientRect().width;
  const widthOf = (sel) => $(sel).getBoundingClientRect().width;
  makeResizer($('#rz-side'), {
    axis: 'x', store: 'side', read: () => widthOf('#side'),
    limits: () => [220, Math.min(460, window.innerWidth - railW() - (els.app.classList.contains('insp-collapsed') ? 0 : widthOf('#inspector')) - 380)],
  });
  $('#rz-insp').dataset.sign = '-1';
  makeResizer($('#rz-insp'), {
    axis: 'x', store: 'insp', read: () => widthOf('#inspector'),
    limits: () => [236, Math.min(420, window.innerWidth - railW() - (els.app.classList.contains('side-collapsed') ? 0 : widthOf('#side')) - 380)],
  });
  $('#rz-tl').dataset.sign = '-1';
  makeResizer($('#rz-tl'), {
    axis: 'y', store: 'tl', read: () => els.tl.getBoundingClientRect().height,
    limits: () => [184, window.innerHeight - 60 - 300],
  });

  // ---------- history (undo / redo) ----------

  const history = { undo: [], redo: [] };
  const snapshot = () => ({ items: state.items.map((i) => ({ ...i })), selected: state.selected });
  function checkpoint() {
    history.undo.push(snapshot());
    if (history.undo.length > 80) history.undo.shift();
    history.redo = [];
    updateHistoryButtons();
  }
  function restore(snap) {
    state.items = snap.items.filter((i) => state.media.has(i.mediaId)).map((i) => ({ ...i }));
    state.selected = state.items.some((i) => i.id === snap.selected) ? snap.selected : (state.items[0]?.id || null);
    changed();
  }
  function undo() {
    if (!history.undo.length) return;
    pause();
    history.redo.push(snapshot());
    restore(history.undo.pop());
    updateHistoryButtons();
  }
  function redo() {
    if (!history.redo.length) return;
    pause();
    history.undo.push(snapshot());
    restore(history.redo.pop());
    updateHistoryButtons();
  }
  function updateHistoryButtons() {
    els.undo.disabled = !history.undo.length;
    els.redo.disabled = !history.redo.length;
  }

  // ---------- media ----------

  let importChain = Promise.resolve();

  function importFiles(fileList) {
    const files = [...fileList];
    if (!files.length) return;
    const wrongType = files.filter((f) => !EXT.test(f.name));
    const tooBig = files.filter((f) => EXT.test(f.name) && f.size > MAX_BYTES);
    const ok = files.filter((f) => EXT.test(f.name) && f.size <= MAX_BYTES);
    if (wrongType.length) toast(`Skipped ${wrongType.length} file(s): use MP4, MOV, WebM or MKV.`, true);
    else if (tooBig.length) toast(`Skipped ${tooBig.length} file(s) over 250 MB.`, true);
    if (ok.length && els.app.classList.contains('side-collapsed')) setSideCollapsed(false);
    for (const file of ok) {
      const m = { id: uid(), file, name: file.name, url: URL.createObjectURL(file), duration: 0, width: 0, height: 0, thumb: '', thumbs: [], status: 'loading', remote: null, peaks: null };
      state.media.set(m.id, m);
      const probed = probe(m);
      // Probes run in parallel, but clips join the timeline in the order they were chosen.
      importChain = importChain.then(() => probed).then(() => {
        if (m.status === 'ready') {
          if (state.items.length < MAX_ITEMS) addItem(m.id, !state.selected);
          else toast(`The timeline holds up to ${MAX_ITEMS} clips.`, true);
          loadWaveform(m);
        } else {
          toast(`Your browser can’t read “${m.name}”. Try converting it to MP4 (H.264).`, true);
        }
        renderBin();
      });
    }
    renderBin();
    els.fileInput.value = '';
  }

  /** Reads duration and size and grabs frames for thumbnails, hover scrubbing and the filmstrip. */
  function probe(m) {
    return new Promise((resolve) => {
      const v = document.createElement('video');
      v.preload = 'auto';
      v.muted = true;
      v.playsInline = true;
      let settled = false;
      let times = [];
      let index = 0;
      const canvas = document.createElement('canvas');
      const finish = (status) => {
        if (settled) return;
        settled = true;
        m.status = status;
        if (m.thumbs.length) m.thumb = m.thumbs[Math.floor(m.thumbs.length / 3)].url;
        v.removeAttribute('src');
        v.load();
        resolve();
      };
      v.onerror = () => finish('error');
      v.onloadedmetadata = () => {
        if (!Number.isFinite(v.duration) || v.duration <= 0) { finish('error'); return; }
        m.duration = v.duration;
        m.width = v.videoWidth;
        m.height = v.videoHeight;
        const n = clamp(Math.ceil(v.duration / 1.5), 6, 24);
        times = Array.from({ length: n }, (_, k) => Math.min(v.duration - 0.05, (k + 0.5) * v.duration / n));
        v.currentTime = times[0];
      };
      v.onseeked = () => {
        try {
          const h = 120;
          const w = Math.max(1, Math.round(h * (v.videoWidth || 16) / (v.videoHeight || 9)));
          canvas.width = w; canvas.height = h;
          canvas.getContext('2d').drawImage(v, 0, 0, w, h);
          m.thumbs.push({ t: times[index], url: canvas.toDataURL('image/jpeg', 0.72) });
        } catch (_) { /* thumbnails are optional */ }
        index += 1;
        if (index < times.length) v.currentTime = times[index];
        else finish('ready');
      };
      setTimeout(() => finish(m.duration > 0 ? 'ready' : 'error'), 20000);
      v.src = m.url;
    });
  }

  /** Decodes the clip's audio in the browser to draw its waveform. Optional. */
  async function loadWaveform(m) {
    if (m.file.size > WAVEFORM_MAX_BYTES || typeof OfflineAudioContext === 'undefined') { m.peaks = 'unavailable'; return; }
    try {
      const ctx = new OfflineAudioContext(1, 1, 22050);
      const buffer = await ctx.decodeAudioData(await m.file.arrayBuffer());
      const data = buffer.getChannelData(0);
      const per = Math.max(1, Math.floor(buffer.sampleRate / PEAK_RATE));
      const peaks = new Float32Array(Math.ceil(data.length / per));
      let max = 0;
      for (let i = 0; i < peaks.length; i++) {
        let p = 0;
        for (let j = i * per, end = Math.min(data.length, j + per); j < end; j++) {
          const a = Math.abs(data[j]);
          if (a > p) p = a;
        }
        peaks[i] = p;
        if (p > max) max = p;
      }
      if (max < 0.003) { m.peaks = 'silent'; } else {
        for (let i = 0; i < peaks.length; i++) peaks[i] = Math.sqrt(peaks[i] / max);  // perceptual curve
        m.peaks = peaks;
      }
    } catch (_) {
      m.peaks = 'silent';  // no audio track, or a codec the browser can't decode
    }
    renderTimeline();
  }

  function removeMedia(id) {
    const m = state.media.get(id);
    if (!m) return;
    const uses = usageOf(id);
    if (uses && !confirm(`Remove “${m.name}”? It’s used ${uses === 1 ? 'once' : `${uses} times`} on the timeline, and those clips go too.`)) return;
    checkpoint();
    state.items = state.items.filter((i) => i.mediaId !== id);
    if (state.selected && !selectedItem()) state.selected = null;
    if (state.mediaSel === id) state.mediaSel = null;
    if (els.fg.dataset.media === id) { els.fg.removeAttribute('src'); els.bg.removeAttribute('src'); delete els.fg.dataset.media; }
    URL.revokeObjectURL(m.url);
    state.media.delete(id);
    // History entries can't bring back a removed file.
    history.undo.forEach((s) => { s.items = s.items.filter((i) => i.mediaId !== id); });
    changed();
  }

  // ---------- timeline items ----------

  function addItem(mediaId, select = true, index = state.items.length) {
    const m = state.media.get(mediaId);
    if (!m || m.status !== 'ready') return;
    if (state.items.length >= MAX_ITEMS) { toast(`The timeline holds up to ${MAX_ITEMS} clips.`, true); return; }
    checkpoint();
    const item = { id: uid(), mediaId, start: 0, length: Math.min(MAX_LEN, m.duration) };
    state.items.splice(clamp(index, 0, state.items.length), 0, item);
    if (select) { state.selected = item.id; state.mediaSel = null; }
    changed();
  }

  function removeItem(id) {
    const index = state.items.findIndex((i) => i.id === id);
    if (index < 0) return;
    checkpoint();
    state.items.splice(index, 1);
    state.selected = state.items[Math.min(index, state.items.length - 1)]?.id || null;
    changed();
  }

  function splitAtPlayhead() {
    const loc = locate(state.time);
    if (!loc) return;
    const item = state.items[loc.index];
    const cut = loc.offset;
    if (cut < MIN_LEN || item.length - cut < MIN_LEN) { toast('Move the playhead inside a clip to split it.'); return; }
    if (state.items.length >= MAX_ITEMS) { toast(`The timeline holds up to ${MAX_ITEMS} clips.`, true); return; }
    checkpoint();
    const second = { id: uid(), mediaId: item.mediaId, start: item.start + cut, length: item.length - cut };
    item.length = cut;
    item.suggested = false;
    state.items.splice(loc.index + 1, 0, second);
    state.selected = second.id;
    changed();
  }

  function setTrim(item, start, length) {
    item.suggested = false;
    const m = mediaOf(item);
    start = clamp(start, 0, Math.max(0, m.duration - MIN_LEN));
    length = clamp(length, MIN_LEN, maxLengthFor(item, start));
    item.start = start;
    item.length = length;
  }

  /** Where in the item order a drop at timeline time t lands. */
  function dropIndexAt(t, exclude = null) {
    const others = state.items.filter((i) => i !== exclude);
    let acc = 0;
    for (let k = 0; k < others.length; k++) {
      if (t < acc + others[k].length / 2) return { index: k, boundary: acc };
      acc += others[k].length;
    }
    return { index: others.length, boundary: acc };
  }

  // ---------- playback ----------

  let raf = 0;
  let current = -1;
  let advancing = false;

  function setVideoTime(video, t) {
    return new Promise((resolve) => {
      let done = false;
      const finish = () => { if (!done) { done = true; resolve(); } };
      const go = () => {
        video.addEventListener('seeked', finish, { once: true });
        video.currentTime = t;
      };
      if (video.readyState >= 1) go(); else video.addEventListener('loadedmetadata', go, { once: true });
      setTimeout(finish, 1500);
    });
  }

  function updateStageClip() {
    const item = state.items[current];
    els.stageClip.replaceChildren();
    if (!item) return;
    const b = document.createElement('b');
    b.textContent = `Clip ${current + 1} of ${state.items.length}`;
    els.stageClip.append(b, ` · ${displayName(mediaOf(item))}`);
  }

  async function seek(t) {
    state.time = clamp(t, 0, total());
    const loc = locate(state.time);
    if (!loc) {
      els.frame.classList.remove('has-clip');
      current = -1;
      updateStageClip();
      updatePlayhead();
      return;
    }
    els.frame.classList.add('has-clip');
    const changedClip = current !== loc.index;
    current = loc.index;
    if (changedClip) updateStageClip();
    const item = state.items[current];
    const m = mediaOf(item);
    if (els.fg.dataset.media !== m.id) {
      els.fg.src = m.url;
      els.bg.src = m.url;
      els.fg.dataset.media = m.id;
    }
    const target = item.start + loc.offset;
    updatePlayhead();
    await Promise.all([setVideoTime(els.fg, target), setVideoTime(els.bg, target)]);
  }

  async function play() {
    if (!state.items.length) return;
    if (state.time >= total() - 0.05) await seek(0);
    else if (current < 0) await seek(state.time);
    state.playing = true;
    updatePlayButton();
    els.fg.play().catch(() => {});
    els.bg.play().catch(() => {});
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(tick);
  }

  function pause() {
    state.playing = false;
    els.fg.pause();
    els.bg.pause();
    cancelAnimationFrame(raf);
    updatePlayButton();
  }

  function tick() {
    if (!state.playing) return;
    const item = state.items[current];
    if (!item) { pause(); return; }
    if (!advancing) {
      const local = els.fg.currentTime;
      const end = item.start + item.length;
      state.time = startOf(current) + clamp(local - item.start, 0, item.length);
      if (Math.abs(els.bg.currentTime - local) > 0.35) els.bg.currentTime = local;
      if (local >= end - 0.04 || els.fg.ended) {
        if (current + 1 < state.items.length) {
          advancing = true;
          seek(startOf(current + 1)).then(() => {
            advancing = false;
            if (state.playing) { els.fg.play().catch(() => {}); els.bg.play().catch(() => {}); }
          });
        } else {
          state.time = total();
          pause();
        }
      }
      updatePlayhead();
      followPlayhead();
    }
    raf = requestAnimationFrame(tick);
  }

  /** Keeps the playhead in view while playing. */
  function followPlayhead() {
    const x = 16 + state.time * state.zoom;
    const s = els.scroll;
    if (x > s.scrollLeft + s.clientWidth - 40) s.scrollLeft = x - 80;
    else if (x < s.scrollLeft) s.scrollLeft = Math.max(0, x - 80);
  }

  function togglePlay() { state.playing ? pause() : play(); }

  // ---------- preview stage ----------

  function layoutStage(recenter = false) {
    const c = els.canvas;
    const availW = c.clientWidth - 40;
    const availH = c.clientHeight - 26;
    if (availW <= 0 || availH <= 0) return;
    const fitH = Math.max(160, Math.min(availH, availW * 16 / 9));
    const h = Math.round(fitH * state.view);
    const w = Math.round(h * 9 / 16);
    els.frame.style.width = `${w}px`;
    els.frame.style.height = `${h}px`;
    els.frame.style.borderRadius = `${clamp(Math.round(h / 36), 8, 18)}px`;
    const outH = SIZES[state.size][1];
    els.viewPct.textContent = `${Math.round((h / outH) * 100)}%`;
    els.viewFit.setAttribute('aria-pressed', String(state.view === 1));
    $('#view-out').disabled = state.view <= VIEW_STEPS[0];
    $('#view-in').disabled = state.view >= VIEW_STEPS[VIEW_STEPS.length - 1];
    c.classList.toggle('is-zoomed', state.view > 1);
    if (recenter) {
      c.scrollLeft = (c.scrollWidth - c.clientWidth) / 2;
      c.scrollTop = (c.scrollHeight - c.clientHeight) / 2;
    }
  }
  function setView(v) {
    state.view = v;
    layoutStage(true);
  }
  function stepView(dir) {
    const i = VIEW_STEPS.findIndex((s) => s >= state.view - 1e-6);
    const next = VIEW_STEPS[clamp((i < 0 ? VIEW_STEPS.length - 1 : i) + dir, 0, VIEW_STEPS.length - 1)];
    setView(next);
  }
  $('#view-in').addEventListener('click', () => stepView(1));
  $('#view-out').addEventListener('click', () => stepView(-1));
  els.viewFit.addEventListener('click', () => setView(1));
  els.canvas.addEventListener('dblclick', (e) => { if (!e.target.closest('button')) setView(1); });
  els.canvas.addEventListener('wheel', (e) => {
    if (!e.ctrlKey && !e.metaKey) return;  // pinch-to-zoom on a trackpad arrives as ctrl+wheel
    e.preventDefault();
    const next = clamp(state.view * (e.deltaY < 0 ? 1.1 : 0.91), VIEW_STEPS[0], VIEW_STEPS[VIEW_STEPS.length - 1]);
    state.view = Math.abs(next - 1) < 0.04 ? 1 : next;
    layoutStage(false);
  }, { passive: false });
  els.canvas.addEventListener('pointerdown', (e) => {
    if (state.view <= 1 || e.button !== 0 || e.target.closest('button')) return;
    const c = els.canvas;
    const sx = e.clientX, sy = e.clientY, sl = c.scrollLeft, st = c.scrollTop;
    c.setPointerCapture(e.pointerId);
    c.classList.add('is-panning');
    const move = (ev) => { c.scrollLeft = sl - (ev.clientX - sx); c.scrollTop = st - (ev.clientY - sy); };
    const up = () => {
      c.classList.remove('is-panning');
      c.removeEventListener('pointermove', move);
      c.removeEventListener('pointerup', up);
      c.removeEventListener('pointercancel', up);
    };
    c.addEventListener('pointermove', move);
    c.addEventListener('pointerup', up);
    c.addEventListener('pointercancel', up);
  });

  // ---------- rendering the UI ----------

  function changed() {
    const tot = total();
    if (state.time > tot) state.time = tot;
    state.dirty = state.items.length > 0;
    state.exported = false;
    renderBin();
    renderTimeline();
    renderInspector();
    renderFormat();
    renderSaveState();
    els.exportOpen.disabled = !state.items.length;
    $('#auto-trim-all').disabled = !state.items.length;
    $('#auto-trim-run').disabled = !state.items.length;
    $('#split').disabled = !state.items.length;
    $('#remove-item').disabled = !state.selected;
    els.tcTotal.textContent = fmt(tot);
    if (!state.playing) {
      current = -1;  // the clip under the playhead may have changed; let seek work it out again
      seek(state.time);
    }
  }

  function renderSaveState() {
    const s = els.saveState;
    s.classList.toggle('is-dirty', state.dirty && !state.exported);
    s.classList.toggle('is-exported', state.exported);
    s.querySelector('.save-text').textContent = state.exported ? 'Exported · edit stays in this tab' : 'Not saved · stays in this tab';
  }

  function renderBin() {
    const list = els.mediaList;
    list.replaceChildren();
    const usage = new Map();
    state.items.forEach((i) => usage.set(i.mediaId, (usage.get(i.mediaId) || 0) + 1));
    const n = state.media.size;
    const inEdit = [...state.media.keys()].filter((id) => usage.has(id)).length;
    els.mediaCount.textContent = n ? `${inEdit} of ${n} in edit` : '';
    els.drop.classList.toggle('is-compact', n > 0);
    const sourceId = selectedItem()?.mediaId;
    for (const m of state.media.values()) {
      const li = document.createElement('li');
      li.className = 'mcard' + (m.id === state.mediaSel ? ' is-selected' : '') + (m.id === sourceId ? ' is-source' : '');
      li.dataset.id = m.id;
      li.tabIndex = 0;
      li.setAttribute('aria-label', `${m.name}${usage.get(m.id) ? ', in your edit' : ''}`);
      const thumb = document.createElement('div');
      thumb.className = 'mthumb' + (m.status === 'loading' ? ' is-loading' : '') + (m.status === 'error' ? ' is-error' : '');
      if (m.thumb) thumb.style.backgroundImage = `url(${m.thumb})`;
      if (m.status === 'error') thumb.textContent = 'Can’t read in browser';
      const uses = usage.get(m.id) || 0;
      if (uses) {
        const used = document.createElement('span');
        used.className = 'mused' + (uses === 1 ? ' is-single' : '');
        used.innerHTML = icon('check') + (uses > 1 ? `<span>${uses}</span>` : '');
        used.title = uses > 1 ? `On the timeline ${uses} times` : 'On the timeline';
        thumb.append(used);
      }
      if (m.status === 'ready') {
        const badge = document.createElement('span');
        badge.className = 'mbadge';
        badge.textContent = fmtClock(m.duration);
        const scrub = document.createElement('span');
        scrub.className = 'mscrub';
        const add = document.createElement('button');
        add.type = 'button'; add.className = 'madd'; add.innerHTML = `${icon('plus')}Add`;
        add.title = 'Add to the end of the timeline'; add.setAttribute('aria-label', `Add ${m.name} to timeline`);
        add.addEventListener('click', (e) => { e.stopPropagation(); addItem(m.id); });
        thumb.append(badge, scrub, add);
        // Hover to skim through the clip.
        thumb.addEventListener('pointermove', (e) => {
          if (!m.thumbs.length) return;
          const r = thumb.getBoundingClientRect();
          const f = clamp((e.clientX - r.left) / r.width, 0, 0.999);
          thumb.style.backgroundImage = `url(${m.thumbs[Math.floor(f * m.thumbs.length)].url})`;
          scrub.style.width = `${f * 100}%`;
          thumb.classList.add('is-scrubbing');
        });
        thumb.addEventListener('pointerleave', () => {
          if (m.thumb) thumb.style.backgroundImage = `url(${m.thumb})`;
          thumb.classList.remove('is-scrubbing');
        });
        li.draggable = true;
        li.addEventListener('dragstart', (e) => {
          e.dataTransfer.setData(MEDIA_MIME, m.id);
          e.dataTransfer.effectAllowed = 'copy';
          li.classList.add('is-dragging');
        });
        li.addEventListener('dragend', () => li.classList.remove('is-dragging'));
        li.addEventListener('dblclick', () => addItem(m.id));
      }
      const del = document.createElement('button');
      del.type = 'button'; del.className = 'mdel'; del.innerHTML = icon('x');
      del.title = 'Remove from this edit'; del.setAttribute('aria-label', `Remove ${m.name}`);
      del.addEventListener('click', (e) => { e.stopPropagation(); removeMedia(m.id); });
      thumb.append(del);
      const text = document.createElement('div');
      text.className = 'mtext';
      const name = document.createElement('div');
      name.className = 'mname';
      name.textContent = displayName(m);
      name.title = m.name;
      const meta = document.createElement('div');
      meta.className = 'mmeta';
      meta.textContent = m.status === 'loading' ? 'Reading…' : [resLabel(m), extOf(m)].filter(Boolean).join(' · ');
      text.append(name, meta);
      li.append(thumb, text);
      li.addEventListener('click', () => selectMedia(m.id));
      li.addEventListener('keydown', (e) => {
        if (e.target !== li) return;
        if (e.key === 'Enter') { e.preventDefault(); if (m.status === 'ready') addItem(m.id); }
        else if (e.key === ' ') { e.preventDefault(); selectMedia(m.id); }
      });
      list.append(li);
    }
  }

  function selectMedia(id) {
    state.mediaSel = id;
    state.selected = null;
    markSelection();
    renderInspector();
  }

  function renderInspector() {
    const item = selectedItem();
    const media = !item && state.mediaSel ? state.media.get(state.mediaSel) : null;
    els.clipEmpty.hidden = !!(item || media);
    els.clipFields.hidden = !item;
    els.mediaFields.hidden = !media;
    $('#remove-item').disabled = !item;
    $('#stat-clips').textContent = String(state.items.length);
    $('#stat-length').textContent = fmtClock(total());
    $('#stat-output').textContent = SIZES[state.size].join(' × ');
    $('#stat-layout').textContent = LAYOUT_NAMES[state.layout];
    if (media) renderMediaInspector(media);
    if (!item) return;
    const m = mediaOf(item);
    els.clipIndex.textContent = `${state.items.indexOf(item) + 1} of ${state.items.length}`;
    els.clipName.textContent = displayName(m);
    els.clipName.title = m.name;
    els.clipRes.textContent = [m.width && m.height ? `${m.width} × ${m.height}` : '', fmt(m.duration)].filter(Boolean).join(' · ');
    els.clipThumb.style.backgroundImage = `url(${thumbAt(m, item.start + item.length / 2)})`;
    if (document.activeElement !== els.fStart) els.fStart.value = item.start.toFixed(1);
    if (document.activeElement !== els.fEnd) els.fEnd.value = (item.start + item.length).toFixed(1);
    if (document.activeElement !== els.fLength) els.fLength.value = item.length.toFixed(1);
    els.fStart.max = Math.max(0, m.duration - MIN_LEN).toFixed(1);
    els.fEnd.max = m.duration.toFixed(1);
    els.clipSourceLen.textContent = `${item.length.toFixed(1)}s of ${m.duration.toFixed(1)}s` + (m.duration > MAX_LEN ? ' · max 2:00' : '');
    renderTrimmer(item, m);
  }

  function renderMediaInspector(m) {
    const uses = usageOf(m.id);
    $('#mi-usage').textContent = uses ? (uses === 1 ? 'In your edit' : `In your edit ×${uses}`) : 'Not in your edit';
    $('#mi-thumb').style.backgroundImage = m.thumb ? `url(${m.thumb})` : '';
    $('#mi-name').textContent = m.name;
    $('#mi-duration').textContent = m.status === 'ready' ? fmt(m.duration) : '—';
    $('#mi-res').textContent = m.width ? `${m.width} × ${m.height}` : '—';
    $('#mi-size').textContent = fmtBytes(m.file.size);
    $('#mi-add').disabled = m.status !== 'ready';
  }

  function renderTrimmer(item, m) {
    if (els.trimStrip.dataset.media !== m.id) {
      const tiles = () => Array.from({ length: 8 }, (_, k) => {
        const s = document.createElement('span');
        const url = thumbAt(m, ((k + 0.5) * m.duration) / 8);
        if (url) s.style.backgroundImage = `url(${url})`;
        return s;
      });
      els.trimStrip.replaceChildren(...tiles());
      els.trimBright.replaceChildren(...tiles());
      els.trimStrip.dataset.media = m.id;
    }
    const l = (item.start / m.duration) * 100;
    const w = (item.length / m.duration) * 100;
    els.rangeSel.style.left = `${l}%`;
    els.rangeSel.style.width = `${w}%`;
    els.trimBright.style.clipPath = `inset(0 ${Math.max(0, 100 - l - w)}% 0 ${l}%)`;
  }

  function renderFormat() {
    const [w, h] = SIZES[state.size];
    els.stageFormat.textContent = `9:16 · ${state.size}p · ${LAYOUT_NAMES[state.layout]}`;
    $('#export-format').textContent = `${w} × ${h} · ${LAYOUT_NAMES[state.layout]}`;
    $('#size-note').textContent = SIZE_NOTES[state.size];
    layoutStage();
  }

  // ---------- timeline ----------

  function sizeLanes() {
    const bodyH = els.tl.clientHeight - 52;
    const avail = bodyH - 6 - 28 - 12 - 10;
    const a = clamp(Math.round(avail * 0.36), 30, 56);
    const v = clamp(avail - a, 44, 120);
    if (a === state.laneA && v === state.laneV) return false;
    state.laneA = a;
    state.laneV = v;
    els.tl.style.setProperty('--lane-v', `${v}px`);
    els.tl.style.setProperty('--lane-a', `${a}px`);
    return true;
  }

  const RULER_STEPS = [[0.5, 5], [1, 4], [2, 4], [5, 5], [10, 5], [15, 3], [30, 6], [60, 6], [120, 4]];
  function rulerStep(pps) {
    for (const s of RULER_STEPS) if (s[0] * pps >= 72) return s;
    return [300, 5];
  }
  function fmtRuler(t, step) {
    const m = Math.floor(t / 60);
    const s = t - m * 60;
    return step < 1 ? `${m}:${s.toFixed(1).padStart(4, '0')}` : `${m}:${String(Math.round(s)).padStart(2, '0')}`;
  }

  function renderTimeline() {
    const pps = state.zoom;
    const tot = total();
    const visible = els.scroll.clientWidth - 32;
    const contentWidth = Math.max(visible, tot * pps + 240);
    els.inner.style.width = `${contentWidth + 32}px`;
    els.tlCount.textContent = state.items.length ? `${state.items.length} clips` : '';

    // ruler: labelled major ticks, short minor ticks between
    const frag = document.createDocumentFragment();
    const [step, minors] = rulerStep(pps);
    for (let k = 0; k * step * pps <= contentWidth; k++) {
      const t = k * step;
      const tick = document.createElement('div');
      tick.className = 'tick';
      tick.style.left = `${t * pps}px`;
      const label = document.createElement('span');
      label.textContent = fmtRuler(t, step);
      tick.append(label);
      frag.append(tick);
      for (let j = 1; j < minors; j++) {
        const x = (t + (j * step) / minors) * pps;
        if (x > contentWidth) break;
        const minor = document.createElement('div');
        minor.className = 'tick tick-minor';
        minor.style.left = `${x}px`;
        frag.append(minor);
      }
    }
    els.ruler.replaceChildren(frag);

    // lanes
    els.track.replaceChildren();
    els.audioLane.replaceChildren();
    if (!state.items.length) {
      const empty = document.createElement('div');
      empty.className = 'track-empty';
      empty.textContent = 'Clips line up here. Drag to reorder, drag the edges to trim.';
      els.track.append(empty);
    }
    for (const item of state.items) {
      els.track.append(buildItem(item));
      els.audioLane.append(buildAudioItem(item));
    }
    layoutItems();
    updatePlayhead();
  }

  function buildItem(item) {
    const m = mediaOf(item);
    const el = document.createElement('div');
    el.className = 'item' + (item.id === state.selected ? ' is-selected' : '') + (item.suggested ? ' is-suggested' : '');
    el.dataset.id = item.id;
    el.setAttribute('role', 'button');
    el.setAttribute('aria-label', `${m.name}, ${item.length.toFixed(1)} seconds`);
    el.title = m.name;
    const strip = document.createElement('div');
    strip.className = 'strip';
    const label = document.createElement('span');
    label.className = 'item-label';
    const name = document.createElement('span');
    name.className = 'item-name';
    name.textContent = displayName(m);
    const len = document.createElement('span');
    len.className = 'item-len';
    label.append(len, name);
    const tag = document.createElement('span');
    tag.className = 'item-tag';
    tag.textContent = 'Suggested';
    const hl = document.createElement('span');
    hl.className = 'handle handle-l';
    hl.title = 'Drag to trim the start';
    const hr = document.createElement('span');
    hr.className = 'handle handle-r';
    hr.title = 'Drag to trim the end';
    el.append(strip, label, tag, hl, hr);
    el.addEventListener('pointerdown', (e) => onItemPointerDown(e, item, el));
    return el;
  }

  function buildAudioItem(item) {
    const el = document.createElement('div');
    el.className = 'aitem' + (item.id === state.selected ? ' is-selected' : '');
    el.dataset.id = item.id;
    el.append(document.createElement('canvas'));
    return el;
  }

  function fillStrip(strip, item, width) {
    const m = mediaOf(item);
    const pps = state.zoom;
    const aspect = m.width && m.height ? m.width / m.height : 16 / 9;
    const tileW = clamp(Math.round(state.laneV * aspect), 36, 220);
    const n = Math.min(80, Math.max(1, Math.ceil(width / tileW)));
    if (strip.childElementCount !== n) {
      strip.replaceChildren(...Array.from({ length: n }, () => document.createElement('span')));
    }
    [...strip.children].forEach((tile, i) => {
      tile.style.width = `${tileW}px`;
      const t = clamp(item.start + ((i + 0.5) * tileW) / pps, item.start, item.start + item.length);
      const url = thumbAt(m, t);
      const bg = url ? `url("${url}")` : '';
      if (tile.dataset.bg !== url) { tile.style.backgroundImage = bg; tile.dataset.bg = url; }
    });
  }

  function drawWaveform(el, item, width) {
    const m = mediaOf(item);
    const canvas = el.querySelector('canvas');
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.min(4096, Math.round(width)));
    const h = state.laneA;
    el.classList.toggle('is-silent', m.peaks === 'silent');
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    if (!(m.peaks instanceof Float32Array)) {
      if (m.peaks !== 'silent') {  // still loading or unavailable: a quiet baseline
        ctx.fillStyle = 'rgba(138,123,255,.35)';
        ctx.fillRect(4, h / 2 - 0.5, w - 8, 1);
      }
      return;
    }
    const pps = state.zoom;
    ctx.fillStyle = item.id === state.selected ? 'rgba(206,199,255,.95)' : 'rgba(176,165,255,.8)';
    const bar = 2, gap = 1;
    for (let x = 3; x < w - 3; x += bar + gap) {
      const t0 = item.start + x / pps;
      const t1 = item.start + (x + bar + gap) / pps;
      const i0 = Math.floor(t0 * PEAK_RATE);
      const i1 = Math.max(i0 + 1, Math.floor(t1 * PEAK_RATE));
      let v = 0;
      for (let i = i0; i < i1 && i < m.peaks.length; i++) if (m.peaks[i] > v) v = m.peaks[i];
      const bh = Math.max(1.5, v * (h - 10));
      ctx.fillRect(x, (h - bh) / 2, bar, bh);
    }
  }

  /** Positions existing item elements without rebuilding them (keeps pointer capture alive). */
  function layoutItems() {
    const pps = state.zoom;
    let x = 0;
    for (const item of state.items) {
      // A 2px seam between neighbours keeps cuts visible at any zoom.
      const width = Math.max(6, item.length * pps - 2);
      const el = els.track.querySelector(`.item[data-id="${item.id}"]`);
      if (el) {
        el.style.left = `${x * pps}px`;
        el.style.width = `${width}px`;
        el.classList.toggle('is-narrow', width < 120);
        el.classList.toggle('is-tiny', width < 44);
        el.querySelector('.item-len').textContent = `${item.length.toFixed(1)}s`;
        el.setAttribute('aria-label', `${mediaOf(item).name}, ${item.length.toFixed(1)} seconds`);
        fillStrip(el.querySelector('.strip'), item, width);
      }
      const a = els.audioLane.querySelector(`.aitem[data-id="${item.id}"]`);
      if (a) {
        a.style.left = `${x * pps}px`;
        a.style.width = `${width}px`;
        drawWaveform(a, item, width);
      }
      x += item.length;
    }
  }

  function updatePlayhead() {
    els.playhead.style.left = `${16 + state.time * state.zoom}px`;
    els.tcNow.textContent = fmt(state.time);
  }

  function updatePlayButton() {
    els.play.setAttribute('aria-pressed', String(state.playing));
    els.play.setAttribute('aria-label', state.playing ? 'Pause' : 'Play');
  }

  function markSelection() {
    $$('#track .item, #audio-lane .aitem').forEach((n) => n.classList.toggle('is-selected', n.dataset.id === state.selected));
    const sourceId = selectedItem()?.mediaId;
    $$('#media-list .mcard').forEach((n) => {
      n.classList.toggle('is-selected', n.dataset.id === state.mediaSel);
      n.classList.toggle('is-source', n.dataset.id === sourceId);
    });
    $('#remove-item').disabled = !state.selected;
    layoutItems();  // waveform colour follows selection
  }

  // ---------- timeline interactions ----------

  let previewTimer = 0;
  function previewFrame(item, t) {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => {
      const index = state.items.indexOf(item);
      if (index >= 0) seek(startOf(index) + clamp(t - item.start, 0, item.length));
    }, 40);
  }

  function onItemPointerDown(e, item, el) {
    if (e.button !== 0) return;
    e.preventDefault();
    if (state.playing) pause();
    const handle = e.target.closest('.handle');
    const mode = handle ? (handle.classList.contains('handle-l') ? 'trimL' : 'trimR') : 'move';
    const startX = e.clientX;
    const orig = { start: item.start, length: item.length };
    const pps = state.zoom;
    let moved = false;
    let dropIndex = state.items.indexOf(item);
    let marker = null;
    el.setPointerCapture(e.pointerId);
    els.hoverline.hidden = true;

    if (state.selected !== item.id) {
      state.selected = item.id;
      state.mediaSel = null;
      markSelection();
      renderInspector();
    }

    const onMove = (ev) => {
      const dx = ev.clientX - startX;
      if (!moved && Math.abs(dx) < 3) return;
      if (!moved) checkpoint();
      moved = true;
      const ds = dx / pps;
      if (mode !== 'move') {
        item.suggested = false;
        el.classList.remove('is-suggested');
      }
      if (mode === 'trimL') {
        let newStart = clamp(orig.start + ds, 0, orig.start + orig.length - MIN_LEN);
        if (orig.start + orig.length - newStart > MAX_LEN) newStart = orig.start + orig.length - MAX_LEN;
        item.start = newStart;
        item.length = orig.start + orig.length - newStart;
        layoutItems();
        renderInspector();
        previewFrame(item, item.start);
      } else if (mode === 'trimR') {
        item.length = clamp(orig.length + ds, MIN_LEN, maxLengthFor(item));
        layoutItems();
        renderInspector();
        previewFrame(item, item.start + item.length - 0.05);
      } else {
        el.classList.add('is-dragging');
        el.style.transform = `translateX(${dx}px)`;
        const rect = els.track.getBoundingClientRect();
        const drop = dropIndexAt((ev.clientX - rect.left) / pps, item);
        dropIndex = drop.index;
        if (!marker) { marker = document.createElement('div'); marker.className = 'drop-marker'; els.track.append(marker); }
        marker.style.left = `${drop.boundary * pps - 2}px`;
      }
    };

    const onUp = (ev) => {
      el.removeEventListener('pointermove', onMove);
      el.removeEventListener('pointerup', onUp);
      el.removeEventListener('pointercancel', onUp);
      if (marker) marker.remove();
      if (!moved) {
        // A click selects the clip and moves the playhead to where you clicked.
        const rect = el.getBoundingClientRect();
        const index = state.items.indexOf(item);
        seek(startOf(index) + clamp((ev.clientX - rect.left) / pps, 0, item.length));
        return;
      }
      if (mode === 'move') {
        const others = state.items.filter((i) => i !== item);
        others.splice(dropIndex, 0, item);
        state.items = others;
      }
      changed();
    };

    el.addEventListener('pointermove', onMove);
    el.addEventListener('pointerup', onUp);
    el.addEventListener('pointercancel', onUp);
  }

  function timeAtClientX(x) {
    return (x - els.track.getBoundingClientRect().left) / state.zoom;
  }
  function seekFromPointer(e) {
    if (state.playing) pause();
    seek(timeAtClientX(e.clientX));
  }
  els.ruler.addEventListener('pointerdown', (e) => {
    seekFromPointer(e);
    els.ruler.setPointerCapture(e.pointerId);
    const move = (ev) => seek(timeAtClientX(ev.clientX));  // drag along the ruler to scrub
    const up = () => { els.ruler.removeEventListener('pointermove', move); els.ruler.removeEventListener('pointerup', up); };
    els.ruler.addEventListener('pointermove', move);
    els.ruler.addEventListener('pointerup', up);
  });
  els.track.addEventListener('pointerdown', (e) => { if (e.target === els.track || e.target.classList.contains('track-empty')) seekFromPointer(e); });
  els.audioLane.addEventListener('pointerdown', (e) => seekFromPointer(e));

  // Hover guide: shows where a click would put the playhead.
  els.inner.addEventListener('pointermove', (e) => {
    if (e.buttons || !state.items.length) { els.hoverline.hidden = true; return; }
    const t = timeAtClientX(e.clientX);
    if (t < 0 || t > total()) { els.hoverline.hidden = true; return; }
    els.hoverline.hidden = false;
    els.hoverline.style.left = `${16 + t * state.zoom}px`;
    els.hoverline.firstElementChild.textContent = fmt(t);
  });
  els.inner.addEventListener('pointerleave', () => { els.hoverline.hidden = true; });

  // Drag media from the panel onto the timeline.
  let mediaMarker = null;
  const isMediaDrag = (e) => [...(e.dataTransfer?.types || [])].includes(MEDIA_MIME);
  const clearMediaDrop = () => { mediaMarker?.remove(); mediaMarker = null; els.track.classList.remove('is-drop-target'); };
  els.scroll.addEventListener('dragover', (e) => {
    if (!isMediaDrag(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    const drop = dropIndexAt(timeAtClientX(e.clientX));
    if (!mediaMarker) { mediaMarker = document.createElement('div'); mediaMarker.className = 'drop-marker'; els.track.append(mediaMarker); }
    mediaMarker.style.left = `${drop.boundary * state.zoom - 2}px`;
    els.track.classList.add('is-drop-target');
  });
  els.scroll.addEventListener('dragleave', (e) => { if (!els.scroll.contains(e.relatedTarget)) clearMediaDrop(); });
  els.scroll.addEventListener('drop', (e) => {
    if (!isMediaDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    const id = e.dataTransfer.getData(MEDIA_MIME);
    const drop = dropIndexAt(timeAtClientX(e.clientX));
    clearMediaDrop();
    addItem(id, true, drop.index);
  });

  function setZoom(z) {
    state.zoom = clamp(z, ZOOM_MIN, ZOOM_MAX);
    els.zoom.value = String(Math.round(state.zoom));
    renderTimeline();
  }
  els.zoom.addEventListener('input', () => setZoom(Number(els.zoom.value)));
  $('#zoom-in').addEventListener('click', () => setZoom(state.zoom * 1.25));
  $('#zoom-out').addEventListener('click', () => setZoom(state.zoom / 1.25));
  $('#zoom-fit').addEventListener('click', () => {
    if (!state.items.length) return;
    setZoom((els.scroll.clientWidth - 32 - 48) / total());
    els.scroll.scrollLeft = 0;
  });
  els.scroll.addEventListener('wheel', (e) => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    setZoom(state.zoom * (e.deltaY < 0 ? 1.15 : 0.87));
  }, { passive: false });

  // ---------- rail panels ----------

  function showPane(name) {
    $$('.rail-btn[data-pane]').forEach((b) => {
      const on = b.dataset.pane === name;
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-selected', String(on));
    });
    $$('.pane').forEach((p) => { p.hidden = p.dataset.pane !== name; });
  }
  $$('.rail-btn[data-pane]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const collapsed = els.app.classList.contains('side-collapsed');
      // Clicking the open tab again tucks the panel away, like most editors.
      if (btn.classList.contains('is-active') && !collapsed) { setSideCollapsed(true); return; }
      showPane(btn.dataset.pane);
      if (collapsed) setSideCollapsed(false);
    });
  });
  const openFormat = () => { showPane('format'); if (els.app.classList.contains('side-collapsed')) setSideCollapsed(false); };
  els.stageFormat.addEventListener('click', openFormat);
  $('#edit-format').addEventListener('click', openFormat);

  // ---------- inspector + format ----------

  function applyFields(source) {
    const item = selectedItem();
    if (!item) return;
    const start = Number(els.fStart.value);
    const end = Number(els.fEnd.value);
    const length = Number(els.fLength.value);
    checkpoint();
    if (source === 'start' && Number.isFinite(start)) setTrim(item, start, item.start + item.length - start);
    if (source === 'end' && Number.isFinite(end)) setTrim(item, item.start, end - item.start);
    if (source === 'length' && Number.isFinite(length)) setTrim(item, item.start, length);
    changed();
  }
  els.fStart.addEventListener('change', () => applyFields('start'));
  els.fEnd.addEventListener('change', () => applyFields('end'));
  els.fLength.addEventListener('change', () => applyFields('length'));

  // Drag a field's label sideways to scrub its value (Shift for fine steps).
  $$('.num-label[data-scrub]').forEach((label) => {
    let dragged = false;
    label.addEventListener('pointerdown', (e) => {
      const item = selectedItem();
      if (!item || e.button !== 0) return;
      e.preventDefault();
      label.setPointerCapture(e.pointerId);
      const field = label.dataset.scrub;
      const orig = { start: item.start, length: item.length };
      const x0 = e.clientX;
      dragged = false;
      const move = (ev) => {
        const dx = ev.clientX - x0;
        if (!dragged && Math.abs(dx) < 2) return;
        if (!dragged) { checkpoint(); label.classList.add('is-scrubbing'); }
        dragged = true;
        const d = dx * (ev.shiftKey ? 0.01 : 0.05);
        if (field === 'start') setTrim(item, orig.start + d, orig.start + orig.length - (orig.start + d));
        else if (field === 'end') setTrim(item, orig.start, orig.length + d);
        else setTrim(item, orig.start, orig.length + d);
        layoutItems();
        renderInspector();
        previewFrame(item, field === 'start' ? item.start : item.start + item.length - 0.05);
      };
      const up = () => {
        label.removeEventListener('pointermove', move);
        label.removeEventListener('pointerup', up);
        label.removeEventListener('pointercancel', up);
        label.classList.remove('is-scrubbing');
        if (dragged) changed();
      };
      label.addEventListener('pointermove', move);
      label.addEventListener('pointerup', up);
      label.addEventListener('pointercancel', up);
    });
    // A drag shouldn't also focus the input the label belongs to.
    label.addEventListener('click', (e) => { if (dragged) { e.preventDefault(); dragged = false; } });
  });

  // Source trimmer in the inspector: drag edges to trim, drag the window to slide.
  els.trimmer.addEventListener('pointerdown', (e) => {
    const item = selectedItem();
    if (!item || e.button !== 0) return;
    e.preventDefault();
    if (state.playing) pause();
    const m = mediaOf(item);
    const rect = els.trimmer.getBoundingClientRect();
    const mode = e.target.closest('.th-l') ? 'l' : e.target.closest('.th-r') ? 'r' : 'move';
    const orig = { start: item.start, length: item.length };
    if (mode === 'move' && !e.target.closest('.trimmer-win')) {
      // Clicked outside the window: centre the window there.
      const t = ((e.clientX - rect.left) / rect.width) * m.duration;
      checkpoint();
      setTrim(item, clamp(t - item.length / 2, 0, m.duration - item.length), orig.length);
      orig.start = item.start;
      changed();
    }
    els.trimmer.setPointerCapture(e.pointerId);
    els.trimmer.classList.add('is-dragging');
    const x0 = e.clientX;
    let moved = false;
    const move = (ev) => {
      const ds = ((ev.clientX - x0) / rect.width) * m.duration;
      if (!moved && Math.abs(ev.clientX - x0) < 2) return;
      if (!moved) checkpoint();
      moved = true;
      if (mode === 'l') {
        let s = clamp(orig.start + ds, 0, orig.start + orig.length - MIN_LEN);
        if (orig.start + orig.length - s > MAX_LEN) s = orig.start + orig.length - MAX_LEN;
        setTrim(item, s, orig.start + orig.length - s);
      } else if (mode === 'r') {
        setTrim(item, orig.start, orig.length + ds);
      } else {
        setTrim(item, clamp(orig.start + ds, 0, m.duration - orig.length), orig.length);
      }
      layoutItems();
      renderInspector();
      previewFrame(item, mode === 'r' ? item.start + item.length - 0.05 : item.start);
    };
    const up = () => {
      els.trimmer.removeEventListener('pointermove', move);
      els.trimmer.removeEventListener('pointerup', up);
      els.trimmer.removeEventListener('pointercancel', up);
      els.trimmer.classList.remove('is-dragging');
      if (moved) changed();
    };
    els.trimmer.addEventListener('pointermove', move);
    els.trimmer.addEventListener('pointerup', up);
    els.trimmer.addEventListener('pointercancel', up);
  });

  $('#reset-trim').addEventListener('click', () => {
    const item = selectedItem();
    if (!item) return;
    checkpoint();
    setTrim(item, 0, MAX_LEN);
    changed();
  });
  $('#mi-add').addEventListener('click', () => { if (state.mediaSel) addItem(state.mediaSel); });
  $('#split').addEventListener('click', splitAtPlayhead);
  $('#remove-item').addEventListener('click', () => { if (state.selected) removeItem(state.selected); });

  function radioGroup(selector, attr, onPick) {
    $$(selector).forEach((btn) => {
      btn.addEventListener('click', () => {
        $$(selector).forEach((b) => b.setAttribute('aria-checked', String(b === btn)));
        onPick(btn.dataset[attr]);
      });
    });
  }
  radioGroup('.seg [data-layout]', 'layout', (v) => { state.layout = v; els.frame.dataset.layout = v; renderFormat(); renderInspector(); });
  radioGroup('#size-seg [data-size]', 'size', (v) => { state.size = v; renderFormat(); renderInspector(); });
  radioGroup('#trim-length [data-len]', 'len', (v) => { state.trimLength = Number(v); });

  // ---------- upload / drag and drop ----------

  const openPicker = () => els.fileInput.click();
  $('#upload-button').addEventListener('click', openPicker);
  $('#empty-upload').addEventListener('click', openPicker);
  els.drop.addEventListener('click', openPicker);
  els.drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openPicker(); } });
  els.fileInput.addEventListener('change', (e) => importFiles(e.target.files));
  let dragDepth = 0;
  const isFileDrag = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
  window.addEventListener('dragenter', (e) => { if (isFileDrag(e)) { dragDepth++; document.body.classList.add('is-dragging'); } });
  window.addEventListener('dragleave', (e) => { if (!isFileDrag(e)) return; dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) document.body.classList.remove('is-dragging'); });
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => {
    e.preventDefault();
    dragDepth = 0;
    document.body.classList.remove('is-dragging');
    if (e.dataTransfer?.files?.length) importFiles(e.dataTransfer.files);
  });

  // ---------- transport + keyboard ----------

  els.play.addEventListener('click', togglePlay);
  $('#to-start').addEventListener('click', () => { pause(); seek(0); });
  $('#to-end').addEventListener('click', () => { pause(); seek(total()); });
  els.undo.addEventListener('click', undo);
  els.redo.addEventListener('click', redo);
  document.addEventListener('keydown', (e) => {
    if (els.dialog.open) return;
    const tag = (e.target.tagName || '').toLowerCase();
    if (['input', 'select', 'textarea'].includes(tag) || e.target.isContentEditable) return;
    if (e.target.getAttribute?.('role') === 'separator') return;
    const mod = e.metaKey || e.ctrlKey;
    if (mod && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if (mod && (e.key === 'y' || e.key === 'Y')) { e.preventDefault(); redo(); return; }
    if (mod) return;
    if (e.key === ' ') { if (e.target.closest?.('.mcard')) return; e.preventDefault(); togglePlay(); }
    else if (e.key === 's' || e.key === 'S') { splitAtPlayhead(); }
    else if (e.key === 'Delete' || e.key === 'Backspace') { if (state.selected) { e.preventDefault(); removeItem(state.selected); } }
    else if (e.key === 'Escape') { state.selected = null; state.mediaSel = null; markSelection(); renderInspector(); }
    else if (e.key === 'Home') { pause(); seek(0); }
    else if (e.key === 'End') { pause(); seek(total()); }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      pause();
      seek(state.time + (e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 5 : 0.5));
    }
  });

  // ---------- upload helper ----------

  function upload(m, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `/api/projects/${state.projectId}/clips`);
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded); };
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch (_) { /* non-JSON error */ }
        if (xhr.status >= 200 && xhr.status < 300 && data.file) { m.remote = data.file; resolve(); }
        else reject(new Error(typeof data.detail === 'string' ? `“${m.name}”: ${data.detail}` : `Upload of “${m.name}” failed (${xhr.status}).`));
      };
      xhr.onerror = () => reject(new Error('Upload failed. Check your connection and try again.'));
      const form = new FormData();
      form.append('file', m.file, m.name);
      xhr.send(form);
    });
  }

  // ---------- suggested trims ----------

  async function analyzeMedia(m, length) {
    m.analysis = m.analysis || {};
    if (m.analysis[length]) return m.analysis[length];
    if (!m.remote) await upload(m, () => {});
    const response = await fetch(`/api/projects/${state.projectId}/clips/${m.remote}/analyze`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ length }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 404) m.remote = null;
      throw new Error(typeof data.detail === 'string' ? data.detail : 'Couldn’t analyze this clip.');
    }
    m.analysis[length] = data;
    return data;
  }

  function applySuggestion(item, data) {
    const m = mediaOf(item);
    const start = clamp(data.suggested_start, 0, Math.max(0, m.duration - MIN_LEN));
    item.start = start;
    item.length = clamp(data.suggested_duration, MIN_LEN, maxLengthFor(item, start));
    item.suggested = true;
  }

  async function withBusy(button, label, work) {
    if (button.getAttribute('aria-busy') === 'true') return;
    const original = button.innerHTML;
    button.setAttribute('aria-busy', 'true');
    button.innerHTML = `${icon('sparkles')}<span class="tool-label">${label}</span>`;
    try { await work((text) => { button.innerHTML = `${icon('sparkles')}<span class="tool-label">${text}</span>`; }); }
    catch (error) { toast(String(error.message || error), true); }
    finally { button.removeAttribute('aria-busy'); button.innerHTML = original; }
  }

  $('#suggest-trim').addEventListener('click', () => {
    const item = selectedItem();
    if (!item) return;
    withBusy($('#suggest-trim'), 'Uploading and analyzing…', async () => {
      pause();
      const data = await analyzeMedia(mediaOf(item), state.trimLength);
      checkpoint();
      applySuggestion(item, data);
      changed();
      await seek(startOf(state.items.indexOf(item)));
      toast(`Trimmed to ${item.length.toFixed(1)}s around ${fmt(data.peak_time)}. ⌘Z to undo.`);
    });
  });

  function autoTrimAll(button) {
    if (!state.items.length) return;
    const length = state.trimLength;
    withBusy(button, 'Analyzing…', async (progress) => {
      pause();
      // A file used more than once was split or duplicated on purpose; leave those alone.
      const uses = new Map();
      state.items.forEach((i) => uses.set(i.mediaId, (uses.get(i.mediaId) || 0) + 1));
      const items = state.items.filter((i) => uses.get(i.mediaId) === 1);
      const skipped = state.items.length - items.length;
      const results = [];
      for (const [n, item] of items.entries()) {
        progress(`${mediaOf(item).remote ? 'Analyzing' : 'Uploading'} ${n + 1}/${items.length}…`);
        results.push([item, await analyzeMedia(mediaOf(item), length)]);
      }
      checkpoint();
      results.forEach(([item, data]) => applySuggestion(item, data));
      changed();
      await seek(0);
      const trimmed = `Trimmed ${items.length} ${items.length === 1 ? 'clip' : 'clips'} to about ${length}s each.`;
      toast(skipped ? `${trimmed} Skipped ${skipped} that use the same file twice.` : trimmed);
    });
  }
  $('#auto-trim-all').addEventListener('click', () => autoTrimAll($('#auto-trim-all')));
  $('#auto-trim-run').addEventListener('click', () => autoTrimAll($('#auto-trim-run')));

  // ---------- export ----------

  function stepState(id, cls) {
    const li = document.getElementById(id);
    li.classList.remove('is-active', 'is-done');
    if (cls) li.classList.add(cls);
  }

  let exporting = false;
  async function runExport() {
    if (exporting || !state.items.length) return;
    if ([...state.media.values()].some((m) => m.status === 'loading')) { toast('Wait until every clip has finished loading.'); return; }
    pause();
    exporting = true;
    const d = els.dialog;
    $('#export-run').hidden = false;
    $('#export-done').hidden = true;
    $('#export-error').hidden = true;
    $('#download').hidden = true;
    $('#upload-meter').style.width = '0%';
    $('#upload-detail').textContent = '';
    $('#render-detail').textContent = '';
    stepState('step-upload', 'is-active');
    stepState('step-render', null);
    renderFormat();
    if (!d.open) d.showModal();

    let timer = 0;
    try {
      const used = [...new Set(state.items.map((i) => i.mediaId))].map((id) => state.media.get(id));
      const pending = used.filter((m) => !m.remote);
      const bytes = pending.reduce((s, m) => s + m.file.size, 0) || 1;
      let done = 0;
      for (const [n, m] of pending.entries()) {
        $('#upload-detail').textContent = `${n + 1} of ${pending.length} · ${fmtBytes(bytes)}`;
        await upload(m, (loaded) => { $('#upload-meter').style.width = `${Math.round(((done + loaded) / bytes) * 100)}%`; });
        done += m.file.size;
      }
      $('#upload-meter').style.width = '100%';
      $('#upload-detail').textContent = pending.length ? 'Done' : 'Already uploaded';
      stepState('step-upload', 'is-done');
      stepState('step-render', 'is-active');
      const began = Date.now();
      timer = setInterval(() => { $('#render-detail').textContent = `${Math.round((Date.now() - began) / 1000)}s`; }, 500);

      const body = {
        clips: state.items.map((item) => ({
          id: item.id,
          file: mediaOf(item).remote,
          start_seconds: round3(item.start),
          duration_seconds: floor3(item.length),
        })),
        style: 'clean',  // the renderer has one look today; styles return when they render differently
        layout: state.layout,
        size: state.size,
      };
      const response = await fetch(`/api/projects/${state.projectId}/render`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 404) used.forEach((m) => { m.remote = null; });  // server lost the files; re-upload next time
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Rendering failed.');
      }
      clearInterval(timer);
      stepState('step-render', 'is-done');
      const url = `${data.url}?v=${Date.now()}`;
      $('#result-video').src = url;
      const [w, h] = SIZES[state.size];
      $('#result-meta').textContent = `${w} × ${h} · ${fmt(total())}`;
      const link = $('#download');
      link.href = url;
      link.download = `${($('#project-title').value || 'reroll-edit').trim().replace(/[^\w\- ]+/g, '').replace(/\s+/g, '-') || 'reroll-edit'}.mp4`;
      link.hidden = false;
      $('#export-run').hidden = true;
      $('#export-done').hidden = false;
      state.exported = true;
      renderSaveState();
    } catch (error) {
      clearInterval(timer);
      const msg = $('#export-error');
      msg.textContent = String(error.message || error);
      msg.hidden = false;
    } finally {
      exporting = false;
    }
  }
  els.exportOpen.addEventListener('click', runExport);
  els.dialog.addEventListener('close', () => { $('#result-video').pause(); });

  // ---------- project ----------

  $('#new-project').addEventListener('click', () => {
    if (state.items.length && !confirm('Start a new edit? Your current clips will be removed from this tab.')) return;
    pause();
    for (const m of state.media.values()) URL.revokeObjectURL(m.url);
    state.media.clear();
    state.items = [];
    state.selected = null;
    state.mediaSel = null;
    state.time = 0;
    state.projectId = newProjectId();
    history.undo = [];
    history.redo = [];
    updateHistoryButtons();
    els.fg.removeAttribute('src');
    els.bg.removeAttribute('src');
    delete els.fg.dataset.media;
    $('#project-title').value = 'Untitled edit';
    changed();
  });
  window.addEventListener('beforeunload', (e) => {
    if (state.items.length) { e.preventDefault(); e.returnValue = ''; }
  });

  // Panels resize with the window, the splitters and collapsing; keep the stage and lanes in step.
  const ro = new ResizeObserver(() => {
    layoutStage();
    sizeLanes();
    renderTimeline();
  });
  ro.observe(els.canvas);
  ro.observe(els.tl);

  applyPrefs();
  sizeLanes();
  changed();
  layoutStage();
})();
