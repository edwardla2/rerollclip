# Clip That starter — editing engine + Claude handoff

This kit contains a working **v0 deterministic** video-editing CLI and a collaboration contract for the desktop client. It is **not** a full AI montage engine and does not capture or transcribe voice itself.

## Run the editor
Prerequisites: Python 3.10+ and `ffmpeg` / `ffprobe` on PATH.

From this directory:

```bash
python -m clipthat_editor validate examples/manifest.example.json
python -m clipthat_editor render /path/to/session/manifest.json --output /path/to/session/output.mp4
```

The sample manifest references placeholder clip files, so create a real session manifest with actual MP4 files before rendering.

For a real example, copy `examples/manifest.example.json` beside your clips, change each `file` to a real relative path, and run `render`. Video output is portrait 1080×1920 at 30 fps by default.

## Current rendering behavior
- Trims selected moments, normalizes resolution/fps/audio, concatenates clips.
- Two vertical layouts: blurred background preserving complete landscape footage (`fit_blur`), and center crop (`center_crop`).
- Optional locally provided soundtrack mixed at configurable volume. **Use music you have rights to use.**
- Preset names are accepted for app compatibility but do not yet implement ML selection, fancy transitions or automatic beat sync. Those are ChatGPT's planned subsequent features.
- No network calls, account creation, automatic uploads, or background recording.

## File map
- `CLAUDE_HANDOFF.md` — exact brief to paste into Claude Code.
- `OWNERSHIP_AND_ROADMAP.md` — roles, milestones, acceptance gates.
- `examples/manifest.example.json` — desktop-to-editor data contract.
- `clipthat_editor/` — render CLI.
- `tests/` — validation tests.

## Team integration
Claude owns the desktop app. Keep that code in a sibling `desktop/` directory, and generate manifests compatible with this package. Do not duplicate the render core.
