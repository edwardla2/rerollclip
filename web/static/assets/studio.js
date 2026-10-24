/* Clip That web editor.
 * Model: media (uploaded files) and timeline items (references into media with their own
 * in/out). One file can appear on the timeline several times. Items play back-to-back
 * (ripple edit). Export uploads each used file once, then asks the server to render a
 * schema-v1 manifest with the same renderer the Mac app uses. */
(() => {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const MAX_BYTES = 250 * 1024 * 1024;
  const MAX_ITEMS = 30;          // server limit per render
  const MAX_LEN = 120;           // renderer limit per clip, seconds
  const MIN_LEN = 0.2;
  const EXT = /\.(mp4|mov|webm|mkv)$/i;
  const uid = () => crypto.randomUUID().replace(/-/g, '');

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
  };

  const els = {
    frame: $('#frame'), fg: $('#v-fg'), bg: $('#v-bg'),
    play: $('#play'), tcNow: $('#tc-now'), tcTotal: $('#tc-total'),
    mediaList: $('#media-list'), fileInput: $('#file-input'), drop: $('#drop'),
    track: $('#track'), ruler: $('#ruler'), inner: $('#tl-inner'), scroll: $('#tl-scroll'), playhead: $('#playhead'),
    tlCount: $('#tl-count'), zoom: $('#zoom'),
    clipEmpty: $('#clip-empty'), clipFields: $('#clip-fields'), clipName: $('#clip-name'),
    fStart: $('#f-start'), fEnd: $('#f-end'), fLength: $('#f-length'), clipSourceLen: $('#clip-source-len'),
    exportOpen: $('#export-open'), dialog: $('#export-dialog'), toast: $('#toast'),
  };

  // ---------- helpers ----------

  function loadProjectId() {
    let id = null;
    try { id = localStorage.getItem('clipthat.project'); } catch (_) { /* storage blocked */ }
    if (id && /^[0-9a-f]{32}$/.test(id)) return id;
    return newProjectId();
  }
  function newProjectId() {
    const id = uid();
    try { localStorage.setItem('clipthat.project', id); } catch (_) { /* fine without */ }
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
  function fmtShort(t) {
    const m = Math.floor(t / 60);
    const s = Math.round(t - m * 60);
    return `${m}:${String(s).padStart(2, '0')}`;
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
      const m = { id: uid(), file, name: file.name, url: URL.createObjectURL(file), duration: 0, thumb: '', status: 'loading', remote: null };
      state.media.set(m.id, m);
      const probed = probe(m);
      // Probes run in parallel, but clips join the timeline in the order they were chosen.
      importChain = importChain.then(() => probed).then(() => {
        if (m.status === 'ready') {
          if (state.items.length < MAX_ITEMS) addItem(m.id, !state.selected);
          else toast(`The timeline holds up to ${MAX_ITEMS} clips.`, true);
        } else {
          toast(`Your browser can’t read “${m.name}”. Try converting it to MP4 (H.264).`, true);
        }
        renderBin();
      });
    }
    renderBin();
    els.fileInput.value = '';
  }

  /** Reads duration and grabs a thumbnail frame. */
  function probe(m) {
    return new Promise((resolve) => {
      const v = document.createElement('video');
      v.preload = 'auto';
      v.muted = true;
      v.playsInline = true;
      let settled = false;
      const finish = (status) => {
        if (settled) return;
        settled = true;
        m.status = status;
        v.removeAttribute('src');
        v.load();
        resolve();
      };
      v.onerror = () => finish('error');
      v.onloadedmetadata = () => {
        if (!Number.isFinite(v.duration) || v.duration <= 0) { finish('error'); return; }
        m.duration = v.duration;
        v.currentTime = Math.min(1, v.duration / 3);
      };
      v.onseeked = () => {
        try {
          const h = 90;
          const w = Math.max(1, Math.round(h * (v.videoWidth || 16) / (v.videoHeight || 9)));
          const c = document.createElement('canvas');
          c.width = w; c.height = h;
          c.getContext('2d').drawImage(v, 0, 0, w, h);
          m.thumb = c.toDataURL('image/jpeg', 0.72);
        } catch (_) { /* thumbnail is optional */ }
        finish('ready');
      };
      setTimeout(() => finish(m.duration > 0 ? 'ready' : 'error'), 15000);
      v.src = m.url;
    });
  }

  function removeMedia(id) {
    const m = state.media.get(id);
    if (!m) return;
    state.items = state.items.filter((i) => i.mediaId !== id);
    if (state.selected && !selectedItem()) state.selected = state.items[0]?.id || null;
    if (els.fg.dataset.media === id) { els.fg.removeAttribute('src'); els.bg.removeAttribute('src'); delete els.fg.dataset.media; }
    URL.revokeObjectURL(m.url);
    state.media.delete(id);
    changed();
  }

  // ---------- timeline items ----------

  function addItem(mediaId, select = true) {
    const m = state.media.get(mediaId);
    if (!m || m.status !== 'ready') return;
    if (state.items.length >= MAX_ITEMS) { toast(`The timeline holds up to ${MAX_ITEMS} clips.`, true); return; }
    const item = { id: uid(), mediaId, start: 0, length: Math.min(MAX_LEN, m.duration) };
    state.items.push(item);
    if (select) state.selected = item.id;
    changed();
  }

  function removeItem(id) {
    const index = state.items.findIndex((i) => i.id === id);
    if (index < 0) return;
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
    const second = { id: uid(), mediaId: item.mediaId, start: item.start + cut, length: item.length - cut };
    item.length = cut;
    state.items.splice(loc.index + 1, 0, second);
    state.selected = second.id;
    changed();
  }

  function setTrim(item, start, length) {
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
    renderBin();
    renderTimeline();
    renderInspector();
    els.exportOpen.disabled = !state.items.length;
    els.tcTotal.textContent = fmt(tot);
    if (!state.playing) seek(state.time);
  }

  function renderBin() {
    const list = els.mediaList;
    list.replaceChildren();
    const usage = new Map();
    state.items.forEach((i) => usage.set(i.mediaId, (usage.get(i.mediaId) || 0) + 1));
    for (const m of state.media.values()) {
      const li = document.createElement('li');
      li.className = 'media';
      const thumb = document.createElement('div');
      thumb.className = 'media-thumb' + (m.status === 'loading' ? ' is-loading' : '');
      if (m.thumb) thumb.style.backgroundImage = `url(${m.thumb})`;
      const info = document.createElement('div');
      const name = document.createElement('div');
      name.className = 'media-name';
      name.textContent = m.name;
      name.title = m.name;
      const meta = document.createElement('div');
      meta.className = 'media-meta' + (m.status === 'error' ? ' is-error' : '');
      const uses = usage.get(m.id) || 0;
      meta.textContent = m.status === 'loading' ? 'Reading…'
        : m.status === 'error' ? 'Can’t read in browser'
        : `${fmt(m.duration)}${uses ? ` · used${uses > 1 ? ` ×${uses}` : ''}` : ''}`;
      info.append(name, meta);
      const actions = document.createElement('div');
      actions.className = 'media-actions';
      if (m.status === 'ready') {
        const add = document.createElement('button');
        add.type = 'button'; add.className = 'mini'; add.textContent = '+';
        add.title = 'Add to timeline'; add.setAttribute('aria-label', `Add ${m.name} to timeline`);
        add.addEventListener('click', () => addItem(m.id));
        actions.append(add);
      }
      const del = document.createElement('button');
      del.type = 'button'; del.className = 'mini'; del.textContent = '×';
      del.title = 'Remove from media'; del.setAttribute('aria-label', `Remove ${m.name}`);
      del.addEventListener('click', () => removeMedia(m.id));
      actions.append(del);
      li.append(thumb, info, actions);
      list.append(li);
    }
  }

  function renderInspector() {
    const item = selectedItem();
    els.clipEmpty.hidden = !!item;
    els.clipFields.hidden = !item;
    if (!item) return;
    const m = mediaOf(item);
    els.clipName.textContent = m.name;
    if (document.activeElement !== els.fStart) els.fStart.value = item.start.toFixed(1);
    if (document.activeElement !== els.fEnd) els.fEnd.value = (item.start + item.length).toFixed(1);
    if (document.activeElement !== els.fLength) els.fLength.value = item.length.toFixed(1);
    els.fStart.max = Math.max(0, m.duration - MIN_LEN).toFixed(1);
    els.fEnd.max = m.duration.toFixed(1);
    els.clipSourceLen.textContent = `Source clip is ${fmt(m.duration)} long.` + (m.duration > MAX_LEN ? ' Each clip can use up to 2 minutes of it.' : '');
  }

  function rulerStep(pps) {
    for (const s of [1, 2, 5, 10, 15, 30, 60, 120]) if (s * pps >= 70) return s;
    return 300;
  }

  function renderTimeline() {
    const pps = state.zoom;
    const tot = total();
    const visible = els.scroll.clientWidth - 32;
    const contentWidth = Math.max(visible, tot * pps + 240);
    els.inner.style.width = `${contentWidth + 32}px`;
    els.tlCount.textContent = state.items.length
      ? `${state.items.length} ${state.items.length === 1 ? 'clip' : 'clips'} · ${fmt(tot)}`
      : 'No clips';

    // ruler
    els.ruler.replaceChildren();
    const step = rulerStep(pps);
    const minor = step / 5;
    for (let t = 0; t * pps <= contentWidth; t += minor) {
      const major = Math.abs(t / step - Math.round(t / step)) < 1e-6;
      const tick = document.createElement('div');
      tick.className = 'tick' + (major ? '' : ' minor');
      tick.style.left = `${t * pps}px`;
      if (major) tick.textContent = fmtShort(t);
      els.ruler.append(tick);
    }

    // clips
    els.track.replaceChildren();
    if (!state.items.length) {
      const empty = document.createElement('div');
      empty.className = 'track-empty';
      empty.textContent = 'Uploaded clips appear here in order.';
      els.track.append(empty);
    }
    state.items.forEach((item) => els.track.append(buildItem(item)));
    layoutItems();
    updatePlayhead();
  }

  function buildItem(item) {
    const m = mediaOf(item);
    const el = document.createElement('div');
    el.className = 'item' + (item.id === state.selected ? ' is-selected' : '');
    el.dataset.id = item.id;
    el.setAttribute('role', 'button');
    el.setAttribute('aria-label', `${m.name}, ${item.length.toFixed(1)} seconds`);
    if (m.thumb) el.style.backgroundImage = `url(${m.thumb})`;
    const label = document.createElement('span');
    label.className = 'item-label';
    label.textContent = m.name;
    const len = document.createElement('span');
    len.className = 'item-len';
    const hl = document.createElement('span');
    hl.className = 'handle handle-l';
    hl.title = 'Drag to trim the start';
    const hr = document.createElement('span');
    hr.className = 'handle handle-r';
    hr.title = 'Drag to trim the end';
    el.append(label, len, hl, hr);
    el.addEventListener('pointerdown', (e) => onItemPointerDown(e, item, el));
    return el;
  }

  /** Positions existing item elements without rebuilding them (keeps pointer capture alive). */
  function layoutItems() {
    const pps = state.zoom;
    let x = 0;
    for (const item of state.items) {
      const el = els.track.querySelector(`.item[data-id="${item.id}"]`);
      if (el) {
        el.style.left = `${x * pps}px`;
        el.style.width = `${Math.max(6, item.length * pps)}px`;
        el.querySelector('.item-len').textContent = `${item.length.toFixed(1)}s`;
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
      els.track.querySelectorAll('.item').forEach((n) => n.classList.toggle('is-selected', n.dataset.id === item.id));
      renderInspector();
    }

    const onMove = (ev) => {
      const dx = ev.clientX - startX;
      if (!moved && Math.abs(dx) < 3) return;
      moved = true;
      const ds = dx / pps;
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
        renderTimeline();
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

  els.zoom.addEventListener('input', () => {
    state.zoom = Number(els.zoom.value);
    renderTimeline();
  });
  els.scroll.addEventListener('wheel', (e) => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    state.zoom = clamp(state.zoom * (e.deltaY < 0 ? 1.15 : 0.87), 8, 120);
    els.zoom.value = String(Math.round(state.zoom));
    renderTimeline();
  }, { passive: false });

  // ---------- inspector ----------

  function applyFields(source) {
    const item = selectedItem();
    if (!item) return;
    const start = Number(els.fStart.value);
    const end = Number(els.fEnd.value);
    const length = Number(els.fLength.value);
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
    setTrim(item, 0, MAX_LEN);
    changed();
  });
  $('#split').addEventListener('click', splitAtPlayhead);
  $('#remove-item').addEventListener('click', () => { if (state.selected) removeItem(state.selected); });

  const layoutHelp = {
    fit_blur: 'Shows the whole frame with a blurred copy behind it.',
    center_crop: 'Fills the frame by cropping the sides. Keep the action centered.',
  };
  document.querySelectorAll('.seg [data-layout]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.layout = btn.dataset.layout;
      document.querySelectorAll('.seg [data-layout]').forEach((b) => b.setAttribute('aria-checked', String(b === btn)));
      els.frame.dataset.layout = state.layout;
      $('#layout-help').textContent = layoutHelp[state.layout];
    });
  });
  $('#size').addEventListener('change', (e) => { state.size = e.target.value; });
  $('#style').addEventListener('change', (e) => { state.style = e.target.value; });

  // ---------- upload / drag and drop ----------

  $('#upload-button').addEventListener('click', () => els.fileInput.click());
  els.drop.addEventListener('click', () => els.fileInput.click());
  els.drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); els.fileInput.click(); } });
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
  document.addEventListener('keydown', (e) => {
    if (els.dialog.open) return;
    const tag = (e.target.tagName || '').toLowerCase();
    if (['input', 'select', 'textarea'].includes(tag) || e.target.isContentEditable) return;
    if (e.key === ' ') { e.preventDefault(); togglePlay(); }
    else if (e.key === 's' || e.key === 'S') { splitAtPlayhead(); }
    else if (e.key === 'Delete' || e.key === 'Backspace') { if (state.selected) { e.preventDefault(); removeItem(state.selected); } }
    else if (e.key === 'Home') { pause(); seek(0); }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      pause();
      seek(state.time + (e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 5 : 0.5));
    }
  });

  // ---------- export ----------

  function stepState(id, cls) {
    const li = document.getElementById(id);
    li.classList.remove('is-active', 'is-done');
    if (cls) li.classList.add(cls);
  }

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

  let exporting = false;
  async function runExport() {
    if (exporting || !state.items.length) return;
    if ([...state.media.values()].some((m) => m.status === 'loading')) { toast('Wait until every clip has finished reading.'); return; }
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
      const video = $('#result-video');
      video.src = url;
      $('#result-meta').textContent = `${state.size} × ${state.size === '480' ? 852 : state.size * 16 / 9} · ${fmt(total())}`;
      const link = $('#download');
      link.href = url;
      link.download = `${($('#project-title').value || 'clip-that-edit').trim().replace(/[^\w\- ]+/g, '').replace(/\s+/g, '-') || 'clip-that-edit'}.mp4`;
      link.hidden = false;
      $('#export-run').hidden = true;
      $('#export-done').hidden = false;
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
