"""Taste profile and the gameplay-first planner."""
import unittest

from clipthat_editor import taste as taste_mod
from clipthat_editor.director import gameplay_first, rank_events, recipes_for

KILLS = [9.3, 12.5, 20.55, 34.75, 50.2]


def music(bpm=80.0, drop=8.675, seconds=60):
    p = 60 / bpm
    b0 = drop % p
    return {"bpm": bpm, "beats": [round(b0 + k * p, 4) for k in range(int(seconds / p))], "drop": drop, "file": "x"}


def plan(**over):
    t = taste_mod.load(branding={"enabled": False}, **over)
    return gameplay_first("clip.mp4", 52.33, KILLS, music(), t, count=5)


class TasteTests(unittest.TestCase):
    def test_default_profile_is_valid_and_portrait(self):
        t = taste_mod.load()
        self.assertEqual(t["format"]["aspect"], "9:16")
        self.assertEqual(t["text"]["mode"], "off")
        self.assertFalse(t["accents"]["continuous_effects"])

    def test_overrides_and_validation(self):
        self.assertEqual(taste_mod.load(intensity="aggressive")["intensity"], "aggressive")
        with self.assertRaises(ValueError):
            taste_mod.load(intensity="nuclear")


class PlannerTests(unittest.TestCase):
    def test_top_event_is_the_final_kill_and_recipes_vary(self):
        events = rank_events(KILLS, 5)
        self.assertTrue(events[-1]["top"])
        rec = recipes_for(events, taste_mod.load())
        self.assertEqual(rec[-1], "hang")
        self.assertTrue(all(a != b for a, b in zip(rec, rec[1:])), rec)     # no repeated preset in a row

    def test_every_kill_lands_on_a_beat_and_plays_at_real_speed_before_it(self):
        tl = plan()
        self.assertEqual(tl.check(), [])
        p = 60 / 80
        b0 = music()["beats"][0]
        for t in tl.music["kills_at"]:
            phase = ((t + tl.music["start"] - b0) / p) % 1
            self.assertLess(min(phase, 1 - phase), 0.02, t)
        for c in tl.clips:
            if c.label.startswith("kill"):
                self.assertAlmostEqual(c.keys[0].speed_out, 1.0)            # the lead-in is readable

    def test_restraint(self):
        tl = plan()
        self.assertEqual(tl.texts, [])                                     # no words by default
        for c in tl.clips:
            top = max(max(k.speed_in, k.speed_out) for k in c.keys)
            self.assertLessEqual(top, 4.0 * 1.5 + 1e-6, c.label)
            self.assertLessEqual(max(k[1] for k in c.zoom.keys), 1.18 + 1e-6)
        mono = tl.master["mono"]
        on = [i / 60 for i in range(int(tl.duration * 60)) if mono.at(i / 60) > 0.5]
        self.assertTrue(on)                                                # one black-and-white accent...
        self.assertLess(on[-1] - on[0], 2.5)                               # ...and only one
        ca = tl.master["ca"]
        self.assertLess(sum(1 for i in range(int(tl.duration * 60)) if ca.at(i / 60) > 0.5) / 60, 0.5)

    def test_restrained_has_no_mono(self):
        tl = plan(intensity="restrained")
        self.assertTrue(tl.master["mono"].is_const(0.0))


if __name__ == "__main__":
    unittest.main()


class StoryTests(unittest.TestCase):
    PLAYS = [
        {"source": "a.mp4", "duration": 52.33, "kills": KILLS, "count": 5, "height": 1080, "game": "valorant",
         "story": [2.1, 8.85, 12.25, 13.05, 13.45, 16.4, 19.95, 38.7, 46.95]},
        {"source": "b.mp4", "duration": 16.6, "kills": [2.25, 5.75, 7.85, 10.85], "count": 5, "height": 360,
         "game": "valorant", "story": [9.45, 10.5]},
    ]

    def plan(self):
        from clipthat_editor.director import story_compilation
        return story_compilation([dict(p) for p in self.PLAYS], music(), taste_mod.load(branding={"enabled": False}))

    def test_best_play_last_and_whole_frame_by_default(self):
        tl = self.plan()
        self.assertEqual(tl.check(), [])
        self.assertEqual(tl.clips[-1].source, "a.mp4")                    # the sharper ace closes
        self.assertTrue(all(c.framing == "full" and not c.feed_inset for c in tl.clips))   # review v001
        self.assertEqual(tl.look["saturation"], 1.0)                       # game colours (review v001)

    def test_crop_profile_crops_sharp_clips_and_squares_low_res(self):
        from clipthat_editor.director import story_compilation
        t = taste_mod.load(branding={"enabled": False}, format={"framing": "crop"}, story={"feed_inset": True})
        tl = story_compilation([dict(p) for p in self.PLAYS], music(), t)
        self.assertTrue(all(c.framing == "fit" for c in tl.clips if c.source == "b.mp4"))
        self.assertTrue(all(c.framing == "crop" and c.feed_inset for c in tl.clips if c.source == "a.mp4"))

    def test_story_kept_in_order_at_real_speed(self):
        tl = self.plan()
        for c in tl.clips:
            if "window" in c.label and "accent" not in c.label:
                self.assertTrue(all(abs(k.speed_in - 1) < 1e-6 or k.speed_in < 1 for k in c.keys), c.label)
        for src in ("a.mp4", "b.mp4"):
            mine = [c for c in tl.clips if c.source == src]
            for x, y in zip(mine, mine[1:]):
                self.assertGreaterEqual(y.src_in, x.src_out - 1e-3)          # never backwards in a play
        kills_shown = len(tl.music["kills_at"])
        self.assertEqual(kills_shown, 9)                                   # every kill of both plays

    def test_real_speed_everywhere_and_no_accent(self):
        # Review v004: nothing sped up or slowed down, no black-and-white accent.
        tl = self.plan()
        for c in tl.clips:
            self.assertTrue(all(abs(k.speed_in - 1) < 1e-6 and abs(k.speed_out - 1) < 1e-6 for k in c.keys), c.label)
        self.assertTrue(all(curve.is_const(0.0) for curve in tl.master.values()))
        for src in ("a.mp4", "b.mp4"):                      # each play is one continuous stretch
            self.assertEqual(sum(1 for c in tl.clips if c.source == src), 1)


