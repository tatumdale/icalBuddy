"""
Centralised path helpers for CalendarSync.

When running inside a py2app .app bundle the source tree is read-only, so
user-writable files (.env, token.json, sync_state.json, logs) live under
~/Library/Application Support/CalendarSync/.

In developer mode (running directly via ``python config_ui.py``) everything
stays relative to the script directory, preserving the existing behaviour.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Detect runtime mode
# ---------------------------------------------------------------------------

def _is_bundled() -> bool:
    """Return True when running inside a py2app / PyInstaller bundle."""
    # py2app sets the frozen attribute; the executable lives inside the .app
    return getattr(sys, "frozen", False)


BUNDLED = _is_bundled()

# ---------------------------------------------------------------------------
# Key directories
# ---------------------------------------------------------------------------

if BUNDLED:
    # .app/Contents/Resources  (read-only, contains bundled data files)
    RESOURCES_DIR = Path(os.environ.get("RESOURCEPATH", Path(__file__).resolve().parent))
    # Writable location following macOS conventions
    DATA_DIR = Path.home() / "Library" / "Application Support" / "CalendarSync"
else:
    # Developer mode – everything relative to the script
    RESOURCES_DIR = Path(__file__).resolve().parent
    DATA_DIR = Path(__file__).resolve().parent

# Ensure the writable data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# iCalBuddy binary resolution
# ---------------------------------------------------------------------------

def bundled_icalbuddy_path() -> str | None:
    """Return the path to the icalBuddy binary embedded inside the .app, or None."""
    if not BUNDLED:
        return None
    candidate = RESOURCES_DIR / "icalBuddy"
    return str(candidate) if candidate.exists() else None
