"""Evaluation harness: edits a Medal-style folder, skips Medal's helper folders, records failures."""
from pathlib import Path
import json
import shutil
import tempfile
import unittest

from clipthat_editor.evaluate import evaluate, find_clips
from test_analysis import make_clip


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class EvaluateTests(unittest.TestCase):
    def test_folder_run_with_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Medal"
            (root / "Roblox").mkdir(parents=True)
            (root / "Edits").mkdir()
            (root / ".thumbnails").mkdir()
            make_clip(root / "Roblox" / "clip one.mp4", 12, [7.0])
            (root / "Roblox" / "broken.mp4").write_text("not a video")
            shutil.copy(root / "Roblox" / "clip one.mp4", root / "Edits" / "edited.mp4")
            shutil.copy(root / "Roblox" / "clip one.mp4", root / ".thumbnails" / "thumb.mp4")
            self.assertEqual([p.name for p in find_clips(root)], ["broken.mp4", "clip one.mp4"])
            out = Path(tmp) / "review"
            summary = evaluate(root, out, profile="roblox", size="720")
            self.assertEqual((summary["clips"], summary["edited"], summary["failed"]), (2, 1, 1))
            data = json.loads((out / "results.json").read_text())
            ok = [r for r in data["clips"] if r["ok"]][0]
            self.assertTrue((out / ok["edit"]).is_file())
            self.assertIn("total_s", ok)
            report = (out / "report.html").read_text()
            self.assertIn("Would you willingly post this edit", report)
            self.assertIn("Failed:", report)


if __name__ == "__main__":
    unittest.main()
