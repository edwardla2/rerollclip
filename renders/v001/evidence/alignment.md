# v001 music alignment (Legacy)

Tempo 70.3 BPM (beat 0.853 s), grid starts at 0.44 s. Song starts at output 0.
Drop candidate at 14.091 s with strength 0.065: low confidence, not used.
Detected onsets: 33.

| What | Output s | Song s | Nearest beat (#) | Offset | Nearest onset | Onset offset | Intended |
|---|---|---|---|---|---|---|---|
| kill | 0.6 | 0.6 | 0.44 (#0) | +160 ms | 0.662 | -62 ms | game-timed (kills are not moved onto beats in story mode) |
| kill | 3.8 | 3.8 | 3.853 (#4) | -53 ms | 4.075 | -275 ms | game-timed (kills are not moved onto beats in story mode) |
| cut | 5.559 | 5.559 | 5.559 (#6) | +0 ms | 5.573 | -14 ms | on the beat |
| kill | 6.259 | 6.259 | 6.412 (#7) | -153 ms | 6.838 | -579 ms | game-timed (kills are not moved onto beats in story mode) |
| cut | 7.266 | 7.266 | 7.266 (#8) | +0 ms | 7.477 | -211 ms | on the beat |
| kill | 8.866 | 8.866 | 8.972 (#10) | -106 ms | 8.975 | -109 ms | game-timed (kills are not moved onto beats in story mode) |
| cut | 10.679 | 10.679 | 10.679 (#12) | +0 ms | 10.89 | -211 ms | on the beat |
| kill | 14.779 | 14.779 | 14.945 (#17) | -166 ms | 14.454 | +325 ms | game-timed (kills are not moved onto beats in story mode) |
| accent start (mono on) | 14.829 | 14.829 | 14.945 (#17) | -116 ms | 15.151 | -322 ms | accent tied to the final kill |
| colour back | 15.429 | 15.429 | 15.798 (#18) | -369 ms | 15.151 | +278 ms | accent tied to the final kill |
| end | 16.78 | 16.78 | 16.651 (#19) | +129 ms | 16.637 | +143 ms | end of the sound (16.78 s) |

## Reading this

- Cuts were placed on the detected beat grid (0 ms offsets above are by construction, not a measurement of audible sync).
- Two of the three cuts fall 211 ms before the nearest strong onset (7.477 s, 10.890 s). If they sound early on playback,
  the likely cause is the grid's phase on this track, not the cut placement. To be confirmed by listening to preview.mp4.
- Kills are game-timed in story mode (not moved onto beats). The black-and-white accent follows the final kill, so it is
  not beat-aligned either: colour returns 369 ms before beat #18.
