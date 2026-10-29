# Creative layer: plan

Written 2026-10-28, after v007 and the first Windows app build. Nothing here is built yet.

**Philosophy.** Reroll makes the editorial decisions. The player picks the creative direction.
One click stays the default. Effects improve a good edit. They never make up for bad pacing
or bad clip choice.

## 1. What already exists

The engine is already split into the layers this needs:

```
clips ─► events.py ─► library.py ─► director.py ─► Timeline ─► compositor.py ─► MP4
         (what           (which         (the edit as      (data)     (draws it; makes
          happened)       plays)         decisions)                   no decisions)
```

| Part | What it does now | Role in the layered engine |
|---|---|---|
| `events.py` | Finds your kills, the ACE, teammates' kills (the story), and action from game audio. Checked frame by frame on real clips. | **Moment detection.** Used as is. |
| `library.py` | Analyses each clip once, scores plays, drops duplicates, picks recent plays within a length budget. | **Clip selection.** Used as is. |
| `director.story_compilation` | Builds the edit: play windows, real speed during action, dead time sped through or cut, best play last, optional cuts on the beat. | **The editorial layer.** It becomes the "Clean" style. Nothing about it changes. |
| `timeline.py` | Holds the edit as data: speed changes over time, keyframed zoom, rotation, pan and shake, master effects (colour split, glow, flash, radial blur, edge glow, exposure, black-and-white), text, sound effects, colour grade. | **The shared format.** Every effect Velocity and Cinematic need can already be written into it. |
| `compositor.py` | Draws any Timeline frame-accurately. Smooth in-between frames only where footage plays slowed. Effects run only when used. | **The renderer.** Used as is. |
| `director.velocity_montage`, `gameplay_first` | Older single-clip stylized planners. They hold the effect choices: punch-in, speed into the kill, snap to slow motion, hang on the final kill, whip out with radial blur, ACE slam. `rank_events` scores each kill. `recipes_for` gives each kill a treatment with no two neighbours the same. | **The effect library to reuse.** The choices are good, but they're tied to one clip and to always being on. They get pulled out into separate effect "recipes". |
| `taste/default.json` | Intensity tiers (restrained, medium, aggressive), recipe rotation, the top-event recipe, a cap on black-and-white, protected screen areas (crosshair, kill feed, banners), maximum zoom, and anti-patterns written as sentences. | **The taste profile** that steers every creative choice. Some rules are already machine-readable. The anti-patterns still need to become checks. |
| `sync.py`, `beats.py`, `beatmaker.py` | Reads a song's beats, lines cuts and kills up with them, and writes original beats. | **Music sync option.** Mostly built. Off by default, as now. |
| `study.py`, `evaluate.py`, `review.py`, `renders/vNNN` | Measure reference edits (cut rhythm, how many cuts land on the beat, flashes), plus versioned renders for review. | **Quality checks**, and how every style gets reviewed. |

Most of the creative layer is already written. What's missing is the structure: a clean
editorial pass, then an optional pass that adds style on top.

## 2. The change: two passes

```
plays ─► edit(plays, taste)                ─► Timeline (Clean: cuts, order, speed, pacing)
                      │
                      ▼
         style(timeline, moments, direction, taste) ─► Timeline (+ accents, grade, ramps)
                      │
                      ▼
         check(timeline, taste)    ─► fix or remove any accent that breaks a rule ─► render
```

- **`edit` is `story_compilation` with no changes.** Clean is `edit` plus a style pass that does nothing.
  A test pins this: Clean's timeline must stay the same as today's.
- **The style pass only adds things.** It writes keyframes, grade and sound effects onto the existing
  Timeline. It may change speed only inside a play that's already kept (a short slow-motion moment,
  or a ramp out of a kill), and it gives back the same amount of footage. It never adds, removes or
  reorders plays. So the editing decisions stay the base engine's.
- **The check pass enforces the taste profile.** Each anti-pattern becomes a rule the engine can check:
  - no zoom that pushes the kill feed or crosshair off screen
  - no more than N accents per 10 seconds
  - no two neighbouring accents alike
  - black-and-white at most once
  - no effect covering the final kill

  An accent that breaks a rule is toned down or removed, and the reason goes in the edit notes, as notes do today.

## 3. What's new

1. **Moments.** Each kill gets a record built from what `events.py` already finds:
   - how important it is (`rank_events`, plus ACE, multi-kill bursts, the last kill of a play,
     the best play's final kill)
   - how much is happening on screen (`measure_motion`)
   - how loud and dense the action is
   - how much room there is before and after it

   Effects are chosen per moment, not per video. That's how Velocity puts a speed ramp on one
   video's opener and none on another's.
2. **Recipes.** Small functions pulled out of `gameplay_first` and `velocity_montage`: punch,
   ramp-in, snap to slow motion, hang, whip transition, ACE slam, grade. Each takes a moment
   and returns keyframes. Each declares:
   - what it needs (room before and after, how important the moment must be)
   - how much it costs toward the accent budget
3. **Directions.** A direction is data, an extra block in the taste profile, not code. It sets:
   - which recipes are allowed
   - which recipe goes on the top moment
   - the accent budget per minute
   - the grade
   - whether slow motion is allowed

   Intensity scales the budget and strength, as the tiers do now.

   | | Clean | Velocity | Cinematic |
   |---|---|---|---|
   | Accents | None | Punch, ramps, zoom-throughs at the strongest moments | Slow motion and hang at the top moments only |
   | Speed | Unchanged | Ramps into and out of top kills | Selective slow motion |
   | Grade | None (game colours) | None, or slight | Graded |
   | Transitions | Hard cuts | Whips at play changes | Fades or holds at play changes |

4. **Checks** from the taste profile's anti-patterns (above), with tests.
5. **Options, at most four:** Direction (Clean, Velocity, Cinematic), Intensity (low, medium,
   high), Music sync (off or on), Best play last (on or off). They're sent to the engine as
   flags, and in the app they sit behind "Style" under Make my video. The default stays one click.

## 4. Order

Each step ends with a render in `renders/vNNN` for you to review, as now.

1. **Split without changing anything.** Add the style pass as a no-op and the `--direction`
   flag, and pin Clean to today's output with a test. Nothing visible changes. *(Small.)*
2. **Moments.** Build kill records from existing detection, with tests on the verified clips. *(Small.)*
3. **Recipes, Velocity first.** Pull punch, ramp, snap, hang and whip out of the old planners,
   then add the Velocity direction. Review on the v007 clips. *(Medium. Most of the review loop goes here.)*
4. **Checks.** Turn the anti-patterns into rules, built alongside step 3 so Velocity is limited from the first render. *(Small to medium.)*
5. **Options in the app.** Style picker and intensity. *(Small.)*
6. **Cinematic.** Grade, selective slow motion, transitions at play changes. *(Medium.)*
7. **Music sync as an option.** Reuses `sync`, `beats` and `beatmaker`. *(Small to medium.)*

Not doing yet: text and captions (the taste profile says off), per-game recipes beyond Valorant,
or any timeline controls. Render time matters more as effects are added: slow-motion
in-between frames are the slowest part. Speed work should land before Velocity or Cinematic ship.
