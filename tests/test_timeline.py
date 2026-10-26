"""The editing timeline (curves, nonlinear time remap), the director's plan, and the compositor."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from clipthat_editor.director import KeyBuilder, exp_ramp, fit_ramp_end, velocity_montage
from clipthat_editor.timeline import Clip, Curve, TimeKey, Timeline


def music(bpm=80.0, drop=8.675, seconds=60):
    p = 60 / bpm
    b0 = drop % p
    return {"bpm": bpm, "beats": [round(b0 + k * p, 4) for k in range(int(seconds / p))], "drop": drop, "file": "x"}


class CurveTests(unittest.TestCase):
    def test_eases(self):
        c = Curve().add(0, 0).add(1, 10, "smooth")
        self.assertAlmostEqual(c.at(0.5), 5.0)
        self.assertLess(c.at(0.1), 1.0)          # eases in
        self.assertEqual(c.at(2), 10)
        self.assertEqual(Curve().add(0, 0).add(1, 10, "hold").at(0.99), 0)

    def test_expression_matches_python(self):
        """The FFmpeg expression and Curve.at agree (checked by FFmpeg itself via a test signal)."""
        if not shutil.which("ffmpeg"):
            self.skipTest("FFmpeg required")
        c = Curve().add(0, 0).add(0.5, 1, "out3").add(1.0, 0.25, "smooth")
        expr = c.expr("T")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.raw"
            # Brightness from the expression on a black frame, read back per frame.
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=16x16:r=20:d=1",
                            "-vf", f"format=gray,geq=lum='200*({expr})'", "-f", "rawvideo", str(out)],
                           check=True)
            raw = out.read_bytes()
        for i in range(20):
            got = raw[i * 256]
            self.assertAlmostEqual(got, 200 * c.at(i / 20), delta=1.5, msg=f"frame {i}")


class TimeRemapTests(unittest.TestCase):
    def clip(self):
        kb = KeyBuilder(1.0).ramp(1.0, 2.6, 0.375, 2).snap(0.28).ramp(0.28, 0.42, 0.56, 2).ramp(0.42, 6.0, 0.6, 5)
        return Clip("c", 10.0, 10.0 + kb.src, 0.0, kb.keys)

    def test_keys_hit_exactly_and_time_moves_forward(self):
        c = self.clip()
        for k in c.keys:
            self.assertAlmostEqual(c.out_at(k.src), k.out, places=6)
        last = -1.0
        for i in range(1, 400):
            o = c.out_at(c.keys[-1].src * i / 400)
            self.assertGreater(o, last)
            last = o

    def test_speed_follows_the_ramp(self):
        c = self.clip()
        impact = c.keys[2].src
        self.assertGreater(c.speed_at(impact - 0.02), 1.8)       # fast going in
        self.assertLess(c.speed_at(impact + 0.01), 0.4)          # snaps into slow motion
        self.assertGreater(c.speed_at(c.keys[-1].src - 0.01), 3.5)  # whips out

    def test_ramp_maths(self):
        self.assertAlmostEqual(exp_ramp(1, 1, 2), 2)
        end = fit_ramp_end(0.4, 1.0, 1.5)
        self.assertAlmostEqual(exp_ramp(0.4, end, 1.0), 1.5, places=3)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_ffmpeg_remap_has_the_planned_length(self):
        c = self.clip()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "o.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=4",
                            "-vf", f"trim=duration={c.src_out - c.src_in:.4f},setpts=PTS-STARTPTS,"
                                   f"setpts='({c.setpts_expr()})/TB',fps=60", str(out)], check=True)
            dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                        "csv=p=0", str(out)], capture_output=True, text=True).stdout)
            self.assertAlmostEqual(dur, c.out_dur, delta=0.05)


class DirectorTests(unittest.TestCase):
    def plan(self):
        return velocity_montage("clip.mp4", 52.3, [9.3, 12.5, 20.55, 34.75, 50.2], music(), count=5,
                                words=["little", "aggro"])

    def test_every_kill_lands_on_its_beat_first_on_the_drop(self):
        tl = self.plan()
        self.assertEqual(tl.check(), [])
        kills = [9.3, 12.5, 20.55, 34.75, 50.2]
        p = 60 / 80
        for i, k in enumerate(kills):
            c = next(c for c in tl.clips if c.label == f"kill {i + 1}")
            landed = c.out_start + c.out_at(k - c.src_in)
            self.assertAlmostEqual(landed, tl.music["kills_at"][i], places=3)
            song_time = landed + tl.music["start"]
            self.assertLess(abs((song_time - music()["beats"][0]) / p - round((song_time - music()["beats"][0]) / p)), 1e-3)
        self.assertAlmostEqual(tl.music["kills_at"][0] + tl.music["start"], 8.675, delta=0.01)

    def test_no_footage_repeats_within_the_story(self):
        tl = self.plan()
        story = [c for c in tl.clips if not c.label.startswith("replay")]
        for a, b in zip(story, story[1:]):
            self.assertGreaterEqual(b.src_in, a.src_out - 1e-3, (a.label, b.label))

    def test_effects_are_on_kills_and_cuts_not_everywhere(self):
        tl = self.plan()
        flash = tl.master["flash"]
        lit = sum(1 for i in range(int(tl.duration * 60)) if flash.at(i / 60) > 0.05)
        self.assertLess(lit / (tl.duration * 60), 0.12)          # flashes are brief accents
        self.assertEqual(flash.at(1.0), 0.0)                     # the calm intro has none

    def test_round_trips_through_json(self):
        tl = self.plan()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            tl.save(path)
            back = Timeline.load(path)
        self.assertEqual(back.to_json(), tl.to_json())


if __name__ == "__main__":
    unittest.main()


class ChunkTests(unittest.TestCase):
    def test_slow_motion_is_split_out(self):
        kb = KeyBuilder(1.0).ramp(1.0, 2.6, 0.375, 2).snap(0.28).ramp(0.28, 0.42, 0.56, 2).ramp(0.42, 6.0, 0.6, 5)
        c = Clip("c", 10.0, 10.0 + kb.src, 0.0, kb.keys)
        runs = c.chunks()
        self.assertEqual([r[2] for r in runs], [False, True, False])
        self.assertEqual(runs[0][0], 0)
        self.assertEqual(runs[-1][1], len(c.keys) - 1)
        for a, b in zip(runs, runs[1:]):
            self.assertEqual(a[1], b[0])        # contiguous, no key lost

    def test_chunk_chain_offsets_time(self):
        from clipthat_editor.compositor import chunk_video_chain
        kb = KeyBuilder(1.0).ramp(1.0, 2.6, 0.375, 2).snap(0.28).ramp(0.28, 0.42, 0.56, 2)
        c = Clip("c", 10.0, 10.0 + kb.src, 5.0, kb.keys, zoom=Curve().add(0, 1.2).add(0.5, 1.0, "out3"))
        tl = Timeline(1920, 1080, 60, "s.mp4", [c])
        k0, k1, slow = c.chunks()[1]
        chain = chunk_video_chain(c, k0, k1, slow, tl, 30.0)
        self.assertIn("minterpolate", chain)
        self.assertIn(f"(t+{c.keys[k0].out:.6f})", chain)
        self.assertIn(f"(T+{c.keys[k0].src:.6f})", chain)
