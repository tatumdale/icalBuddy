#!/usr/bin/env bash
#
# Build CalendarSync.dmg from the .app bundle.
#
# Usage:  ./packaging/build_dmg.sh
# Prereq: run ./packaging/build_app.sh first
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_PATH="$REPO_ROOT/calendar-sync/dist/CalendarSync.app"
DMG_DIR="$REPO_ROOT/calendar-sync/dist"
DMG_NAME="CalendarSync.dmg"
DMG_PATH="$DMG_DIR/$DMG_NAME"
VOLUME_NAME="CalendarSync"
STAGING_DIR="$DMG_DIR/dmg-staging"

if [[ ! -d "$APP_PATH" ]]; then
  echo "ERROR: CalendarSync.app not found. Run ./packaging/build_app.sh first."
  exit 1
fi

echo "==> Creating DMG"

# Clean previous DMG
rm -f "$DMG_PATH"
rm -rf "$STAGING_DIR"

# Prepare staging directory
mkdir -p "$STAGING_DIR"
cp -R "$APP_PATH" "$STAGING_DIR/"

# Add Applications symlink for drag-and-drop install
ln -s /Applications "$STAGING_DIR/Applications"

# Create DMG using hdiutil
hdiutil create \
  -volname "$VOLUME_NAME" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

# Cleanup staging
rm -rf "$STAGING_DIR"

echo ""
echo "DMG created: $DMG_PATH"
echo ""
echo "Users can open the DMG and drag CalendarSync.app to Applications."
