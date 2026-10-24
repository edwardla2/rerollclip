"""HTTP smoke and security tests for the local-only website."""
import asyncio
import uuid
from pathlib import Path
import subprocess
import tempfile

import httpx
import pytest

from web import server


def request(method: str, endpoint: str, **kwargs):
    async def runner():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test.local") as client:
            return await client.request(method, endpoint, **kwargs)
    return asyncio.run(runner())


def test_home_and_health():
    landing = request("GET", "/")
    assert landing.status_code == 200 and b"Clip That" in landing.content
    health = request("GET", "/api/health")
    assert health.json()["cloud_saving"] is False


def test_rejects_bad_project_and_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "RUNTIME", tmp_path)
    assert request("POST", "/api/projects/../clips").status_code != 200
    project_id = uuid.uuid4().hex
    bad = request("POST", f"/api/projects/{project_id}/render", json={"clips": [{"file": "../not-allowed.mp4", "duration_seconds": 1, "start_seconds": 0}]})
    assert bad.status_code == 400
    missing = request("POST", f"/api/projects/{project_id}/render", json={"clips": [{"file": uuid.uuid4().hex + ".mp4", "duration_seconds": 1, "start_seconds": 0}]})
    assert missing.status_code == 404


def test_upload_limit_and_extension(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "RUNTIME", tmp_path)
    project_id = uuid.uuid4().hex
    bad = request("POST", f"/api/projects/{project_id}/clips", files={"file": ("fake.txt", b"text", "text/plain")})
    assert bad.status_code == 415
    monkeypatch.setattr(server, "MAX_UPLOAD_BYTES", 4)
    oversized = request("POST", f"/api/projects/{project_id}/clips", files={"file": ("test.mp4", b"123456", "video/mp4")})
    assert oversized.status_code == 413
    assert not list((tmp_path / project_id).glob("*.mp4"))
