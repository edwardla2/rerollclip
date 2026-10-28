(() => {
  'use strict';
  const video = document.getElementById('demo-video');
  const sound = document.getElementById('demo-sound');
  if (video && sound) {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { video.removeAttribute('autoplay'); video.pause(); video.controls = true; }
    sound.addEventListener('click', () => {
      video.muted = !video.muted;
      if (!video.muted && video.paused) video.play().catch(() => {});
      sound.setAttribute('aria-pressed', String(!video.muted));
      sound.textContent = video.muted ? 'Sound off' : 'Sound on';
    });
  }
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
