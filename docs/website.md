# Website (waitlist + demo)

Static page in `web/static/`, one serverless function in `api/beta-interest.js`, signups in Supabase.
Hosted on Vercel (free Hobby plan). Nothing to build.

## One-time setup

1. **Supabase**: create a project (free tier). SQL editor → run `supabase/waitlist.sql`.
   Project settings → API: copy the Project URL and the `service_role` key.
2. **Vercel**: Add New → Project → import `edwardla2/rerollclip`. Leave the framework as "Other";
   `vercel.json` sets the output folder. Before deploying, add Environment Variables:
   - `SUPABASE_URL` = the Project URL
   - `SUPABASE_SERVICE_ROLE_KEY` = the service_role key (server-only; never put it in the page)
3. Deploy. Every push to the main branch redeploys.

Signups appear in Supabase → Table editor → `waitlist`. Without the env vars the form answers
"Signups are not open yet".

## Local

`python -m uvicorn web.server:app --port 8765` serves the same page; its `/api/beta-interest`
stores signups in a local SQLite file instead of Supabase.

## Demo media

`web/static/assets/media/demo.mp4` is `renders/v006/edit.mp4` at 540×960, 30 fps, CRF 29 (~6.7 MB).
The poster is the ACE frame (54.2 s). Gameplay used with the player's permission.
