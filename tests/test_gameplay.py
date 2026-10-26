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
