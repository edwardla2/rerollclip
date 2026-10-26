# Reference edit breakdown: "velocity montage" (Valorant, 61 s, 16:9)

Measured with `python -m clipthat_editor study` plus frame-by-frame inspection (4 fps sheets of
the whole edit, full 30 fps on the key moments). Song: 80 BPM (beat 0.750 s, bar 3.0 s), drop at
8.68 s. Note: the download's audio is HE-AAC v2, which this FFmpeg decodes at half rate
(30.7 s of samples for 61 s); `montage.decoded_audio` detects and corrects that, and every
musical number below uses the corrected track.

## Structure

| Time | Section | What happens | Cuts per bar |
|---|---|---|---|
| 0.00–0.55 | Open | Luma reveal out of black: the brightest parts (a red knife) appear first | – |
| 0.55–9.2 | Intro (bars 0–2) | One continuous walk-up shot at real speed, slow camera drift. Lyric words in glossy chrome-red 3D letters, one word every 0.25–0.5 s, letters arriving one by one, placed in the scene behind the arm | 0–1 |
| 8.75–9.37 | Anticipation | Last word ("CARS") holds and strobes out over ~0.3 s; camera accelerates | – |
| 9.37 | Transition | One frame of heavy directional/radial blur (whip), hard cut, strong RGB split for ~4 frames | – |
| 9.4–12.4 | Kill 1 | Purple ink glow creeps in from the edges; kill at ~10.9 lands in slow motion (~0.4x); the camera rolls ~6° and keeps pushing while it hangs | 1 |
| 12.6–27 | Energy (bars 4–8) | Montage of many clips: cut on most half beats (~0.4 s), 1-frame whip blur at each cut, constant RGB fringe, bloom, white words ("DAMN", "IN") | 7–15 |
| 21.0–24.7 | Peak | Cuts every quarter beat (~0.2 s): 1 blurred frame, 2 sharp frames, repeat | 15 |
| 27–30 | Calm hold | "CLUTCH" banner, big purple "BAND" word, no cuts for a bar | 0 |
| 31–43 | Medium | 2–4 cuts per bar, flashes on big hits | 2–6 |
| 43.8–48 | Second peak | Quarter-beat cuts again, "MAN" word | 12 |
| 48–58 | Wind-down | Longer shots, last kill with purple edge glow at 56.5 | 1–4 |
| 58–61.4 | Close | Luma fade: everything sinks to black except the brightest pixels, then black | – |

Measured: 85 detected cuts over 61 s (1.4/s), median shot 0.33 s. 41 of 85 cuts fall within 50 ms
of the quarter-beat grid (13 of 85 on half beats, 7 on whole beats): cuts follow the song's
subdivisions in the energetic sections, not one cut per beat.

## Techniques and why they read as professional

1. **Contrast in pacing.** A slow, readable intro and calm holds make the dense sections hit
   harder. Effects are attached to musical events (drop, accents) and gameplay (kills), never
   spread evenly.
2. **Speed ramps that go somewhere.** Footage accelerates into a moment and snaps to slow motion
   on the impact; ramps out are fast enough to need blur, so the whip *is* the transition.
3. **Coordinated impacts.** On a kill, several things happen on the same frame: exposure flash,
   RGB split spike, punch-in, shake, bloom. They decay at different rates (flash ~0.1 s, split
   ~0.3 s, push and roll over the hang), so the hit feels like one physical event.
4. **Continuous camera.** The virtual camera keeps moving through a shot (push, roll), and the
   transition carries that motion into the next shot (zoom-through with radial blur).
5. **Typography as part of the scene.** Big extruded letters, lit and glowing, entering letter
   by letter and leaving with a strobe; placed in depth (the viewmodel arm in front of them).
6. **Finish.** Strong saturation and contrast, bloom on highlights, a permanent slight colour
   fringe in the energetic parts, luma reveals at the start and end.

## How Reroll maps this onto one clip (director.velocity_montage)

The reference is a multi-clip montage; a single ace clip has five moments, so the language is
adapted rather than copied:

* Intro: the clip's own walk-up before kill 1, real speed, slow push and sway, title words in
  chrome red on the beat, luma reveal in. Anticipation on the last beat (split, bloom, push).
* Kill 1 on the drop, with the full impact package and the purple edge glow, then a long ramp.
* Kills 2–3 on two-beat spacing; the build to the final kill gets a bar with rising split and bloom.
* Final kill on a downbeat with the longest slow motion, edge glow, then a calm hold with a white
  kill word (the reference's "CLUTCH" hold).
* A replay flurry on half beats with quarter-beat glitch pulses (the reference's peak sections,
  built from the clip's own kills), then the aftermath and a luma fade out.
