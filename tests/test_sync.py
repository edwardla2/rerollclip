"""Beat-synced edits: rhythm analysis on a generated track, the pacing plan, and a full render."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

from clipthat_editor.beats import analyze_beats
from clipthat_editor.highlight import auto_edit
from clipthat_editor.sync import FINAL_SPEED, MAX_SPEED, MIN_SPEED, plan_to_music
from test_analysis import make_clip

BPM = 140
PERIOD = 60 / BPM
DROP = 16 * PERIOD


def make_track(path: Path, seconds: float = 20) -> None:
    """Kick on every beat, hats between, quiet until a drop on beat 17 (no copyrighted audio)."""
    p, d = f"{PERIOD:.6f}", f"{DROP:.6f}"
    expr = (f"if(lt(t,{d}),0.25,0.9)*sin(2*PI*(50+120*exp(-mod(t,{p})*30))*mod(t,{p}))*exp(-mod(t,{p})*14)"
            f"+if(lt(t,{d}),0.06,0.12)*(random(0)*2-1)*exp(-mod(t+{p}/2,{p})*70)"
            f"+if(gte(t,{d}),0.35*sin(2*PI*55*t),0)")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={seconds}",
                    "-c:a", "aac", str(path)], check=True)


def grid(bpm: float, seconds: float, drop: float) -> dict:
    period = 60 / bpm
    beats = [round(k * period, 3) for k in range(int(seconds / period))]
    return {"bpm": bpm, "beats": beats, "drop": min(beats, key=lambda b: abs(b - drop))}


class PlanTests(unittest.TestCase):
    def test_final_kill_on_the_drop_and_others_on_beats(self):
        music = grid(140, 20, DROP)
        plan = plan_to_music([2.5, 5.8, 8.0, 11.0], 16.6, music)
        self.assertAlmostEqual(plan["kills_at_output"][-1], plan["drop_at_output"], places=3)
        self.assertTrue(all(plan["kills_on_beat"]), plan)

    def test_speeds_stay_watchable_and_segments_are_ordered(self):
        plan = plan_to_music([2.5, 5.8, 8.0, 11.0], 16.6, grid(140, 20, DROP))
        last = -1.0
        for s in plan["segments"]:
            self.assertGreater(s["end"], s["start"])
            self.assertGreaterEqual(s["start"], last - 1e-6)
            last = s["end"]
            self.assertTrue(s["speed"] == FINAL_SPEED or MIN_SPEED <= s["speed"] <= MAX_SPEED, s)
        self.assertLessEqual(last, 16.6 + 1e-6)

    def test_output_timing_matches_the_plan(self):
        """Walk the segments: each kill must sit at the output time the plan promises."""
        kills = [2.5, 5.8, 8.0, 11.0]
        plan = plan_to_music(kills, 16.6, grid(140, 20, DROP))
        for kill, promised in zip(kills, plan["kills_at_output"]):
            t = 0.0
            for s in plan["segments"]:
                if s["start"] <= kill <= s["end"]:
                    t += (kill - s["start"]) / s["speed"]
                    break
                t += (s["end"] - s["start"]) / s["speed"]
            self.assertAlmostEqual(t + plan["sound_start"] - plan["sound_start"], promised, delta=0.02)

    def test_kills_too_close_together_stay_natural(self):
        plan = plan_to_music([5.0, 5.4, 9.0], 12, grid(120, 20, 8.0))
        self.assertAlmostEqual(plan["kills_at_output"][-1], plan["drop_at_output"], places=3)

    def test_single_kill(self):
        plan = plan_to_music([6.0], 10, grid(128, 20, 5.0))
        self.assertGreater(plan["output_seconds"], 2)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class RhythmAndRenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_tempo_beats_and_drop(self):
        track = self.dir / "track.m4a"
        make_track(track)
        r = analyze_beats(track)
        self.assertAlmostEqual(r["bpm"], BPM, delta=0.5)
        self.assertAlmostEqual(r["drop"], DROP, delta=0.06)
        # The grid stays on the kicks to the end of the track (no drift).
        self.assertAlmostEqual(r["beats"][40] % PERIOD if r["beats"][40] % PERIOD < PERIOD / 2 else r["beats"][40] % PERIOD - PERIOD,
                               0, delta=0.03)

    def test_synced_render_without_the_music(self):
        clip, track = self.dir / "clip.mp4", self.dir / "track.m4a"
        make_clip(clip, 16, [3.0, 7.0, 11.0])
        make_track(track)
        out, preview = self.dir / "edit.mp4", self.dir / "preview.mp4"
        result = auto_edit(clip, out, profile="generic", width=720, height=1280, music=track, music_preview=preview,
                           sync="beats")
        self.assertEqual(result["events"]["source"], "audio-hits")
        self.assertAlmostEqual(result["kills_at_output"][-1], result["drop_at_output"], delta=0.01)
        for path in (out, preview):
            data = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_format", "-of", "json", str(path)],
                                             capture_output=True, text=True, check=True).stdout)
            self.assertAlmostEqual(float(data["format"]["duration"]), result["output_seconds"], delta=0.3)


if __name__ == "__main__":
    unittest.main()


class HitSyncTests(unittest.TestCase):
    def music(self, hits, strength=None):
        m = grid(127, 30, 14.4)
        m["accents"] = [{"hits": hits, "strength": strength or [0.8] * len(hits), "score": 10.0}]
        return m

    def test_each_kill_lands_on_a_hit(self):
        from clipthat_editor.sync import plan_to_hits
        hits = [12.53, 12.99, 13.24, 13.47, 13.71, 13.94]
        strength = [0.48, 0.74, 0.51, 0.87, 0.67, 0.91]
        kills = [2.13, 5.67, 7.6, 10.87]
        plan = plan_to_hits(kills, 16.6, self.music(hits, strength))
        self.assertEqual(plan["mode"], "hits")
        self.assertEqual(plan["hits"], [13.24, 13.47, 13.71, 13.94])  # strongest 4 in a row
        # Walk the segments: every kill must reach the output exactly at its hit.
        for kill, hit in zip(plan["kills"], plan["hits"]):
            t = 0.0
            for s in plan["segments"]:
                if s["start"] <= kill <= s["end"]:
                    t += (kill - s["start"]) / s["speed"]
                    break
                t += (s["end"] - s["start"]) / s["speed"]
            self.assertAlmostEqual(t, hit - plan["sound_start"], delta=0.02)

    def test_no_run_long_enough_falls_back_to_beats(self):
        from clipthat_editor.sync import plan_for
        plan = plan_for([2.0, 5.0, 8.0, 11.0], 16, self.music([13.0, 13.5]))
        self.assertEqual(plan["mode"], "beats")

    def test_kills_closer_than_the_hits_slow_down_to_fit(self):
        from clipthat_editor.sync import plan_to_hits
        plan = plan_to_hits([5.0, 5.2, 9.0], 12, self.music([10.0, 10.6, 11.2]))
        self.assertTrue(any(s["speed"] < 1 for s in plan["segments"][:3]), plan["segments"])


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
class AccentTests(unittest.TestCase):
    def test_finds_the_standout_run(self):
        """A steady beat with a burst of six much louder hits: the burst is the run."""
        from clipthat_editor.beats import accent_runs
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duns.m4a"
            p = 0.47
            # Busy beat (kick + hats) with a break at 10-11.5 s: the music drops out and six
            # staccato hits play, like the "dun dun dun" before a drop in edit sounds.
            burst = "+".join(f"between(t,{10 + i * 0.235},{10 + i * 0.235 + 0.15})*(0.6*(random(0)*2-1)+0.8*sin(2*PI*55*t))*exp(-(t-{10 + i * 0.235})*22)"
                             for i in range(6))
            beat = (f"0.5*sin(2*PI*(50+120*exp(-mod(t,{p})*30))*mod(t,{p}))*exp(-mod(t,{p})*14)"
                    f"+0.12*(random(0)*2-1)*exp(-mod(t+{p}/2,{p})*60)+0.08*(random(0)*2-1)*exp(-mod(t,{p}/4)*90)")
            expr = f"if(between(t,9.95,11.45),0,1)*({beat})+{burst}"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            f"aevalsrc='{expr}':s=44100:d=16", "-c:a", "aac", str(path)], check=True)
            runs = accent_runs(path)
            self.assertTrue(runs)
            hits = runs[0]["hits"]
            self.assertGreaterEqual(len([h for h in hits if 9.95 <= h <= 11.5]), 5, hits)
