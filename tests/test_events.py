"""Valorant kill detection from the kill feed's teal rows."""
import unittest

from clipthat_editor.events import FEED_FPS, FEED_LAG, feed_rows, feed_steps


def series(levels):
    """[(seconds, value)] held until the next change, at FEED_FPS."""
    out = []
    for (t0, v), (t1, _) in zip(levels, levels[1:] + [(levels[-1][0] + 1.0, 0)]):
        out += [v] * int(round((t1 - t0) * FEED_FPS))
    return out


class FeedTests(unittest.TestCase):
    def test_each_new_row_is_a_kill(self):
        teal = series([(0, 0), (2.2, 110), (5.7, 230), (7.9, 340), (12.0, 340)])
        kills = feed_steps(teal)
        self.assertEqual([round(k + FEED_LAG, 2) for k in kills], [2.2, 5.7, 7.9])

    def test_a_passing_teal_flash_is_not_a_kill(self):
        teal = series([(0, 100), (3.0, 700), (3.2, 100), (6.0, 100)])
        self.assertEqual(feed_steps(teal), [])

    def test_rows_arriving_together_are_one_kill(self):
        # A collateral: two rows 0.2 s apart from one shot.
        teal = series([(0, 200), (4.0, 330), (4.2, 450), (7.0, 450)])
        self.assertEqual(len(feed_steps(teal)), 1)

    def test_small_shuffles_are_ignored(self):
        teal = series([(0, 440), (3.0, 500), (5.0, 500)])
        self.assertEqual(feed_steps(teal), [])


if __name__ == "__main__":
    unittest.main()


class KillCountTests(unittest.TestCase):
    def test_collateral_is_one_moment_but_two_kills(self):
        hold = int(0.4 * FEED_FPS)
        # One row, then later two rows 0.15 s apart (a collateral): two moments, three kills.
        teal = [0] * 20 + [150] * 40 + [300] * 3 + [450] * 40
        self.assertEqual(len(feed_steps(teal)), 2)
        self.assertEqual(feed_rows(teal), 3)


class OwnKillTests(unittest.TestCase):
    def test_banners_pick_your_rows_out_of_everyones(self):
        from clipthat_editor.events import own_kills
        # Feed-row onsets measured on a real swiftplay ace (everyone's kills, plus a smoke exit
        # at 8.85), and the player's kill banners. Verified kill frames: 9.30, 12.43, 20.57,
        # 34.77, 50.20 (one 20 fps sample of tolerance).
        onsets = [2.1, 8.85, 9.3, 12.25, 12.55, 13.05, 13.45, 16.4, 19.95, 20.55, 34.75, 38.7, 46.95, 50.2]
        banners = [9.4, 12.6, 20.3, 34.8, 50.7]
        got = own_kills(onsets, banners)
        for g, truth in zip(got, [9.30, 12.43, 20.57, 34.77, 50.20]):
            self.assertAlmostEqual(g, truth, delta=0.13)
        self.assertEqual(len(got), 5)

    def test_without_banners_every_row_counts(self):
        from clipthat_editor.events import own_kills
        self.assertEqual(own_kills([1.0, 2.0], []), [1.0, 2.0])
