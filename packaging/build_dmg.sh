#!/usr/bin/env bash
#
# Build CalendarSync.dmg from the .app bundle.
#
# Usage:  ./packaging/build_dmg.sh
# Prereq: run ./packaging/build_app.sh first
#         brew install create-dmg   (or CI installs it)
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_PATH="$REPO_ROOT/calendar-sync/dist/CalendarSync.app"
DMG_DIR="$REPO_ROOT/calendar-sync/dist"
DMG_NAME="CalendarSync.dmg"
DMG_PATH="$DMG_DIR/$DMG_NAME"
VOLUME_NAME="CalendarSync"
ICON_FILE="$REPO_ROOT/calendar-sync/resources/CalendarSync.icns"
EULA_FILE="$REPO_ROOT/packaging/LICENSE_EULA.txt"

if [[ ! -d "$APP_PATH" ]]; then
  echo "ERROR: CalendarSync.app not found. Run ./packaging/build_app.sh first."
  exit 1
fi

echo "==> Creating DMG"
rm -f "$DMG_PATH"

# -----------------------------------------------------------------
# Prefer create-dmg (polished layout); fall back to plain hdiutil
# -----------------------------------------------------------------
if command -v create-dmg >/dev/null 2>&1; then
  echo "    Using create-dmg for styled installer"

  CREATE_DMG_ARGS=(
    --volname "$VOLUME_NAME"
    --window-pos 200 120
    --window-size 660 400
    --icon-size 128
    --icon "CalendarSync.app" 160 190
    --app-drop-link 500 190
    --hide-extension "CalendarSync.app"
    --no-internet-enable
  )

  # Volume icon (shown in Finder sidebar / desktop)
  if [[ -f "$ICON_FILE" ]]; then
    CREATE_DMG_ARGS+=(--volicon "$ICON_FILE")
  fi

  # EULA shown when DMG is first opened
  if [[ -f "$EULA_FILE" ]]; then
    CREATE_DMG_ARGS+=(--eula "$EULA_FILE")
  fi

  # create-dmg returns exit code 2 when it "succeeds with warnings"
  # (e.g. Finder positioning on headless CI), so accept 0 or 2.
  create-dmg "${CREATE_DMG_ARGS[@]}" "$DMG_PATH" "$APP_PATH" \
    && true
  rc=$?
  if [[ $rc -ne 0 && $rc -ne 2 ]]; then
    echo "ERROR: create-dmg failed (exit $rc)"
    exit 1
  fi

else
  echo "    create-dmg not found — using plain hdiutil (install create-dmg for a polished DMG)"
  STAGING_DIR="$DMG_DIR/dmg-staging"
  rm -rf "$STAGING_DIR"
  mkdir -p "$STAGING_DIR"
  cp -R "$APP_PATH" "$STAGING_DIR/"
  ln -s /Applications "$STAGING_DIR/Applications"
  if [[ -f "$EULA_FILE" ]]; then
    cp "$EULA_FILE" "$STAGING_DIR/LICENSE.txt"
  fi
  hdiutil create \
    -volname "$VOLUME_NAME" \
    -srcfolder "$STAGING_DIR" \
    -ov \
    -format UDZO \
    "$DMG_PATH"
  rm -rf "$STAGING_DIR"
fi

echo ""
echo "DMG created: $DMG_PATH"
echo ""
echo "Users can open the DMG and drag CalendarSync.app to Applications."
