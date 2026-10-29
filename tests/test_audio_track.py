import subprocess
import tempfile
import unittest
from pathlib import Path

from clipthat_editor.audio_track import game_track


def _clip(path: Path, tracks: list[str]) -> None:
    args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=160x90:r=15:d=2"]
    for t in tracks:
        args += ["-f", "lavfi", "-i", t]
    args += ["-map", "0:v"] + sum([["-map", f"{i + 1}:a"] for i in range(len(tracks))], [])
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)]
    subprocess.run(args, check=True)


class GameTrackTests(unittest.TestCase):
    def test_single_track_is_the_game(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "one.mp4"
            _clip(p, ["sine=frequency=440:duration=2"])
            self.assertEqual(game_track(p), 0)

    def test_medal_multitrack_uses_the_game_only_track(self):
        # Medal: track 1 = everything mixed, track 2 = game alone, then voice/mic.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "medal.mp4"
            _clip(p, ["sine=frequency=440:duration=2", "sine=frequency=330:duration=2",
                      "sine=frequency=220:duration=2"])
            self.assertEqual(game_track(p), 1)

    def test_silent_second_track_falls_back_to_the_first(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "silent2.mp4"
            _clip(p, ["sine=frequency=440:duration=2", "anullsrc=r=48000:cl=stereo:d=2"])
            self.assertEqual(game_track(p), 0)


if __name__ == "__main__":
    unittest.main()
