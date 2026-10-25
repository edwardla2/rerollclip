"""Sound list and automatic sound choice."""
from pathlib import Path
import tempfile
import unittest

from clipthat_editor import sounds


def entry(title, bpm, drop, duration=20.0, games=()):
    return {"id": title.lower(), "title": title, "artist": "test", "tiktok_url": "", "bpm": bpm,
            "first_beat": 0.0, "drop": drop, "duration": duration, "games": list(games)}


KILLS = [2.55, 5.85, 7.95, 10.95]


class PickTests(unittest.TestCase):
    def test_prefers_a_sound_that_fits(self):
        late = entry("Drop too late", 128, 19.2)     # sound ends before the kills after the drop
        good = entry("Good fit", 128, 7.5)
        choice = sounds.pick(KILLS, 16.6, sounds=[late, good])
        self.assertEqual(choice["sound"]["title"], "Good fit")
        self.assertEqual(choice["plan"]["mode"], "drop")

    def test_drop_mode_prefers_starting_the_sound_at_zero(self):
        # Drop 2 s in: the lead-in fits, so the sound starts at 0:00 in TikTok.
        early, later = entry("Early drop", 128, 2.0), entry("Later drop", 128, 9.0)
        choice = sounds.pick(KILLS, 16.6, sounds=[later, early])
        self.assertEqual(choice["sound"]["title"], "Early drop")
        self.assertEqual(choice["plan"]["sound_start"], 0.0)

    def test_game_tag_breaks_ties(self):
        a, b = entry("Generic", 128, 7.5), entry("Valorant pick", 128, 7.5, games=["valorant"])
        self.assertEqual(sounds.pick(KILLS, 16.6, game="valorant", sounds=[a, b])["sound"]["title"], "Valorant pick")

    def test_empty_list(self):
        self.assertIsNone(sounds.pick(KILLS, 16.6, sounds=[]))

    def test_rhythm_rebuilds_the_grid(self):
        r = sounds.rhythm(entry("x", 120, 4.0, duration=10))
        self.assertEqual(r["beats"][:3], [0.0, 0.5, 1.0])
        self.assertEqual(r["drop"], 4.0)

    def test_list_round_trip_keeps_no_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sounds.json"
            sounds.save([entry("A", 128, 7.5)], path)
            loaded = sounds.load(path)
            self.assertEqual(loaded[0]["title"], "A")
            self.assertNotIn("audio", Path(path).read_text())


if __name__ == "__main__":
    unittest.main()
