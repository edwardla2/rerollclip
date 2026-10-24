"""Highlight auto-edit: decision rules (pure) and end-to-end renders on synthetic clips."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

from clipthat_editor.analysis import STEP
from clipthat_editor.highlight import (MIN_RESULT, SLOW_FACTOR, auto_edit, decide, encoder_works, pick_encoder)
from test_analysis import make_clip


def curve(duration: float, bumps: dict[float, float], base: float = 0.02) -> list[float]:
    """A score curve: flat base, a 1 s plateau of the given height at each bump time."""
    n = int(duration / STEP)
    out = [base] * n
    for t, h in bumps.items():
        for i in range(int((t - 0.5) / STEP), int((t + 0.5) / STEP)):
            if 0 <= i < n:
                out[i] = h
    return out


class DecideTests(unittest.TestCase):
    def test_peak_plays_slow_and_zoomed(self):
        plan = decide(curve(30, {18: 0.8}), 30)
        slow = [s for s in plan["segments"] if s["speed"] != 1]
        self.assertEqual(len(slow), 1)
        self.assertEqual(slow[0]["speed"], SLOW_FACTOR)
        self.assertGreater(slow[0]["zoom"], 1)
        self.assertLessEqual(slow[0]["start"], plan["peak"])
        self.assertGreaterEqual(slow[0]["end"], plan["peak"])

    def test_dead_air_is_cut_but_not_near_the_peak(self):
        plan = decide(curve(30, {18: 0.8}), 30)
        self.assertTrue(plan["cuts"], "long quiet setup should be cut")
        for c in plan["cuts"]:
            self.assertFalse(c["start"] < plan["peak"] + 1.0 and c["end"] > plan["peak"] - 2.0,
                             msg=f"cut {c} too close to peak {plan['peak']}")

    def test_no_sliver_at_the_window_edges(self):
        plan = decide(curve(30, {18: 0.8}), 30)
        for s in plan["segments"]:
            self.assertGreaterEqual(s["end"] - s["start"], 0.5, msg=plan["segments"])

    def test_segments_are_ordered_and_inside_the_window(self):
        plan = decide(curve(30, {6: 0.5, 18: 0.8}), 30)
        w = plan["window"]
        last = w["start"]
        for s in plan["segments"]:
            self.assertGreaterEqual(s["start"], last - 1e-6)
            self.assertLess(s["start"], s["end"])
            last = s["end"]
        self.assertLessEqual(last, w["end"] + 1e-6)

    def test_never_shorter_than_minimum(self):
        plan = decide(curve(30, {18: 0.8}), 30)
        self.assertGreaterEqual(plan["output_seconds"], MIN_RESULT)

    def test_busy_clip_keeps_everything(self):
        plan = decide(curve(30, {t: 0.7 for t in range(1, 30)}, base=0.6), 30)
        self.assertEqual(plan["cuts"], [])

    def test_trigger_offset_limits_the_search(self):
        # The loudest moment is after the trigger, so it can't be the one the player meant.
        plan = decide(curve(30, {8: 0.5, 25: 0.9}), 30, trigger_offset=10.0)
        self.assertLess(plan["peak"], 10.0)

    def test_short_clip(self):
        plan = decide(curve(4, {2: 0.8}), 4)
        self.assertGreater(plan["output_seconds"], 3.5)


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class AutoEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def check_output(self, result, out: Path, width=1080, height=1920):
        self.assertTrue(out.is_file())
        self.assertFalse(out.with_name(out.stem + ".partial" + out.suffix).exists())
        data = probe(out)
        video = next(s for s in data["streams"] if s["codec_type"] == "video")
        audio = [s for s in data["streams"] if s["codec_type"] == "audio"]
        self.assertEqual((video["width"], video["height"]), (width, height))
        self.assertEqual(len(audio), 1, "every edit has an audio track")
        duration = float(data["format"]["duration"])
        self.assertAlmostEqual(duration, result["output_seconds"], delta=0.25)
        self.assertLess(abs(float(video["duration"]) - float(audio[0]["duration"])), 0.15, "audio stays in sync")

    def test_edits_a_clip_end_to_end(self):
        src, out = self.dir / "clip.mp4", self.dir / "edit.mp4"
        make_clip(src, 30, [18.0])
        result = auto_edit(src, out)
        self.check_output(result, out)
        self.assertAlmostEqual(result["peak"], 18.3, delta=0.6)
        self.assertLess(result["output_seconds"], 30)
        self.assertIn("total_s", result["timings"])

    def test_silent_clip_with_blur_fill_at_720(self):
        src, out = self.dir / "silent.mp4", self.dir / "edit.mp4"
        make_clip(src, 20, [12.0], audio=False)
        result = auto_edit(src, out, layout="fit_blur", width=720, height=1280)
        self.assertEqual(result["signals"], ["motion"])
        self.check_output(result, out, 720, 1280)

    def test_cpu_encoder_always_available(self):
        self.assertEqual(pick_encoder("libx264"), "libx264")
        self.assertIn(pick_encoder("auto"), {"libx264", "h264_nvenc", "h264_amf", "h264_qsv", "h264_videotoolbox"})

    def test_unavailable_hardware_encoder_falls_back(self):
        if encoder_works("h264_nvenc"):
            self.skipTest("this machine has NVENC")
        self.assertEqual(pick_encoder("h264_nvenc"), "libx264")


if __name__ == "__main__":
    unittest.main()
