"""Evaluate the Highlight edit on a folder of real clips.

    python -m clipthat_editor evaluate <clips-dir> <out-dir> [--profile roblox]

For every clip: edit it, record what was decided and how long it took, and keep going on
failure. Writes, into <out-dir>:
- edits/<clip>.reroll.mp4   the edit, next to nothing else so it's easy to share;
- results.json / results.csv  decisions, timings and failures per clip;
- report.html               each original beside its edit with a rating form. Ratings stay
  in the reviewer's browser until they press "Download ratings" (a CSV).
Medal's own helper folders (.thumbnails, Edits, Screenshots, ...) are skipped.
"""
from __future__ import annotations

import csv
import html
import json
import os
from pathlib import Path
import time
from typing import Any

from .highlight import PROFILES, auto_edit

MEDAL_RESERVED = {".thumbnails", "clips_thumbnails", "editor", "edits", "projects", "screenshots"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm"}
RATINGS = ["Definitely not", "Probably not", "Maybe, with changes", "Probably yes", "Definitely yes"]
ISSUES = ["Misses the important moment", "Cuts too early", "Cuts too late", "Crops out something important",
          "Slow motion hurts it", "Hard to follow on a phone", "Audio is off"]


def find_clips(folder: Path) -> list[Path]:
    clips = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d.lower() not in MEDAL_RESERVED and not d.startswith("."))
        for name in sorted(files):
            if Path(name).suffix.lower() in VIDEO_EXT and ".reroll." not in name:
                clips.append(Path(root) / name)
    return clips


