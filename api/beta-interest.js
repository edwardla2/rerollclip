// Vercel serverless function: saves a waitlist signup to Supabase.
// Env vars (Vercel project settings): SUPABASE_URL and SUPABASE_SECRET_KEY (a secret key, sb_secret_...,
// from Settings > API Keys; the legacy service_role key in SUPABASE_SERVICE_ROLE_KEY also works).
// The key stays on the server; the table has row-level security on and no public policies.
const GAMES = new Set(['', 'valorant', 'cs2', 'fortnite', 'roblox', 'other']);
const WINDOWS = new Set(['', '11', '10', 'unsure']);
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ detail: 'Method not allowed' });
  }
  const body = typeof req.body === 'string' ? safeJson(req.body) : (req.body || {});
  const email = String(body.email || '').trim().toLowerCase();
  const game = String(body.game || '');
  const windows = String(body.windows || '');
  if (body.website) return res.status(200).json({ ok: true });   // honeypot: accept quietly
  if (body.consent !== true) return res.status(400).json({ detail: 'Tick the box so we can store your details.' });
  if (email.length > 254 || !EMAIL.test(email)) return res.status(422).json({ detail: 'Enter a valid email address.' });
  if (!GAMES.has(game) || !WINDOWS.has(windows)) return res.status(422).json({ detail: 'Pick a game and Windows version from the list.' });

  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return res.status(503).json({ detail: 'Signups are not open yet. Try again soon.' });

  try {
    // Upsert on email: signing up twice keeps one row and updates the answers.
    const r = await fetch(`${url.replace(/\/$/, '')}/rest/v1/waitlist?on_conflict=email`, {
      method: 'POST',
      headers: {
        apikey: key,
        // New sb_secret_ keys aren't JWTs and go only in `apikey`; a legacy service_role JWT also needs Bearer.
        ...(key.startsWith('sb_') ? {} : { Authorization: `Bearer ${key}` }),
        'Content-Type': 'application/json',
        Prefer: 'resolution=merge-duplicates,return=minimal',
      },
      body: JSON.stringify({ email, game: game || null, windows: windows || null, source: 'site' }),
    });
    if (!r.ok) {
      console.error('supabase', r.status, (await r.text()).slice(0, 300));
      return res.status(502).json({ detail: 'Couldn’t save your email. Try again.' });
    }
    return res.status(200).json({ ok: true });
  } catch (err) {
    console.error('supabase', err);
    return res.status(502).json({ detail: 'Couldn’t save your email. Try again.' });
  }
};

function safeJson(text) {
  try { return JSON.parse(text); } catch { return {}; }
}
