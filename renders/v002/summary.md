# Reroll render v002

- Length: 16.78 s, 1080x1920 @ 60 fps
- Measured: {'streams': 'stream|width=1080|height=1920|r_frame_rate=60/1; stream|r_frame_rate=0/0; format|duration=16.790000', 'loudness_lufs': '-14.3', 'true_peak_dbfs': '-0.8'}
- Song (preview only): Legacy, 70.3 BPM, starts at 0.0 s of the sound; no drop used (candidate 14.091 s, low; not used)
- Speed: real speed except play 1 window 4 (10.68-16.78 s) 0.40x-1.00x
- Taste: mode story, intensity medium

## Changes in this version

- From review v001 (Edward): 'looks squished' -> the whole game screen, full width, centred, with a blurred, darkened copy filling above and below (option 2 he picked)
- From review v001 (Edward): 'colour too saturated / fake' -> no colour grading; measured against the source clip: within 2/255 per channel (format conversion only)
- Kill-feed inset removed (the whole frame shows the game's own kill feed)
- Unchanged on purpose: cuts, timing, song (Legacy), black-and-white accent on the final kill, watermark

## Shots

| # | Output | Source | Clip | Speeds | Framing |
|---|---|---|---|---|---|
| 1 | 0.00-5.56 | 8.70-14.26 | clip.mp4 | [1.0] | full |
| 2 | 5.56-7.27 | 19.85-21.56 | clip.mp4 | [1.0] | full |
| 3 | 7.27-10.68 | 33.15-36.56 | clip.mp4 | [1.0] | full |
| 4 | 10.68-16.78 | 46.10-51.70 | clip.mp4 | [0.4, 0.42, 0.44, 0.66, 1.0] | full |

## Effects (master keyframes, output time)

- flash: [(14.78, 0.1)]
- mono: [(14.83, 1.0), (15.43, 1.0)]

## Planner notes

- play 1: clip.mp4, 5 kills, framing full
- play 1: cut 5.6s of dead time at 5.559s
- play 1: cut 11.6s of dead time at 7.266s
- play 1: cut 9.5s of dead time at 10.679s
- accent: final kill of play 1 at 14.779s
- trimmed 0.61s off the end to finish with the song

Kills land at (output s): [0.6, 3.8, 6.259, 8.866, 14.779]

## Colour check (v002 vs source, gameplay area, same frames)

| Output | Source | Mean RGB source | Mean RGB v002 | Abs diff |
|---|---|---|---|---|
| 0.6 s | 9.3 s | 84.1 81.7 91.4 | 82.9 79.8 90.3 | 2.11 |
| 3.8 s | 12.5 s | 125.4 105.7 87.1 | 124.2 103.7 85.9 | 2.15 |
| 8.866 s | 34.75 s | 96.3 79.6 63.3 | 95.0 77.4 62.0 | 2.31 |
