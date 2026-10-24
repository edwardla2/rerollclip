# Clip That web backend (Vapor 4)

Serves the landing page and the browser studio from `../web/static`, and the API the studio uses:

| Method | Path | What it does |
|---|---|---|
| GET | `/`, `/studio` | Landing page, web editor |
| GET | `/assets/*` | CSS, JS, fonts |
| GET | `/api/health` | Liveness |
| POST | `/api/beta-interest` | `{email, consent, website}` → stores the email (SQLite), with a honeypot field |
| POST | `/api/projects/:id/clips` | Multipart `file` upload (MP4/MOV/WebM/MKV, 250 MB) → `{file, bytes}` |
| POST | `/api/projects/:id/render` | `{clips:[{id?, file, start_seconds, duration_seconds}], style, layout, size}` → builds a schema-v1 manifest with `ClipThatContracts`, renders it → `{ok, url, bytes}` |
| GET | `/api/projects/:id/output` | The rendered MP4 |

Errors are `{"detail": "..."}` with a matching status code, the same shape as the Python prototype in
`../web`, which this replaces. `Tests/AppTests` mirrors `../web/tests` endpoint for endpoint.

## Run

```bash
swift run App serve          # http://127.0.0.1:8765 (needs python3 + ffmpeg for rendering)
swift test
```

Configuration (environment variables): `HOST`, `PORT`, `CLIPTHAT_WEB_DATA` (uploads/renders; default
`../.web_runtime`), `CLIPTHAT_DB`, `CLIPTHAT_STATIC_DIR`, `CLIPTHAT_EDITOR_ROOT`, `CLIPTHAT_PYTHON`,
`CLIPTHAT_MAX_UPLOAD_MB` (250), `CLIPTHAT_RENDER_TIMEOUT` (600 s), `CLIPTHAT_RETENTION_HOURS` (24:
project folders untouched this long are deleted).

## Before public hosting

Projects are unguessable random ids, not accounts. Before exposing this to the internet it needs
rate limiting, upload quotas, a job queue for renders instead of in-request rendering, and a
privacy notice for the beta list. These are tracked in `docs/STATUS.md`.
