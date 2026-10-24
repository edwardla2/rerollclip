"""Suggested-trim tests on synthetic clips with planted ground truth (no copyrighted footage).

Each clip has a quiet noise bed and a static frame; "moments" are a loud burst plus a
colour flash at known times. The analyser must find the planted moment, frame it with
setup before and reaction after, respect the trigger time for replay clips, and work on
silent clips from visual change alone.
"""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

from clipthat_editor.analysis import analyze, suggest_window, PEAK_POSITION


def make_clip(path: Path, duration: float, moments: list[float], audio: bool = True, flash: bool = True) -> None:
    """Blue frame + quiet noise; each moment = 0.6 s loud burst and/or red flash at that time."""
    boxes = ",".join(f"drawbox=enable='between(t,{t},{t + 0.6})':color=red:t=fill" for t in moments) if flash and moments else "null"
    args = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x203050:s=320x180:r=30:d={duration}"]
    if audio:
        envelope = "+".join(f"between(t,{t},{t + 0.6})" for t in moments) or "0"
        args += ["-f", "lavfi", "-i", f"anoisesrc=d={duration}:a=0.9:r=48000",
                 "-filter_complex", f"[0:v]{boxes}[v];[1:a]volume='if({envelope},1,0.02)':eval=frame[a]",
                 "-map", "[v]", "-map", "[a]", "-c:a", "aac"]
    else:
        args += ["-vf", boxes]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", str(duration), str(path)]
    subprocess.run(args, check=True)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class AnalyzeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def assertFrames(self, result, moment, length):
        start, dur = result["suggested_start"], result["suggested_duration"]
        self.assertAlmostEqual(result["peak_time"], moment + 0.3, delta=0.6, msg=result)
        self.assertLessEqual(start, moment, msg="moment must be inside the window")
        self.assertGreaterEqual(start + dur, moment + 0.6, msg="burst must be inside the window")
        self.assertAlmostEqual(dur, length, delta=0.01)
        self.assertGreater(moment - start, 1.0, msg="needs setup before the moment")

    def test_finds_planted_moment(self):
        clip = self.dir / "a.mp4"
        make_clip(clip, 30, [18.0])
        result = analyze(clip, length=8)
        self.assertEqual(result["signals"], ["audio", "motion"])
        self.assertFrames(result, 18.0, 8)

    def test_picks_the_stronger_of_two_moments(self):
        clip = self.dir / "b.mp4"
        # Two moments; the second has both audio and visual change, the first audio only.
        make_clip(clip, 30, [6.0, 21.0])
        first_only_audio = self.dir / "b2.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(clip), "-vf",
                        "drawbox=enable='between(t,6,6.6)':color=0x203050:t=fill", "-c:a", "copy",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(first_only_audio)], check=True)
        result = analyze(first_only_audio, length=6)
        self.assertFrames(result, 21.0, 6)

    def test_replay_trigger_limits_search_to_before_the_command(self):
        clip = self.dir / "c.mp4"
        # Real moment at 20 s, user says "Clip that" at 24 s, decoy (e.g. teammate yelling) at 28 s.
        make_clip(clip, 31.5, [20.0, 28.0])
        result = analyze(clip, length=8, trigger_offset=24.0)
        self.assertFrames(result, 20.0, 8)
        self.assertLessEqual(result["suggested_start"] + result["suggested_duration"], 24.0 + 1.5 + 0.01)

    def test_silent_clip_uses_visual_change(self):
        clip = self.dir / "d.mp4"
        make_clip(clip, 20, [12.0], audio=False)
        result = analyze(clip, length=6)
        self.assertEqual(result["signals"], ["motion"])
        self.assertFrames(result, 12.0, 6)

    def test_window_never_exceeds_clip(self):
        clip = self.dir / "e.mp4"
        make_clip(clip, 5, [4.5])
        result = analyze(clip, length=8)
        self.assertEqual(result["suggested_start"], 0)
        self.assertLessEqual(result["suggested_duration"], 5.0)

    def test_cli_json(self):
        clip = self.dir / "f.mp4"
        make_clip(clip, 12, [7.0])
        out = subprocess.run([sys.executable, "-m", "clipthat_editor", "analyze", str(clip), "--length", "5"],
                             capture_output=True, text=True, check=True)
        data = json.loads(out.stdout)
        self.assertTrue(data["ok"])
        self.assertIn("suggested_start", data)
        bad = subprocess.run([sys.executable, "-m", "clipthat_editor", "analyze", str(self.dir / "missing.mp4")],
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertFalse(json.loads(bad.stderr)["ok"])


class WindowMathTests(unittest.TestCase):
    def test_peak_sits_70_percent_through(self):
        score = [0.0] * 300
        score[150] = 5.0   # 15.05 s
        w = suggest_window(score, 30.0, 10.0)
        self.assertAlmostEqual((w["peak"] - w["start"]) / w["duration"], PEAK_POSITION, delta=0.02)

    def test_clamped_at_clip_start(self):
        score = [0.0] * 100
        score[5] = 1.0
        self.assertEqual(suggest_window(score, 10.0, 8.0)["start"], 0.0)


if __name__ == "__main__":
    unittest.main()
