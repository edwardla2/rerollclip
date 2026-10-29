(() => {
  'use strict';
  // The die: pip layout per face on a 3x3 grid (cells 0..8).
  const FACES = { 1: [4], 2: [0, 8], 3: [0, 4, 8], 4: [0, 2, 6, 8], 5: [0, 2, 4, 6, 8], 6: [0, 2, 3, 5, 6, 8] };
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function draw(die, face) {
    if (!die.children.length) for (let i = 0; i < 9; i++) die.appendChild(document.createElement('i'));
    [...die.children].forEach((pip, i) => pip.classList.toggle('on', FACES[face].includes(i)));
    die.dataset.face = String(face);
  }
  // Roll: flick through random faces, then land on `face`.
  function roll(die, face, steps = 6) {
    if (reduced) { draw(die, face); return; }
    die.classList.remove('rolling'); void die.offsetWidth; die.classList.add('rolling');
    let n = 0;
    const t = setInterval(() => {
      n += 1;
      if (n >= steps) { clearInterval(t); draw(die, face); return; }
      let f; do { f = 1 + Math.floor(Math.random() * 6); } while (String(f) === die.dataset.face);
      draw(die, f);
    }, 70);
  }
  window.rerollDie = roll;
  document.querySelectorAll('.die').forEach((d) => draw(d, Number(d.dataset.face) || 1));

  // Logo lands on two (the watermark's face) on load and rerolls on hover.
  const logo = document.querySelector('#logo .die');
  if (logo) {
    roll(logo, 2, 9);
    document.getElementById('logo').addEventListener('mouseenter', () => roll(logo, 2));
  }
  // Every other die rerolls to its own face when you hover it or its row/button.
  document.querySelectorAll('.cta, .list li, .row button').forEach((host) => {
    const d = host.querySelector('.die');
    if (d) host.addEventListener('mouseenter', () => roll(d, Number(d.dataset.home || (d.dataset.home = d.dataset.face))));
  });
})();

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

  // The demo's real cut list (renders/v007): [start, end, clip, sped up]
  const SHOTS = [[0, 4.45, 1, 0], [4.45, 6.2, 1, 1], [6.2, 7.7, 1, 0], [7.7, 9.82, 1, 1], [9.82, 12.78, 1, 0],
    [12.78, 14.18, 1, 1], [14.18, 20.82, 1, 0], [20.82, 24.82, 2, 0], [24.82, 26.93, 2, 1], [26.93, 36.33, 2, 0],
    [36.33, 39.38, 2, 0], [39.38, 41.6, 2, 1], [41.6, 45.5, 2, 0], [45.5, 50.15, 2, 0], [50.15, 52.23, 2, 1],
    [52.23, 59.23, 2, 0], [59.23, 76.38, 3, 0], [76.38, 77.2, 3, 1], [77.2, 81.2, 3, 0], [81.2, 86.55, 4, 0],
    [86.55, 87.6, 4, 1], [87.6, 91.75, 4, 0], [91.75, 93.8, 4, 1], [93.8, 101.15, 4, 0]];
  const TOTAL = 101.15;
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
    time.textContent = `${fmt(t)} / 1:41`;
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
      status.innerHTML = '<span class="die" data-face="6" aria-hidden="true"></span>You rolled a six. You’re on the list, and I’ll email you when there’s a spot.'; status.className = 'status ok'; const d6 = status.querySelector('.die'); window.rerollDie && window.rerollDie(d6, 6, 10);
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
  // Jumping to a section (a "Join the waitlist" link, or a shared #beta link) shows everything at
  // once, so the form is never caught mid-reveal.
  const showAll = () => items.forEach((el) => { el.classList.remove('pending'); io.unobserve(el); });
  if (location.hash) { items.forEach((el) => el.classList.add('reveal')); return; }
  document.querySelectorAll('a[href^="#"]').forEach((a) => a.addEventListener('click', showAll));
  window.addEventListener('hashchange', showAll);
  items.forEach((el, i) => {
    el.classList.add('reveal');
    if (el.getBoundingClientRect().top > window.innerHeight) {
      el.classList.add('pending');
      el.style.transitionDelay = el.matches('.list li') ? `${(i % 4) * 70}ms` : '0ms';
      io.observe(el);
    }
  });
})();
