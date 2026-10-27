# Reroll render v001

- Length: 16.78 s, 1080x1920 @ 60 fps
- Measured: {'streams': 'stream|width=1080|height=1920|r_frame_rate=60/1; stream|r_frame_rate=0/0; format|duration=16.790000', 'loudness_lufs': '-14.3', 'true_peak_dbfs': '-0.8'}
- Song (preview only): Legacy (TikTok sound ssstik.io_1793044908730.mp4), 70.3 BPM, starts at 0.0 s of the sound
- Taste: mode story, intensity medium

## Changes in this version

- Baseline for external review: story mode (light editing, the play kept in order at real speed)
- Source: one swiftplay ace (1080p30 clip, 52 s); sound: Legacy (16.8 s TikTok sound, 70 BPM, no drop)
- Three cuts over dead time (5.6 s, 11.6 s, 9.5 s), each on a beat; no speed ramps
- One accent: 0.7 s black-and-white slow motion on the final kill, colour returns as the finisher bursts
- Kill-feed inset (rows only) below the round banners; 'made with reroll' bottom-right
- Known: 16.8 s, over the 10-15 s target, because it fills the whole sound; 9:16 crop upscales a 608-px slice 1.8x

## Shots

| # | Output | Source | Clip | Speeds | Framing |
|---|---|---|---|---|---|
| 1 | 0.00-5.56 | 8.70-14.26 | clip.mp4 | [1.0] | crop + feed |
| 2 | 5.56-7.27 | 19.85-21.56 | clip.mp4 | [1.0] | crop + feed |
| 3 | 7.27-10.68 | 33.15-36.56 | clip.mp4 | [1.0] | crop + feed |
| 4 | 10.68-16.78 | 46.10-51.70 | clip.mp4 | [0.4, 0.42, 0.44, 0.66, 1.0] | crop + feed |

## Effects (master keyframes, output time)

- flash: [(14.78, 0.1)]
- mono: [(14.83, 1.0), (15.43, 1.0)]

## Planner notes

- play 1: clip.mp4, 5 kills, framing crop + kill feed
- play 1: cut 5.6s of dead time at 5.559s
- play 1: cut 11.6s of dead time at 7.266s
- play 1: cut 9.5s of dead time at 10.679s
- accent: final kill of play 1 at 14.779s
- trimmed 0.61s off the end to finish with the song

Kills land at (output s): [0.6, 3.8, 6.259, 8.866, 14.779]
