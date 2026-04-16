#!/usr/bin/env bash
#
# Build CalendarSync.dmg from the .app bundle.
#
# Usage:  ./packaging/build_dmg.sh
# Prereq: run ./packaging/build_app.sh first
#         brew install fileicon   (for custom Applications folder icon)
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_PATH="$REPO_ROOT/calendar-sync/dist/CalendarSync.app"
DMG_DIR="$REPO_ROOT/calendar-sync/dist"
DMG_NAME="CalendarSync.dmg"
DMG_PATH="$DMG_DIR/$DMG_NAME"
RW_DMG_PATH="$DMG_DIR/CalendarSync-rw.dmg"
VOLUME_NAME="CalendarSync"
ICON_FILE="$REPO_ROOT/calendar-sync/resources/CalendarSync.icns"
APPS_ICON_FILE="$REPO_ROOT/calendar-sync/resources/ApplicationsFolder.icns"
EULA_FILE="$REPO_ROOT/packaging/LICENSE_EULA.txt"

if [[ ! -d "$APP_PATH" ]]; then
  echo "ERROR: CalendarSync.app not found. Run ./packaging/build_app.sh first."
  exit 1
fi

echo "==> Creating DMG"
rm -f "$DMG_PATH" "$RW_DMG_PATH"
# Unmount any previous build volume
hdiutil detach "/Volumes/$VOLUME_NAME" -quiet 2>/dev/null || true

# -----------------------------------------------------------------
# 1. Create a read-write DMG, large enough to hold the .app
# -----------------------------------------------------------------
APP_SIZE_MB=$(du -sm "$APP_PATH" | awk '{print $1}')
DMG_SIZE_MB=$(( APP_SIZE_MB + 20 ))   # headroom for symlink + metadata
echo "    Creating ${DMG_SIZE_MB}MB read-write volume"

hdiutil create \
  -size "${DMG_SIZE_MB}m" \
  -fs HFS+ \
  -volname "$VOLUME_NAME" \
  -type SPARSE \
  -ov \
  "$RW_DMG_PATH"

# -----------------------------------------------------------------
# 2. Mount it read-write (at default /Volumes/ so Finder can see it)
# -----------------------------------------------------------------
hdiutil attach "$RW_DMG_PATH.sparseimage" -noverify -noautoopen
MOUNT_POINT="/Volumes/$VOLUME_NAME"

if [[ ! -d "$MOUNT_POINT" ]]; then
  echo "ERROR: Volume did not mount at $MOUNT_POINT"
  exit 1
fi

# -----------------------------------------------------------------
# 3. Copy app into volume
# -----------------------------------------------------------------
cp -R "$APP_PATH" "$MOUNT_POINT/"

# -----------------------------------------------------------------
# 4. Create Applications alias + set custom icon
#    A Finder alias (not a Unix symlink) supports custom icons.
# -----------------------------------------------------------------
echo "    Creating Applications alias with custom icon"
osascript -e 'tell application "Finder" to make alias file to POSIX file "/Applications" at POSIX file "'"$MOUNT_POINT"'" with properties {name:"Applications"}' || \
  ln -s /Applications "$MOUNT_POINT/Applications"   # fallback to symlink

if command -v fileicon >/dev/null 2>&1 && [[ -f "$APPS_ICON_FILE" ]]; then
  echo "    Setting Applications folder icon via fileicon"
  fileicon set "$MOUNT_POINT/Applications" "$APPS_ICON_FILE" || true
fi

# -----------------------------------------------------------------
# 5. Set volume icon
# -----------------------------------------------------------------
if [[ -f "$ICON_FILE" ]]; then
  cp "$ICON_FILE" "$MOUNT_POINT/.VolumeIcon.icns"
  SetFile -a C "$MOUNT_POINT" 2>/dev/null || true
fi

# -----------------------------------------------------------------
# 6. Configure Finder window (icon positions, view style)
# -----------------------------------------------------------------
echo "    Configuring Finder window layout"
osascript <<'APPLESCRIPT' || true
tell application "Finder"
  tell disk "CalendarSync"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set bounds of container window to {200, 120, 860, 520}
    set opts to icon view options of container window
    set icon size of opts to 128
    set arrangement of opts to not arranged
    set position of item "CalendarSync.app" of container window to {160, 190}
    set position of item "Applications" of container window to {500, 190}
    close
    open
    update without registering applications
    close
  end tell
end tell
APPLESCRIPT

# Give Finder a moment to write .DS_Store
sleep 2

# -----------------------------------------------------------------
# 7. Unmount and convert to compressed read-only DMG
# -----------------------------------------------------------------
echo "    Converting to compressed DMG"
hdiutil detach "$MOUNT_POINT" -quiet
hdiutil convert "$RW_DMG_PATH.sparseimage" \
  -format UDZO \
  -o "$DMG_PATH" \
  -ov

rm -f "$RW_DMG_PATH.sparseimage"

# -----------------------------------------------------------------
# 8. Embed EULA (shown before DMG mounts)
# -----------------------------------------------------------------
if [[ -f "$EULA_FILE" ]]; then
  echo "    Embedding EULA"
  # create-dmg's EULA embedding if available, otherwise python fallback
  if command -v create-dmg >/dev/null 2>&1; then
    # Use create-dmg just for EULA injection on the existing DMG
    python3 "$(brew --prefix create-dmg 2>/dev/null || echo /opt/homebrew/Cellar/create-dmg)/support/dmg-license.py" \
      "$DMG_PATH" "$EULA_FILE" 2>/dev/null || \
    echo "    Note: EULA embedding skipped (dmg-license.py not found). Include LICENSE.txt manually."
  fi
fi

echo ""
echo "DMG created: $DMG_PATH"
echo ""
echo "Users can open the DMG and drag CalendarSync.app to Applications."