class StructureTests(unittest.TestCase):
    """Edward's structure (after v002): build-up with nothing happening, the drop on the first
    kill, then the story with each fight's kill on a beat."""
    def plan(self, m):
        from clipthat_editor.director import story_compilation
        return story_compilation([dict(p) for p in StoryTests.PLAYS], m, taste_mod.load(branding={"enabled": False}))

    def test_buildup_then_first_kill_on_the_drop(self):
        m = music(bpm=92.0, drop=5.0)
        m["drop_strength"], m["duration"] = 0.6, 60.0
        tl = self.plan(m)
        self.assertEqual(tl.check(), [])
        first = min(tl.music["kills_at"])
        self.assertAlmostEqual(first + tl.music["start"], 5.0, delta=0.02)      # first kill on the drop
        self.assertGreaterEqual(first, 2.0 - 1e-6)                              # a real build-up before it

    def test_each_fights_first_kill_on_a_beat(self):
        m = music(bpm=92.0, drop=5.0)
        m["drop_strength"], m["duration"] = 0.6, 60.0
        tl = self.plan(m)
        p, b0 = 60 / 92, m["beats"][0]
        windows = [c for c in tl.clips if "window" in c.label]
        on = 0
        for c in windows:
            play = next(x for x in StoryTests.PLAYS if x["source"] == c.source)
            k = next((k for k in play["kills"] if c.src_in <= k <= c.src_out), None)
            if k is None:
                continue
            t = c.out_start + c.out_at(k - c.src_in) + tl.music["start"]
            ph = ((t - b0) / p) % 1
            on += min(ph, 1 - ph) < 0.03
        self.assertEqual(on, len([c for c in windows if any(c.src_in <= k <= c.src_out for x in StoryTests.PLAYS
                                                             if x["source"] == c.source for k in x["kills"])]))


@unittest.skipUnless(__import__("shutil").which("ffmpeg"), "FFmpeg required")
class EditClipTests(unittest.TestCase):
    """The one-clip flow the desktop app runs for each new Medal clip."""
    def test_edits_a_clip_and_reports_progress(self):
        import json, subprocess, tempfile
        from pathlib import Path
        from clipthat_editor.montage import edit_clip
        from test_analysis import make_clip
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "clip.mp4"
            make_clip(src, 14, [4.0, 9.0])
            stages = []
            r = edit_clip(src, Path(tmp) / "out", profile="generic", work=Path(tmp) / "w", size=(270, 480), fps=30,
                          progress=lambda s, f: stages.append(s))
            self.assertTrue(r["ok"], r)
            out = Path(r["output"])
            self.assertTrue(out.exists() and out.name == "clip (Reroll).mp4")
            self.assertTrue(Path(r["timeline"]).exists())
            self.assertEqual(stages[0], "finding plays")
            self.assertEqual(stages[-1], "done")
            probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
                                              capture_output=True, text=True).stdout)
            v = next(s for s in probe["streams"] if s["codec_type"] == "video")
            self.assertEqual((v["width"], v["height"]), (270, 480))

    def test_a_clip_with_nothing_in_it(self):
        import subprocess, tempfile
        from pathlib import Path
        from clipthat_editor.montage import edit_clip
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "empty.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x180:d=3",
                            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=3", "-shortest", str(src)], check=True)
            r = edit_clip(src, Path(tmp) / "out", profile="generic")
            self.assertEqual((r["ok"], r["reason"]), (False, "no_plays"))
