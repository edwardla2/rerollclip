#!/usr/bin/env bash
# One-time setup for the Clip That desktop app on macOS.
#   1. installs ffmpeg / python / xcodegen with Homebrew if missing
#   2. runs the editor's own tests and the desktop core tests
#   3. generates ClipThat.xcodeproj
# Usage:  desktop/scripts/bootstrap.sh
set -euo pipefail

DESKTOP="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$DESKTOP/.." && pwd)"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required: https://brew.sh" >&2
  exit 1
fi

for pkg in ffmpeg python; do
  if ! brew list --formula "$pkg" >/dev/null 2>&1; then
    say "Installing $pkg"
    brew install "$pkg"
  fi
done

XCODEGEN="$(command -v xcodegen || true)"
if [ -z "$XCODEGEN" ] && [ -x "$HOME/development/xcodegen-dist/xcodegen/bin/xcodegen" ]; then
  XCODEGEN="$HOME/development/xcodegen-dist/xcodegen/bin/xcodegen"
fi
if [ -z "$XCODEGEN" ]; then
  say "Installing xcodegen"
  brew install xcodegen
  XCODEGEN="$(command -v xcodegen)"
fi

say "Editor tests (ChatGPT's renderer, unmodified)"
(cd "$REPO" && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests)

say "Desktop core tests (manifest, buffer, voice matching, end-to-end render)"
(cd "$DESKTOP/Core" && swift test)

say "Generating ClipThat.xcodeproj"
(cd "$DESKTOP" && "$XCODEGEN" generate)

cat <<EOF

Done. Next:
  open "$DESKTOP/ClipThat.xcodeproj"
  then press ⌘R in Xcode (scheme: ClipThat, destination: My Mac).

Sample clips for a first render:  $DESKTOP/scripts/make_test_clips.sh
EOF
