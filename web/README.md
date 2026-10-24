# Clip That website — local functional prototype

This is a local browser demo for Clip That, including a marketing page and basic editing workspace. It is not a public hosted product or a complete AI editor.

## Setup

You need Python 3.10+ with `fastapi`, `python-multipart`, `uvicorn`, and `ffmpeg`/`ffprobe` on PATH.

From the repository root (`clip-that-starter/`), run:

```bash
python -m pip install -r web/requirements.txt
python -m uvicorn web.server:app --host 127.0.0.1 --port 8765
```

Visit `http://127.0.0.1:8765` in your browser.

> Bind to localhost only. The MVP API deliberately has no user authentication. Do **not** expose it publicly as-is.

## What works now

1. Click “Start creating free.”
2. Upload a few short videos from your computer (maximum 250 MB each in this demo).
3. Choose a clip to preview, adjust its start and duration, and reorder clips on the timeline.
4. Set crop/layout and output size and select a style label.
5. Click “Create montage” and download the resulting portrait MP4.

Browser previews reflect the original uploaded clip, not yet the composite timeline. Only the exported video reflects all clips. The preset names do not yet change the rendering style. No automatic highlights, voice capture, cloud saves, sync, payments, or AI effects are available. Uploaded data is saved to `.web_runtime/` **on the same local computer** and isn't automatically deleted; remove that folder to delete local demo data. If running this code on a remote host, uploads would go to that server instead.

## API (local MVP only)

- `GET /api/health`
- `POST /api/projects/{project_id}/clips` — multipart `file` upload
- `POST /api/projects/{project_id}/render` — renders the shared v1 manifest to an MP4
- `GET /api/projects/{project_id}/output`

Project IDs are lowercase UUID hex strings. There is no authentication or project persistence in the browser beyond a project ID. Add authorization and signed access before public deployment.

## Tests

```bash
python -m pip install -r web/requirements-dev.txt
python -m pytest -q
```

## Owner

ChatGPT owns this `web/` folder; Claude should build inside `desktop/` and follow the shared renderer contract.
