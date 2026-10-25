"""Reference-edit measurement and the hook caption."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from clipthat_editor.highlight import caption_text, _caption
from clipthat_editor.study import cuts_from_change, events_from_brightness, on_beat_share, study


class StudyMathTests(unittest.TestCase):
    def test_cuts_are_spikes_in_change(self):
        change = [2.0] * 90
        for i in (30, 45, 60):
            change[i] = 60.0
        self.assertEqual(cuts_from_change(change, fps=30), [1.0, 1.5, 2.0])

    def test_on_beat_share(self):
        self.assertEqual(on_beat_share([1.0, 1.52, 2.3], [1.0, 1.5, 2.0, 2.5]), 0.667)

    def test_flash_and_dip(self):
        bright = [100.0] * 30 + [220.0] + [100.0] * 30 + [5.0] * 5
        ev = events_from_brightness(bright, fps=30)
        self.assertEqual(ev["flashes"], [1.0])
        self.assertEqual(ev["dips"], [round(61 / 30, 3)])


class CaptionTests(unittest.TestCase):
    def test_text(self):
        self.assertIsNone(caption_text(None))
        self.assertIsNone(caption_text(1))
        self.assertEqual(caption_text(3), "3K")
        self.assertEqual(caption_text(5), "ACE")

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_caption_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "c.mp4"
            graph = "[0:v]format=yuv420p" + _caption("ACE", 0.0, 1.0, 360, 640) + "[v]"
            done = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=360x640:d=1.5",
                                   "-filter_complex", graph, "-map", "[v]", str(out)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_study_finds_hard_cuts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cuts.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=160x90:d=1",
                            "-f", "lavfi", "-i", "color=c=white:s=160x90:d=1", "-f", "lavfi", "-i", "color=c=gray:s=160x90:d=1",
                            "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-r", "30", str(out)], check=True)
            r = study(out)
            self.assertEqual(len(r["cuts"]), 2, r["cuts"])
            self.assertAlmostEqual(r["cuts"][0], 1.0, delta=0.05)


if __name__ == "__main__":
    unittest.main()
