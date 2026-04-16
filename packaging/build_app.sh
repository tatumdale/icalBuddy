#!/usr/bin/env bash
#
# Build CalendarSync.app
#
# Usage:  ./packaging/build_app.sh
# Output: calendar-sync/dist/CalendarSync.app
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CALSYNC_DIR="$REPO_ROOT/calendar-sync"

echo "==> Step 1/4: Compile icalBuddy binary"
# Try to compile from source; skip gracefully if SDK is missing
ICALBUDDY_BIN=""
if command -v clang >/dev/null 2>&1; then
  if make -C "$REPO_ROOT" icalBuddy 2>/dev/null; then
    ICALBUDDY_BIN="$REPO_ROOT/icalBuddy"
    echo "    Compiled icalBuddy from source."
  else
    echo "    WARNING: icalBuddy compilation failed (CalendarStore SDK may be missing)."
    echo "    Will try to use Homebrew-installed binary as fallback."
  fi
fi

# Fallback: use Homebrew-installed icalBuddy
if [[ -z "$ICALBUDDY_BIN" ]]; then
  for candidate in /opt/homebrew/bin/icalBuddy /usr/local/bin/icalBuddy; do
    if [[ -x "$candidate" ]]; then
      ICALBUDDY_BIN="$candidate"
      echo "    Using Homebrew icalBuddy: $ICALBUDDY_BIN"
      break
    fi
  done
fi

if [[ -z "$ICALBUDDY_BIN" ]]; then
  echo "ERROR: Could not find or build icalBuddy. Install via: brew install ical-buddy"
  exit 1
fi

echo "==> Step 2/4: Set up Python venv + dependencies"
VENV_DIR="$CALSYNC_DIR/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$CALSYNC_DIR/requirements.txt"
"$VENV_DIR/bin/pip" install --quiet py2app

echo "==> Step 3/4: Build .app via py2app"
# Clean previous builds
rm -rf "$CALSYNC_DIR/build" "$CALSYNC_DIR/dist"

(cd "$CALSYNC_DIR" && "$VENV_DIR/bin/python" setup.py py2app)

APP_PATH="$CALSYNC_DIR/dist/CalendarSync.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "ERROR: py2app did not produce CalendarSync.app"
  exit 1
fi

echo "==> Step 4/4: Embed icalBuddy binary into .app bundle"
RESOURCES="$APP_PATH/Contents/Resources"
cp "$ICALBUDDY_BIN" "$RESOURCES/icalBuddy"
chmod +x "$RESOURCES/icalBuddy"

echo ""
echo "Build complete: $APP_PATH"
echo ""
echo "To sign (optional):  codesign --force --deep --sign - --entitlements packaging/entitlements.plist \"$APP_PATH\""
