# Reroll render v007

- Length: 101.15 s, 1080x1920 @ 60 fps
- Measured: {'streams': 'stream|width=1080|height=1920|r_frame_rate=60/1; stream|r_frame_rate=0/0; format|duration=101.167000', 'loudness_lufs': '-14.0', 'true_peak_dbfs': '-1.9'}
- Song (preview only): -, None BPM, starts at 0.0 s of the sound; no drop used (candidate None s, n/a)
- Speed: real speed except play 1 skim 1 (4.45-6.20 s) 1.10x-3.30x; play 1 skim 2 (7.70-9.82 s) 1.10x-3.30x; play 1 skim 3 (12.78-14.18 s) 1.10x-3.30x; play 2 skim 1 (24.82-26.93 s) 1.10x-3.30x; play 2 skim 3 (39.38-41.60 s) 1.10x-3.30x; play 2 skim 5 (50.15-52.23 s) 1.10x-3.30x; play 3 skim 1 (76.38-77.20 s) 1.10x-3.30x; play 4 skim 1 (86.55-87.60 s) 1.10x-3.30x; play 4 skim 2 (91.75-93.80 s) 1.10x-3.30x
- Taste: mode story, intensity medium

## Changes in this version

- First compilation from Edward's own Medal clips (720p HEVC, multi-track)
- Kill detection ignores gun models and the scoreboard in the banner spot (long Operator clip: 3 real kills instead of 7)
- Game-only audio track (Medal track 2), so no voice chat in the export

## Shots

| # | Output | Source | Clip | Speeds | Framing |
|---|---|---|---|---|---|
| 1 | 0.00-4.45 | 0.00-4.45 | m2.mov | [1.0] | full |
| 2 | 4.45-6.20 | 4.45-7.95 | m2.mov | [1.1, 1.58, 2.29, 3.3] | full |
| 3 | 6.20-7.70 | 7.95-9.45 | m2.mov | [1.0] | full |
| 4 | 7.70-9.82 | 9.45-13.70 | m2.mov | [1.1, 1.58, 2.29, 3.3] | full |
| 5 | 9.82-12.77 | 13.70-16.65 | m2.mov | [1.0] | full |
| 6 | 12.78-14.18 | 16.65-19.45 | m2.mov | [1.1, 1.58, 2.29, 3.3] | full |
| 7 | 14.18-20.83 | 19.45-26.10 | m2.mov | [1.0] | full |
| 8 | 20.82-24.82 | 9.40-13.40 | m1.mov | [1.0] | full |
| 9 | 24.82-26.93 | 13.40-17.60 | m1.mov | [1.1, 1.58, 2.29, 3.3] | full |
| 10 | 26.93-36.33 | 17.60-27.00 | m1.mov | [1.0] | full |
| 11 | 36.33-39.38 | 34.40-37.45 | m1.mov | [1.0] | full |
| 12 | 39.38-41.60 | 37.45-41.90 | m1.mov | [1.1, 1.58, 2.29, 3.3] | full |
| 13 | 41.60-45.50 | 41.90-45.80 | m1.mov | [1.0] | full |
| 14 | 45.50-50.15 | 52.80-57.45 | m1.mov | [1.0] | full |
| 15 | 50.15-52.23 | 57.45-61.60 | m1.mov | [1.1, 1.58, 2.29, 3.3] | full |
| 16 | 52.23-59.23 | 61.60-68.60 | m1.mov | [1.0] | full |
| 17 | 59.23-76.38 | 17.30-34.45 | m4.mov | [1.0] | full |
| 18 | 76.38-77.20 | 34.45-36.10 | m4.mov | [1.1, 1.58, 2.29, 3.3] | full |
| 19 | 77.20-81.20 | 36.10-40.10 | m4.mov | [1.0] | full |
| 20 | 81.20-86.55 | 10.65-16.00 | m3.mov | [1.0] | full |
| 21 | 86.55-87.60 | 16.00-18.10 | m3.mov | [1.1, 1.58, 2.29, 3.3] | full |
| 22 | 87.60-91.75 | 18.10-22.25 | m3.mov | [1.0] | full |
| 23 | 91.75-93.80 | 22.25-26.35 | m3.mov | [1.1, 1.58, 2.29, 3.3] | full |
| 24 | 93.80-101.15 | 26.35-33.70 | m3.mov | [1.0] | full |

## Effects (master keyframes, output time)


## Planner notes

- play 1: m2.mov, 3 kills, framing full
- play 2: m1.mov, 3 kills, framing full
- play 2: cut 7.4s of dead time at 36.325s
- play 2: cut 7.0s of dead time at 45.500s
- play 3: m4.mov, 4 kills, framing full
- play 4: m3.mov, 4 kills, framing full

Kills land at (output s): [1.65, 11.425, 18.425, 23.825, 53.125, 56.825, 62.225, 66.425, 73.725, 78.8, 84.7, 90.75, 97.0, 98.75]
