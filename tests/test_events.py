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