def evaluate(clips_dir: Path, out_dir: Path, *, profile: str = "generic", slow_motion: str = "auto",
             size: str = "1080", encoder: str = "auto") -> dict[str, Any]:
    clips_dir, out_dir = Path(clips_dir).resolve(), Path(out_dir).resolve()
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile {profile}")
    edits = out_dir / "edits"
    edits.mkdir(parents=True, exist_ok=True)
    width, height = (720, 1280) if size == "720" else (1080, 1920)
    rows: list[dict[str, Any]] = []
    began = time.monotonic()
    clips = find_clips(clips_dir)
    for n, clip in enumerate(clips, 1):
        rel = clip.relative_to(clips_dir)
        dest = edits / (str(rel.with_suffix("")).replace(os.sep, "__") + ".reroll.mp4")
        print(f"[{n}/{len(clips)}] {rel}", flush=True)
        row: dict[str, Any] = {"clip": str(rel), "source_path": str(clip)}
        try:
            result = auto_edit(clip, dest, profile=profile, slow_motion=slow_motion, width=width, height=height,
                               encoder=encoder)
            row.update(ok=True, edit=str(dest.relative_to(out_dir)), source_seconds=result["source_seconds"],
                       output_seconds=result["output_seconds"], peak=result["peak"], strength=result["strength"],
                       slow_motion=result["slow_motion"]["applied"], slow_reason=result["slow_motion"]["reason"],
                       cuts=len(result["cuts"]), layout=result["layout"], encoder=result["encoder"],
                       signals="+".join(result["signals"]), **result["timings"])
        except Exception as error:  # keep going; failures are results too
            row.update(ok=False, error=str(error).strip().splitlines()[-1][:300] if str(error).strip() else repr(error))
        rows.append(row)
    summary = {
        "profile": profile, "clips": len(rows), "edited": sum(r["ok"] for r in rows),
        "failed": sum(not r["ok"] for r in rows), "wall_seconds": round(time.monotonic() - began, 1),
    }
    done = [r for r in rows if r["ok"]]
    if done:
        totals = sorted(r["total_s"] for r in done)
        summary["median_total_s"] = totals[len(totals) // 2]
        summary["slowest_total_s"] = totals[-1]
    (out_dir / "results.json").write_text(json.dumps({"summary": summary, "clips": rows}, indent=2), encoding="utf-8")
    fields = ["clip", "ok", "error", "source_seconds", "output_seconds", "peak", "strength", "slow_motion",
              "slow_reason", "cuts", "layout", "encoder", "signals", "analyze_s", "render_s", "total_s", "edit"]
    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    (out_dir / "report.html").write_text(render_report(rows, summary, out_dir), encoding="utf-8")
    return summary


def render_report(rows: list[dict[str, Any]], summary: dict[str, Any], out_dir: Path) -> str:
    esc = html.escape
    cards = []
    for i, r in enumerate(rows):
        source = Path(os.path.relpath(r["source_path"], out_dir)).as_posix()
        if not r["ok"]:
            cards.append(f'<article class="card failed"><h2>{esc(r["clip"])}</h2>'
                         f'<p class="err">Failed: {esc(r["error"])}</p></article>')
            continue
        facts = (f'{r["source_seconds"]:.1f}s → {r["output_seconds"]:.1f}s · peak at {r["peak"]:.1f}s · '
                 f'{r["cuts"]} cut(s) · slow motion: {"yes" if r["slow_motion"] else "no"} ({esc(r["slow_reason"])}) · '
                 f'{esc(r["layout"])} · {esc(r["encoder"])} · {r["total_s"]:.1f}s to edit')
        ratings = "".join(f'<label><input type="radio" name="r{i}" value="{esc(x)}"> {esc(x)}</label>' for x in RATINGS)
        issues = "".join(f'<label><input type="checkbox" name="i{i}" value="{esc(x)}"> {esc(x)}</label>' for x in ISSUES)
        cards.append(f'''<article class="card" data-clip="{esc(r["clip"])}" data-i="{i}">
  <h2>{esc(r["clip"])}</h2><p class="facts">{facts}</p>
  <div class="pair">
    <figure><video src="{esc(source)}" controls preload="metadata"></video><figcaption>Original</figcaption></figure>
    <figure class="tall"><video src="{esc(Path(r["edit"]).as_posix())}" controls preload="metadata"></video><figcaption>Reroll edit</figcaption></figure>
  </div>
  <fieldset><legend>Would you willingly post this edit to your own account?</legend><div class="opts">{ratings}</div></fieldset>
  <fieldset><legend>What's wrong with it? (any that apply)</legend><div class="opts">{issues}</div></fieldset>
  <label class="note">Notes <textarea name="n{i}" rows="2"></textarea></label>
</article>''')
    s = summary
    timing = (f' · median {s["median_total_s"]:.1f}s per clip, slowest {s["slowest_total_s"]:.1f}s'
              if "median_total_s" in s else "")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reroll edit review</title>
<style>
:root {{ --bg:#0d0e11; --panel:#16171c; --raise:#1e2027; --line:rgba(255,255,255,.08); --text:#f3f4f6; --muted:#a3a7b1; --gold:#ffd23f; --bad:#ff8a7a; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.5 ui-sans-serif,-apple-system,"Segoe UI",system-ui,sans-serif; }}
header {{ position:sticky; top:0; z-index:2; background:rgba(13,14,17,.92); backdrop-filter:blur(8px); border-bottom:1px solid var(--line); padding:14px 16px; display:flex; flex-wrap:wrap; gap:12px; align-items:center; }}
header h1 {{ font-size:17px; margin:0; }} header p {{ margin:0; color:var(--muted); flex:1; min-width:240px; }}
button {{ background:var(--gold); color:#1b1503; border:0; border-radius:999px; padding:9px 16px; font-weight:700; cursor:pointer; }}
main {{ max-width:1100px; margin:0 auto; padding:16px; display:grid; gap:16px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:16px; display:grid; gap:12px; }}
.card h2 {{ font-size:15px; margin:0; word-break:break-word; }} .facts {{ margin:0; color:var(--muted); font-size:12.5px; }}
.pair {{ display:grid; grid-template-columns:minmax(0,1.9fr) minmax(0,1fr); gap:12px; align-items:start; }}
figure {{ margin:0; }} video {{ width:100%; background:#000; border-radius:10px; display:block; }}
.tall video {{ aspect-ratio:9/16; max-height:70vh; object-fit:contain; }}
figcaption {{ color:var(--muted); font-size:12px; margin-top:6px; }}
fieldset {{ border:1px solid var(--line); border-radius:12px; padding:10px 12px; margin:0; }}
legend {{ padding:0 6px; font-weight:600; }} .opts {{ display:flex; flex-wrap:wrap; gap:6px 16px; }}
.opts label {{ display:inline-flex; gap:6px; align-items:center; }} input {{ accent-color:var(--gold); }}
.note {{ display:grid; gap:4px; color:var(--muted); }} textarea {{ background:var(--bg); color:var(--text); border:1px solid var(--line); border-radius:10px; padding:8px; font:inherit; }}
.failed {{ border-color:rgba(255,138,122,.4); }} .err {{ color:var(--bad); margin:0; }}
@media (max-width:700px) {{ .pair {{ grid-template-columns:1fr; }} }}
</style></head><body>
<header><h1>Reroll edit review</h1>
<p>Profile <b>{esc(s["profile"])}</b> · {s["edited"]} of {s["clips"]} clips edited, {s["failed"]} failed{timing}</p>
<button type="button" id="download">Download ratings</button></header>
<main>{"".join(cards) or "<p>No clips found.</p>"}</main>
<script>
(() => {{
  const KEY = 'reroll.review.' + location.pathname;
  let saved = {{}};
  try {{ saved = JSON.parse(localStorage.getItem(KEY) || '{{}}') || {{}}; }} catch (_) {{}}
  const cards = [...document.querySelectorAll('.card[data-clip]')];
  const read = (card) => {{
    const i = card.dataset.i;
    return {{
      clip: card.dataset.clip,
      rating: (card.querySelector(`input[name="r${{i}}"]:checked`) || {{}}).value || '',
      issues: [...card.querySelectorAll(`input[name="i${{i}}"]:checked`)].map((x) => x.value).join('; '),
      notes: card.querySelector('textarea').value.trim(),
    }};
  }};
  cards.forEach((card) => {{
    const s = saved[card.dataset.clip];
    if (s) {{
      card.querySelectorAll('input').forEach((x) => {{ x.checked = x.type === 'radio' ? x.value === s.rating : (s.issues || '').split('; ').includes(x.value); }});
      card.querySelector('textarea').value = s.notes || '';
    }}
    card.addEventListener('input', () => {{
      saved[card.dataset.clip] = read(card);
      try {{ localStorage.setItem(KEY, JSON.stringify(saved)); }} catch (_) {{}}
    }});
  }});
  document.getElementById('download').addEventListener('click', () => {{
    const q = (v) => '"' + String(v).replace(/"/g, '""') + '"';
    const lines = ['clip,rating,issues,notes', ...cards.map(read).map((r) => [r.clip, r.rating, r.issues, r.notes].map(q).join(','))];
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([lines.join('\\n')], {{ type: 'text/csv' }}));
    a.download = 'reroll-ratings.csv';
    a.click();
  }});
}})();
</script></body></html>'''
