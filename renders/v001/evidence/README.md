# v001 review evidence (for feedback/v001.md)

The rendered video is unchanged; everything here is measured from `../edit.mp4` and `../preview.mp4`.

| Request | Evidence | Finding |
|---|---|---|
| P0 media | `../preview.mp4`, `../edit.mp4`, `../sheet.png`, `requested-frames.png`, `frames/` (full 1080x1920 frames at 0.6, 3.8, 5.559, 6.259, 7.266, 8.866, 10.679, 14.779, 14.829, 15.429, 15.729 s) | Sent for direct review |
| P1 metadata | `../summary.md` (corrections section), `../timeline.json` (`music.title`, `source_asset`, `decoded_path`, `drop_candidate_s`, `drop_confidence`) | "No speed ramps" corrected; drop is a low-confidence candidate (0.065), unused; track identity separated from the decoded path |
| P1 30 to 60 fps | `motion-cadence.txt`, `motion-unique-fps.txt`, `motion-compare-half-speed.mp4` | Real-speed windows are 30 fps doubled (50% repeated frames, even cadence); the slow-motion accent is synthesized (0% repeats). Interpolating real-speed combat tears fast camera flicks (see the side-by-side at 1.3 s), so v001's choice is kept unless review says otherwise. Exporting 30 fps would look the same for real-speed parts. |
| P1 framing / branding | `frames/`, `watermark-and-hud-1to1.png` | Watermark clears the ability bar and ammo counter at 1:1. The 9:16 crop is a 608 px slice upscaled 1.78x: visibly soft at 1:1. Kill 4 (8.866 s): the enemy is small and near the right edge of the crop. Kill 2 (3.8 s): feed rows sit just above the enemy. |
| P2 pacing / accent | `requested-frames.png`, `frames/t14.779s.png` to `t15.729s.png` | For the reviewer's playback judgement; no change proposed yet |
| P2 music alignment | `beats.json` (grid, onsets, drop candidate, per-event offsets), `alignment.md` | Cuts sit on the detected grid by construction; two of three are 211 ms before the nearest strong onset, a possible grid-phase error to confirm by ear. Kills and the accent are game-timed, not beat-aligned. |
