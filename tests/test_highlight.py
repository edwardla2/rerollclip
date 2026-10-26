"""Highlight auto-edit: decision rules (pure) and end-to-end renders on synthetic clips."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

from clipthat_editor.analysis import STEP
from clipthat_editor.highlight import (MIN_RESULT, PROFILES, auto_edit, decide, encoder_works, pick_encoder)
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
        self.assertEqual(slow[0]["speed"], PROFILES["generic"].slow_factor)
        self.assertTrue(plan["slow_motion"]["applied"])
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

    def test_slow_motion_is_earned_not_automatic(self):
        # A peak barely above a busy background doesn't get slowed down.
        plan = decide(curve(30, {t: 0.4 for t in range(2, 29, 2)} | {18: 0.5}, base=0.35), 30)
        self.assertFalse(plan["slow_motion"]["applied"], plan["slow_motion"])
        self.assertTrue(all(s["speed"] == 1 for s in plan["segments"]))

    def test_profiles_set_slow_motion_and_length(self):
        strong = curve(30, {18: 0.8})
        cs2 = decide(strong, 30, profile="cs2")
        self.assertFalse(cs2["slow_motion"]["applied"])
        self.assertEqual(cs2["slow_motion"]["reason"], "off for cs2")
        valorant = decide(strong, 30, profile="valorant")
        self.assertTrue(valorant["slow_motion"]["applied"])
        slow = [s for s in valorant["segments"] if s["speed"] != 1][0]
        self.assertAlmostEqual(slow["end"] - slow["start"], 2 * PROFILES["valorant"].slow_half, delta=0.01)
        w = decide(strong, 30, profile="fortnite")["window"]
        self.assertAlmostEqual(w["end"] - w["start"], PROFILES["fortnite"].length, delta=0.01)

    def test_slow_motion_override(self):
        strong = curve(30, {18: 0.8})
        self.assertFalse(decide(strong, 30, slow_motion="off")["slow_motion"]["applied"])
        self.assertTrue(decide(strong, 30, profile="cs2", slow_motion="on")["slow_motion"]["applied"])

    def test_unknown_profile_is_refused(self):
        from clipthat_editor.engine import EditorError
        with self.assertRaises(EditorError):
            decide(curve(10, {5: 0.8}), 10, profile="minecraft")

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
        result = auto_edit(src, out, profile="roblox", width=720, height=1280)
        self.assertEqual(result["layout"], "fit_blur", "Roblox keeps the whole frame")
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


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class FocusLayoutTests(unittest.TestCase):
    def test_focus_layout_with_impact_renders(self):
        from clipthat_editor.highlight import Segment, build_filtergraph
        graph = build_filtergraph([Segment(0, 1, impact=True), Segment(1, 2, fade_out=0.3)], src_w=1920, src_h=1080,
                                  width=720, height=1280, fps=30, layout="focus", audio_input="0:a:0")
        self.assertIn("eval=frame", graph)
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "c.mp4", Path(tmp) / "o.mp4"
            make_clip(src, 4, [1.0])
            result = auto_edit(src, out, layout="focus", width=720, height=1280)
            self.assertEqual(result["layout"], "focus")
            data = probe(out)
            video = next(s for s in data["streams"] if s["codec_type"] == "video")
            self.assertEqual((video["width"], video["height"]), (720, 1280))


class RampTests(unittest.TestCase):
    def test_curves_keep_each_segment_length_and_start_where_the_footage_was(self):
        import math
        from clipthat_editor.highlight import Segment, ramp_speeds
        segs = [Segment(0, 0.4, 1.0), Segment(0.4, 0.7, 2.5), Segment(0.7, 0.8, 0.4, impact=True),
                Segment(0.8, 2.0, 2.2), Segment(5.0, 5.3, 2.5)]
        ramps = ramp_speeds(segs)
        self.assertIsNone(ramps[0])
        self.assertIsNone(ramps[2])                                   # the shot itself snaps to slow motion
        self.assertEqual(ramps[1][0], 1.0)                            # continues the run-up's speed
        self.assertEqual(ramps[3][0], 0.4)                            # accelerates out of the slow shot
        self.assertEqual(ramps[4][0], 1.0)                            # after a cut: from normal speed
        for seg, ramp in zip(segs, ramps):
            if ramp:
                s0, s1 = ramp
                length = seg.end - seg.start
                curved = length / (s1 - s0) * math.log(s1 / s0)       # output time of the whole curve
                self.assertAlmostEqual(curved, seg.output_length, delta=0.002)
                self.assertGreater(s1, seg.speed)
