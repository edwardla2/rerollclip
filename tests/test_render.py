"""FFmpeg smoke test that uses synthetic footage, no copyrighted assets."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from clipthat_editor.engine import render, probe


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class RenderTests(unittest.TestCase):
    def test_two_clips_with_missing_audio_render_to_portrait(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clips = root / "clips"
            clips.mkdir()
            a, b = clips / "a.mp4", clips / "b.mp4"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=blue:s=320x180:r=12:d=1.5", "-f", "lavfi", "-i",
                            "sine=frequency=440:sample_rate=48000:duration=1.5", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(a)], check=True)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=red:s=320x180:r=12:d=1.5", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", str(b)], check=True)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": 1,
                "session_id": "unit-test",
                "style": "clean",
                "layout": "fit_blur",
                "output": {"width": 360, "height": 640, "fps": 12},
                "clips": [
                    {"id": "1", "file": "clips/a.mp4", "start_seconds": 0, "duration_seconds": 1.2},
                    {"id": "2", "file": "clips/b.mp4", "start_seconds": 0, "duration_seconds": 1.2},
                ],
                "music": None,
            }))
            output = root / "output.mp4"
            render(manifest, output)
            self.assertTrue(output.exists())
            duration, has_audio = probe(output)
            self.assertTrue(has_audio)
            self.assertTrue(2.1 < duration < 2.6)
            result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                     "-show_entries", "stream=width,height", "-of", "json", str(output)],
                                    check=True, capture_output=True, text=True)
            stream = json.loads(result.stdout)["streams"][0]
            self.assertEqual((stream["width"], stream["height"]), (360, 640))
