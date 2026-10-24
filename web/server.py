"""Local-only Clip That web demo. Not a public production SaaS server.

From repository root:
    python -m uvicorn web.server:app --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import uuid

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web" / "static"
RUNTIME = Path(os.environ.get("CLIPTHAT_WEB_DATA", str(ROOT / ".web_runtime"))).resolve()
RUNTIME.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = 250 * 1024 * 1024
PROJECT_RE = re.compile(r"^[0-9a-f]{32}$")
FILE_RE = re.compile(r"^[0-9a-f]{32}\.(mp4|mov|webm|mkv)$")
ALLOWED = {".mp4", ".mov", ".webm", ".mkv"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")

app = FastAPI(title="Clip That web proof of concept", version="0.1.0", docs_url=None, redoc_url=None)
app.mount("/assets", StaticFiles(directory=str(STATIC)), name="assets")


class BetaInterest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    consent: bool = False
    website: str = Field(default="", max_length=300)  # Honeypot; should remain empty.


def save_beta_interest(email: str) -> None:
    """Local-only prototype storage; do not deploy without anti-abuse, notice and retention review."""
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(RUNTIME / "beta-interest.sqlite3", timeout=10) as db:
        db.execute("CREATE TABLE IF NOT EXISTS beta_interest (email TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        db.execute("INSERT OR IGNORE INTO beta_interest(email) VALUES (?)", (email,))
        db.commit()


@app.post("/api/beta-interest")
async def beta_interest(request: BetaInterest):
    if not request.consent:
        raise HTTPException(400, "Please confirm consent to register beta interest")
    email = request.email.strip().lower()
    if not EMAIL_RE.fullmatch(email):
        raise HTTPException(422, "Enter a valid email address")
    if request.website:  # Accept honeypot quietly; avoids leaking anti-spam criteria.
        return {"ok": True, "mode": "local-interest-only", "email_sent": False}
    await run_in_threadpool(save_beta_interest, email)
    return {"ok": True, "mode": "local-interest-only", "email_sent": False}


class ClipInput(BaseModel):
    file: str
    start_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0, le=120)


class RenderInput(BaseModel):
    clips: list[ClipInput] = Field(min_length=1, max_length=30)
    style: str = "clean"
    layout: str = "fit_blur"
    size: str = "720"


def project_dir(project_id: str) -> Path:
    if not PROJECT_RE.fullmatch(project_id):
        raise HTTPException(400, "Invalid project ID")
    p = RUNTIME / project_id
    p.mkdir(parents=True, exist_ok=True)
    return p


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html", media_type="text/html")


@app.get("/api/health")
def health():
    return {"ok": True, "mode": "local-demo", "render_engine": "python-ffmpeg", "cloud_saving": False}


@app.post("/api/projects/{project_id}/clips")
async def upload_clip(project_id: str, file: UploadFile = File(...)):
    parent = project_dir(project_id)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(415, "Supported video types: MP4, MOV, WebM and MKV")
    file_name = uuid.uuid4().hex + suffix
    dest = parent / file_name
    size = 0
    try:
        with dest.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "File exceeds local demo limit of 250 MB")
                handle.write(chunk)
        if size == 0:
            raise HTTPException(400, "Empty upload")
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return {"file": file_name, "bytes": size}


@app.post("/api/projects/{project_id}/render")
async def render_project(project_id: str, request: RenderInput):
    parent = project_dir(project_id)
    if request.style not in {"clean", "cinematic", "high_energy"}:
        raise HTTPException(400, "Unsupported preset")
    if request.layout not in {"fit_blur", "center_crop"}:
        raise HTTPException(400, "Unsupported layout")
    if request.size not in {"480", "720", "1080"}:
        raise HTTPException(400, "Unsupported resolution")
    clips = []
    for clip in request.clips:
        if not FILE_RE.fullmatch(clip.file):
            raise HTTPException(400, "Invalid uploaded clip reference")
        if not (parent / clip.file).is_file():
            raise HTTPException(404, "Uploaded clip no longer exists")
        clips.append({"file": clip.file, "start_seconds": clip.start_seconds, "duration_seconds": clip.duration_seconds})
    height = int(request.size) * 16 // 9
    width = int(request.size)
    # output width is actually portrait's shorter side. 480 => 480x852 (even), 720=>720x1280, 1080=>1080x1920.
    if request.size == "480":
        height = 852
    manifest = {"schema_version": 1, "session_id": project_id, "style": request.style,
                "layout": request.layout, "output": {"width": width, "height": height, "fps": 30},
                "clips": clips, "music": None}
    manifest_path = parent / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    output = parent / "render.mp4"
    cmd = [sys.executable, "-m", "clipthat_editor", "render", str(manifest_path), "--output", str(output)]

    def run_cli():
        return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=600)

    try:
        result = await run_in_threadpool(run_cli)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Render timed out")
    if result.returncode != 0:
        details = result.stderr[-1400:]
        try:
            details = json.loads(details).get("error", details)
        except (ValueError, AttributeError):
            pass
        raise HTTPException(422, f"Render failed: {details}")
    if not output.is_file() or not output.stat().st_size:
        raise HTTPException(500, "Renderer exited without a video")
    return {"ok": True, "url": f"/api/projects/{project_id}/output", "bytes": output.stat().st_size}


@app.get("/api/projects/{project_id}/output")
def get_render(project_id: str):
    dest = project_dir(project_id) / "render.mp4"
    if not dest.is_file():
        raise HTTPException(404, "No rendered video yet")
    return FileResponse(dest, media_type="video/mp4", filename="clip-that-edit.mp4")
