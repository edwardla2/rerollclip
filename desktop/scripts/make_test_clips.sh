#!/usr/bin/env bash
# Generates three synthetic "gameplay" clips (moving test pattern + tone; one has no
# audio) for trying import → render without real footage. No copyrighted material.
#
# Usage:  make_test_clips.sh [output-folder]      (default: ~/Movies/Clip That Test Clips)
# Tip: add the output folder as a watched folder, then run this again to watch
#      new files auto-import, like a recorder exporting a clip.
set -euo pipefail

OUT="${1:-$HOME/Movies/Clip That Test Clips}"
mkdir -p "$OUT"
STAMP="$(date +%Y-%m-%d\ %H-%M-%S)"

make_clip() {
  local name="$1" pattern="$2" tone="$3"
  if [ -n "$tone" ]; then
    ffmpeg -hide_banner -loglevel error -y \
      -f lavfi -t 12 -i "${pattern}=s=1920x1080:r=60" \
      -f lavfi -i "sine=frequency=${tone}:sample_rate=48000:duration=12" \
      -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -b:a 160k -shortest \
      "$OUT/$name $STAMP.mp4"
  else
    ffmpeg -hide_banner -loglevel error -y \
      -f lavfi -t 12 -i "${pattern}=s=1920x1080:r=60" \
      -c:v libx264 -preset veryfast -pix_fmt yuv420p \
      "$OUT/$name $STAMP.mp4"
  fi
}

make_clip "Replay A" testsrc2 440
make_clip "Replay B" rgbtestsrc ""
make_clip "Replay C" testsrc 660

echo "Wrote 3 clips to: $OUT"
