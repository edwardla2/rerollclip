# Renders for external review

One folder per iteration, never overwritten: `vNNN/` holds `edit.mp4` (the postable export, no
music), `preview.mp4` (with the sound, for judging sync), `timeline.json` (every cut, speed key and
effect keyframe), `taste.json` (the editorial parameters), `summary.md` (shots, effect values and
the changes made) and `sheet.png` (frames at every kill and cut).

Videos are kept out of git (size); everything else is committed. Made with
`python -m clipthat_editor release <render.mp4> --changes "..."`.
