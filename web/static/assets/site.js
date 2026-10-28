(() => {
  'use strict';
  const video = document.getElementById('demo-video');
  const sound = document.getElementById('demo-sound');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!video) return;
  if (reduced) { video.removeAttribute('autoplay'); video.pause(); }

  function setMuted(m) {
    video.muted = m;
    if (!m && video.paused) video.play().catch(() => {});
    if (sound) { sound.setAttribute('aria-pressed', String(!m)); sound.textContent = m ? 'Sound off' : 'Sound on'; }
  }
  if (sound) sound.addEventListener('click', () => setMuted(!video.muted));
  video.addEventListener('click', () => setMuted(!video.muted));

  // The demo's real cut list (renders/v006): [start, end, clip, sped up]
  const SHOTS = [[0, 14.15, 1, 0], [14.15, 17.95, 2, 0], [17.95, 20.05, 2, 1], [20.05, 21.55, 2, 0], [21.55, 23.65, 2, 1],
    [23.65, 26.3, 2, 0], [26.3, 29.12, 2, 1], [29.12, 33.12, 2, 0], [33.12, 49.83, 3, 0], [49.83, 50.9, 3, 1],
    [50.9, 54.9, 3, 0], [54.9, 59.8, 4, 0], [59.8, 61.4, 4, 1], [61.4, 64.4, 4, 0], [64.4, 66.45, 4, 1], [66.45, 73.8, 4, 0]];
  const TOTAL = 73.8;
  const track = document.getElementById('edit-track');
  const head = document.getElementById('edit-head');
  const time = document.getElementById('edit-time');
  if (!track) return;
  const segs = SHOTS.map(([a, b, clip, fast], i) => {
    const el = document.createElement('span');
    el.className = 'edit-seg' + (fast ? ' fast' : '') + (i && clip !== SHOTS[i - 1][2] ? ' clip-start' : '');
    el.style.flex = String(b - a);
    el.title = `Clip ${clip}${fast ? ', sped up' : ''}`;
    track.insertBefore(el, head);
    return el;
  });
  const fmt = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
  let last = -1;
  function tick() {
    const t = video.currentTime || 0;
    head.style.left = `calc(${(t / TOTAL) * 100}% - 1px)`;
    const i = SHOTS.findIndex(([a, b]) => t >= a && t < b);
    if (i !== last) { segs.forEach((s, j) => s.classList.toggle('on', j === i)); last = i; }
    time.textContent = `${fmt(t)} / 1:14`;
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
  track.addEventListener('click', (e) => {
    const r = track.getBoundingClientRect();
    video.currentTime = Math.max(0, Math.min(TOTAL - 0.1, ((e.clientX - r.left) / r.width) * TOTAL));
    if (video.paused) video.play().catch(() => {});
  });
})();

(() => {
  'use strict';
  const form = document.getElementById('beta-form');
  if (!form) return;
  const status = document.getElementById('beta-status');
  const button = document.getElementById('beta-submit');

  function show(text, kind) {
    status.textContent = text;
    status.classList.toggle('error', kind === 'error');
    status.classList.toggle('ok', kind === 'ok');
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const email = document.getElementById('beta-email').value.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) { show('Enter a valid email address.', 'error'); return; }
    if (!document.getElementById('beta-consent').checked) { show('Tick the box so we can store your details.', 'error'); return; }
    button.disabled = true;
    show('Saving…');
    try {
      const response = await fetch('/api/beta-interest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email, consent: true,
          game: document.getElementById('beta-game').value,
          windows: '',
          website: document.getElementById('beta-website').value,
        })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Couldn’t save your email. Try again.');
      show('You’re on the list. We’ll email you when there’s a spot.', 'ok');
      form.reset();
    } catch (error) {
      show(String(error.message || error), 'error');
    } finally {
      button.disabled = false;
    }
  });
})();

(() => {
  'use strict';
  // Rows and blocks settle in as they scroll into view. Visible by default; only items still
  // below the fold get the pending state, so nothing is ever hidden at rest.
  if (!('IntersectionObserver' in window) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  document.documentElement.classList.add('js');
  const items = document.querySelectorAll('.list li, .beta-head, .row');
  const io = new IntersectionObserver((entries) => entries.forEach((e) => {
    if (e.isIntersecting) { e.target.classList.remove('pending'); io.unobserve(e.target); }
  }), { rootMargin: '0px 0px -8% 0px' });
  items.forEach((el, i) => {
    el.classList.add('reveal');
    if (el.getBoundingClientRect().top > window.innerHeight) {
      el.classList.add('pending');
      el.style.transitionDelay = el.matches('.list li') ? `${(i % 4) * 70}ms` : '0ms';
      io.observe(el);
    }
  });
})();
