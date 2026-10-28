"""Clip library: picking the plays for a compilation."""
import unittest

from clipthat_editor.library import pick, same_play, score

FRAME = [100] * (32 * 18)
OTHER = [30] * (32 * 18)


def play(name, kills, count=None, ace=None, mtime=0.0, prints=None, confidence="high", duration=40.0):
    return {"source": f"/clips/{name}.mp4", "kills": kills, "count": count or len(kills), "ace_at": ace,
            "mtime": mtime, "prints": prints or [], "duration": duration, "story": [], "action": [],
            "confidence": confidence, "height": 1080}


class PickTests(unittest.TestCase):
    def test_strongest_plays_and_duplicates_once(self):
        plays = [play("a", [10.0, 15.0], prints=[OTHER]), play("ace", [5, 9, 14, 20], count=5, ace=21.0, prints=[FRAME]),
                 play("ace again", [3, 7, 12, 18], count=5, prints=[FRAME])]
        chosen, notes = pick(plays)
        names = [p["source"] for p in chosen]
        self.assertIn("/clips/ace.mp4", names)
        self.assertNotIn("/clips/ace again.mp4", names)               # same footage at a kill
        self.assertTrue(any("same play" in n for n in notes))

    def test_length_budget_and_recent_only(self):
        plays = [play(f"p{i}", [10.0, 20.0, 30.0], mtime=float(i)) for i in range(8)]
        chosen, _ = pick(plays, max_seconds=60)
        self.assertLess(len(chosen), 8)
        chosen, _ = pick(plays, since=6.0)
        self.assertTrue(all(p["mtime"] >= 6.0 for p in chosen))

    def test_unconfirmed_kills_only_as_a_last_resort(self):
        sure, unsure = play("sure", [10.0]), play("unsure", [5, 6, 7, 8, 9, 10], confidence="low")
        chosen, notes = pick([sure, unsure])
        self.assertEqual([p["source"] for p in chosen], ["/clips/sure.mp4"])
        chosen, _ = pick([unsure])
        self.assertEqual(len(chosen), 1)

    def test_score_and_same_play(self):
        self.assertGreater(score(play("x", [1, 2, 3, 4], count=5)), score(play("y", [1, 2, 3, 4])))
        self.assertTrue(same_play(play("a", [1], prints=[FRAME]), play("b", [2], prints=[FRAME])))
        self.assertFalse(same_play(play("a", [1], prints=[FRAME]), play("b", [2], prints=[OTHER])))


if __name__ == "__main__":
    unittest.main()
