/* Reroll Studio — browser editor.
 * Model: media (uploaded files) and timeline items (references into media with their own
 * in/out). One file can appear on the timeline several times. Items play back-to-back
 * (ripple edit). Export uploads each used file once, then asks the server to render a
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
  const TILE_W = 72;             // filmstrip tile width, px
  const EXT = /\.(mp4|mov|webm|mkv)$/i;
  const SIZES = { 480: [480, 852], 720: [720, 1280], 1080: [1080, 1920] };
  const LAYOUT_NAMES = { fit_blur: 'Blur fill', center_crop: 'Crop' };
  const uid = () => crypto.randomUUID().replace(/-/g, '');
  const icon = (name) => `<svg class="i" aria-hidden="true"><use href="#i-${name}"/></svg>`;

  const state = {
    projectId: loadProjectId(),
    media: new Map(),
    items: [],
    selected: null,
    zoom: 36,          // pixels per second
    time: 0,           // playhead, seconds into the timeline
    playing: false,
    layout: 'fit_blur',
    size: '1080',
    style: 'clean',
    trimLength: 8,
    dirty: false,
  };

  const els = {
    frame: $('#frame'), fg: $('#v-fg'), bg: $('#v-bg'),
    play: $('#play'), tcNow: $('#tc-now'), tcTotal: $('#tc-total'),
    mediaList: $('#media-list'), mediaCount: $('#media-count'), fileInput: $('#file-input'), drop: $('#drop'),
    track: $('#track'), audioLane: $('#audio-lane'), ruler: $('#ruler'), inner: $('#tl-inner'), scroll: $('#tl-scroll'),
    playhead: $('#playhead'), tlCount: $('#tl-count'), zoom: $('#zoom'),
    clipEmpty: $('#clip-empty'), clipFields: $('#clip-fields'), clipName: $('#clip-name'), clipThumb: $('#clip-thumb'),
    rangeSel: $('#clip-range-sel'),
    fStart: $('#f-start'), fEnd: $('#f-end'), fLength: $('#f-length'), clipSourceLen: $('#clip-source-len'),
    exportOpen: $('#export-open'), dialog: $('#export-dialog'), toast: $('#toast'),
    undo: $('#undo'), redo: $('#redo'), saveState: $('#bar-hint'), stageFormat: $('#stage-format'),
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

  function fmt(t) {
    t = Math.max(0, t || 0);
    const m = Math.floor(t / 60);
    const s = t - m * 60;
    return `${m}:${s.toFixed(1).padStart(4, '0')}`;
  }
  function fmtClock(t) {
    const total = Math.round(Math.max(0, t || 0));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
  }
  function fmtRuler(t) {
    if (t < 60) return `${t}s`;
    const m = Math.floor(t / 60);
    const s = Math.round(t - m * 60);
    return s ? `${m}m${s}s` : `${m}m`;
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
    for (const file of ok) {
      const m = { id: uid(), file, name: file.name, url: URL.createObjectURL(file), duration: 0, thumb: '', thumbs: [], status: 'loading', remote: null, peaks: null };
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

  /** Reads duration and grabs several frames for thumbnails and the timeline filmstrip. */
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
        const n = clamp(Math.ceil(v.duration / 2), 4, 12);
        times = Array.from({ length: n }, (_, k) => Math.min(v.duration - 0.05, (k + 0.5) * v.duration / n));
        v.currentTime = times[0];
      };
      v.onseeked = () => {
        try {
          const h = 96;
          const w = Math.max(1, Math.round(h * (v.videoWidth || 16) / (v.videoHeight || 9)));
          canvas.width = w; canvas.height = h;
          canvas.getContext('2d').drawImage(v, 0, 0, w, h);
          m.thumbs.push({ t: times[index], url: canvas.toDataURL('image/jpeg', 0.7) });
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
    checkpoint();
    state.items = state.items.filter((i) => i.mediaId !== id);
    if (state.selected && !selectedItem()) state.selected = state.items[0]?.id || null;
    if (els.fg.dataset.media === id) { els.fg.removeAttribute('src'); els.bg.removeAttribute('src'); delete els.fg.dataset.media; }
    URL.revokeObjectURL(m.url);
    state.media.delete(id);
    // History entries can't bring back a removed file.
    history.undo.forEach((s) => { s.items = s.items.filter((i) => i.mediaId !== id); });
    changed();
  }

  // ---------- timeline items ----------

  function addItem(mediaId, select = true) {
    const m = state.media.get(mediaId);
    if (!m || m.status !== 'ready') return;
    if (state.items.length >= MAX_ITEMS) { toast(`The timeline holds up to ${MAX_ITEMS} clips.`, true); return; }
    checkpoint();
    const item = { id: uid(), mediaId, start: 0, length: Math.min(MAX_LEN, m.duration) };
    state.items.push(item);
    if (select) state.selected = item.id;
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

  async function seek(t) {
    state.time = clamp(t, 0, total());
    const loc = locate(state.time);
    if (!loc) {
      els.frame.classList.remove('has-clip');
      current = -1;
      updatePlayhead();
      return;
    }
    els.frame.classList.add('has-clip');
    current = loc.index;
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
    }
    raf = requestAnimationFrame(tick);
  }

  function togglePlay() { state.playing ? pause() : play(); }

  // ---------- rendering the UI ----------

  function changed() {
    const tot = total();
    if (state.time > tot) state.time = tot;
    state.dirty = state.items.length > 0;
    renderBin();
    renderTimeline();
    renderInspector();
    renderFormat();
    els.exportOpen.disabled = !state.items.length;
    $('#auto-trim-all').disabled = !state.items.length;
    $('#auto-trim-run').disabled = !state.items.length;
    els.tcTotal.textContent = fmt(tot);
    els.saveState.classList.toggle('is-dirty', state.dirty);
    if (!state.playing) seek(state.time);
  }

  function renderBin() {
    const list = els.mediaList;
    list.replaceChildren();
    const usage = new Map();
    state.items.forEach((i) => usage.set(i.mediaId, (usage.get(i.mediaId) || 0) + 1));
    els.mediaCount.textContent = state.media.size ? `${state.media.size} ${state.media.size === 1 ? 'clip' : 'clips'}` : '';
    for (const m of state.media.values()) {
      const li = document.createElement('li');
      li.className = 'mcard';
      const thumb = document.createElement('div');
      thumb.className = 'mthumb' + (m.status === 'loading' ? ' is-loading' : '') + (m.status === 'error' ? ' is-error' : '');
      if (m.thumb) thumb.style.backgroundImage = `url(${m.thumb})`;
      if (m.status === 'error') thumb.textContent = 'Can’t read in browser';
      if (m.status === 'ready') {
        const badge = document.createElement('span');
        badge.className = 'mbadge';
        badge.textContent = fmtClock(m.duration);
        thumb.append(badge);
        thumb.title = 'Add to timeline';
        thumb.addEventListener('click', () => addItem(m.id));
      }
      const uses = usage.get(m.id) || 0;
      if (uses) {
        const used = document.createElement('span');
        used.className = 'mused';
        used.textContent = uses > 1 ? `Used ×${uses}` : 'Added';
        thumb.append(used);
      }
      const actions = document.createElement('div');
      actions.className = 'mactions';
      if (m.status === 'ready') {
        const add = document.createElement('button');
        add.type = 'button'; add.className = 'mini'; add.innerHTML = icon('plus');
        add.title = 'Add to timeline'; add.setAttribute('aria-label', `Add ${m.name} to timeline`);
        add.addEventListener('click', (e) => { e.stopPropagation(); addItem(m.id); });
        actions.append(add);
      }
      const del = document.createElement('button');
      del.type = 'button'; del.className = 'mini mini-del'; del.innerHTML = icon('x');
      del.title = 'Remove from media'; del.setAttribute('aria-label', `Remove ${m.name}`);
      del.addEventListener('click', (e) => { e.stopPropagation(); removeMedia(m.id); });
      actions.append(del);
      thumb.append(actions);
      const name = document.createElement('div');
      name.className = 'mname';
      name.textContent = m.name;
      name.title = m.name;
      li.append(thumb, name);
      list.append(li);
    }
  }

  function renderInspector() {
    const item = selectedItem();
    els.clipEmpty.hidden = !!item;
    els.clipFields.hidden = !item;
    $('#stat-clips').textContent = String(state.items.length);
    $('#stat-length').textContent = fmtClock(total());
    $('#stat-output').textContent = SIZES[state.size].join(' × ');
    if (!item) return;
    const m = mediaOf(item);
    els.clipName.textContent = m.name;
    els.clipName.title = m.name;
    els.clipThumb.style.backgroundImage = `url(${thumbAt(m, item.start + item.length / 2)})`;
    if (document.activeElement !== els.fStart) els.fStart.value = item.start.toFixed(1);
    if (document.activeElement !== els.fEnd) els.fEnd.value = (item.start + item.length).toFixed(1);
    if (document.activeElement !== els.fLength) els.fLength.value = item.length.toFixed(1);
    els.fStart.max = Math.max(0, m.duration - MIN_LEN).toFixed(1);
    els.fEnd.max = m.duration.toFixed(1);
    els.rangeSel.style.left = `${(item.start / m.duration) * 100}%`;
    els.rangeSel.style.width = `${(item.length / m.duration) * 100}%`;
    els.clipSourceLen.textContent = `Using ${fmt(item.length)} of ${fmt(m.duration)}` + (m.duration > MAX_LEN ? ' · max 2:00 per clip' : '');
  }

  function renderFormat() {
    const [w, h] = SIZES[state.size];
    const text = `9:16 · ${state.size}p · ${LAYOUT_NAMES[state.layout]}`;
    els.stageFormat.textContent = text;
    $('#export-format').textContent = `${w} × ${h} · ${LAYOUT_NAMES[state.layout]}`;
  }

  function rulerStep(pps) {
    for (const s of [1, 2, 5, 10, 15, 30, 60, 120]) if (s * pps >= 64) return s;
    return 300;
  }

  function renderTimeline() {
    const pps = state.zoom;
    const tot = total();
    const visible = els.scroll.clientWidth - 32;
    const contentWidth = Math.max(visible, tot * pps + 240);
    els.inner.style.width = `${contentWidth + 32}px`;
    els.tlCount.textContent = state.items.length ? `${state.items.length} clips` : '';

    // ruler: sparse labels, dotted subdivisions
    els.ruler.replaceChildren();
    const step = rulerStep(pps);
    const dots = 4;
    for (let t = 0; t * pps <= contentWidth; t += step) {
      const tick = document.createElement('div');
      tick.className = 'tick';
      tick.style.left = `${t * pps}px`;
      tick.textContent = fmtRuler(t);
      els.ruler.append(tick);
      for (let k = 1; k <= dots; k++) {
        const x = (t + (k * step) / (dots + 1)) * pps;
        if (x > contentWidth) break;
        const dot = document.createElement('div');
        dot.className = 'dot-tick';
        dot.style.left = `${x}px`;
        els.ruler.append(dot);
      }
    }

    // lanes
    els.track.replaceChildren();
    els.audioLane.replaceChildren();
    if (!state.items.length) {
      const empty = document.createElement('div');
      empty.className = 'track-empty';
      empty.textContent = 'Uploaded clips line up here. Drag to reorder, drag the edges to trim.';
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
    const len = document.createElement('span');
    len.className = 'item-len';
    const tag = document.createElement('span');
    tag.className = 'item-tag';
    tag.textContent = 'Suggested';
    const hl = document.createElement('span');
    hl.className = 'handle handle-l';
    hl.title = 'Drag to trim the start';
    const hr = document.createElement('span');
    hr.className = 'handle handle-r';
    hr.title = 'Drag to trim the end';
    el.append(strip, len, tag, hl, hr);
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
    const n = Math.min(60, Math.max(1, Math.ceil(width / TILE_W)));
    if (strip.childElementCount !== n) {
      strip.replaceChildren(...Array.from({ length: n }, () => document.createElement('span')));
    }
    [...strip.children].forEach((tile, i) => {
      tile.style.width = `${TILE_W}px`;
      const t = clamp(item.start + ((i + 0.5) * TILE_W) / pps, item.start, item.start + item.length);
      const url = thumbAt(m, t);
      const bg = url ? `url(${url})` : '';
      if (tile.style.backgroundImage !== bg) tile.style.backgroundImage = bg;
    });
  }

  function drawWaveform(el, item, width) {
    const m = mediaOf(item);
    const canvas = el.querySelector('canvas');
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.min(4096, Math.round(width)));
    const h = 44;
    el.classList.toggle('is-silent', m.peaks === 'silent');
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    if (!(m.peaks instanceof Float32Array)) {
      if (m.peaks !== 'silent') {  // still loading or unavailable: a quiet baseline
        ctx.fillStyle = 'rgba(138,123,255,.35)';
        ctx.fillRect(0, h / 2 - 0.5, w, 1);
      }
      return;
    }
    const pps = state.zoom;
    ctx.fillStyle = 'rgba(176,165,255,.9)';
    const bar = 2, gap = 1;
    for (let x = 0; x < w; x += bar + gap) {
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
      const width = Math.max(6, item.length * pps);
      const el = els.track.querySelector(`.item[data-id="${item.id}"]`);
      if (el) {
        el.style.left = `${x * pps}px`;
        el.style.width = `${width}px`;
        el.querySelector('.item-len').textContent = `${item.length.toFixed(1)}s`;
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

    if (state.selected !== item.id) {
      state.selected = item.id;
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
        const t = (ev.clientX - rect.left) / pps;
        const others = state.items.filter((i) => i !== item);
        let acc = 0;
        dropIndex = others.length;
        for (let k = 0; k < others.length; k++) {
          if (t < acc + others[k].length / 2) { dropIndex = k; break; }
          acc += others[k].length;
        }
        const boundary = others.slice(0, dropIndex).reduce((s, i) => s + i.length, 0);
        if (!marker) { marker = document.createElement('div'); marker.className = 'drop-marker'; els.track.append(marker); }
        marker.style.left = `${boundary * pps - 1}px`;
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

  function seekFromPointer(e, container) {
    const rect = container.getBoundingClientRect();
    if (state.playing) pause();
    seek((e.clientX - rect.left) / state.zoom);
  }
  els.ruler.addEventListener('pointerdown', (e) => seekFromPointer(e, els.ruler));
  els.track.addEventListener('pointerdown', (e) => { if (e.target === els.track) seekFromPointer(e, els.track); });
  els.audioLane.addEventListener('pointerdown', (e) => seekFromPointer(e, els.audioLane));

  function setZoom(z) {
    state.zoom = clamp(z, 8, 120);
    els.zoom.value = String(Math.round(state.zoom));
    renderTimeline();
  }
  els.zoom.addEventListener('input', () => setZoom(Number(els.zoom.value)));
  $('#zoom-in').addEventListener('click', () => setZoom(state.zoom * 1.25));
  $('#zoom-out').addEventListener('click', () => setZoom(state.zoom / 1.25));
  els.scroll.addEventListener('wheel', (e) => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    setZoom(state.zoom * (e.deltaY < 0 ? 1.15 : 0.87));
  }, { passive: false });

  // ---------- rail panels ----------

  $$('.rail-btn[data-pane]').forEach((btn) => {
    btn.addEventListener('click', () => {
      $$('.rail-btn[data-pane]').forEach((b) => {
        const on = b === btn;
        b.classList.toggle('is-active', on);
        b.setAttribute('aria-selected', String(on));
      });
      $$('.pane').forEach((p) => { p.hidden = p.dataset.pane !== btn.dataset.pane; });
    });
  });

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
  $('#reset-trim').addEventListener('click', () => {
    const item = selectedItem();
    if (!item) return;
    checkpoint();
    setTrim(item, 0, MAX_LEN);
    changed();
  });
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
  radioGroup('.seg [data-layout]', 'layout', (v) => { state.layout = v; els.frame.dataset.layout = v; renderFormat(); });
  radioGroup('#size-seg [data-size]', 'size', (v) => { state.size = v; renderFormat(); renderInspector(); });
  radioGroup('#style-chips [data-style]', 'style', (v) => { state.style = v; });
  radioGroup('#trim-length [data-len]', 'len', (v) => { state.trimLength = Number(v); });

  // ---------- upload / drag and drop ----------

  const openPicker = () => els.fileInput.click();
  $('#upload-button').addEventListener('click', openPicker);
  $('#empty-upload').addEventListener('click', openPicker);
  els.drop.addEventListener('click', openPicker);
  els.drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openPicker(); } });
  els.fileInput.addEventListener('change', (e) => importFiles(e.target.files));
  let dragDepth = 0;
  window.addEventListener('dragenter', (e) => { if (e.dataTransfer?.types?.includes('Files')) { dragDepth++; document.body.classList.add('is-dragging'); } });
  window.addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) document.body.classList.remove('is-dragging'); });
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
    const mod = e.metaKey || e.ctrlKey;
    if (mod && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if (mod && (e.key === 'y' || e.key === 'Y')) { e.preventDefault(); redo(); return; }
    if (mod) return;
    if (e.key === ' ') { e.preventDefault(); togglePlay(); }
    else if (e.key === 's' || e.key === 'S') { splitAtPlayhead(); }
    else if (e.key === 'Delete' || e.key === 'Backspace') { if (state.selected) { e.preventDefault(); removeItem(state.selected); } }
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
    withBusy($('#suggest-trim'), 'Analyzing…', async () => {
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
        progress(`Analyzing ${n + 1}/${items.length}…`);
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
        $('#upload-detail').textContent = `${n + 1} of ${pending.length}`;
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
        style: state.style,
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
      state.dirty = false;
      els.saveState.classList.remove('is-dirty');
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
  window.addEventListener('resize', () => renderTimeline());

  changed();
})();
