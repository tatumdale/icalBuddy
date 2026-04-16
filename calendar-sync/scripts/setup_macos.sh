#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required. Install it first: https://brew.sh/"
  exit 1
fi

if ! command -v icalBuddy >/dev/null 2>&1; then
  echo "Installing icalBuddy..."
  brew install ical-buddy
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found in PATH."
  exit 1
fi

python3 -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

if [[ ! -f "$PROJECT_DIR/.env" ]]; then
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
fi

echo "Setup complete."
echo "Next steps:"
echo "1) Put your Google OAuth client file at: $PROJECT_DIR/credentials.json"
echo "2) Run config UI: $PROJECT_DIR/.venv/bin/python $PROJECT_DIR/config_ui.py"
echo "3) In the UI, pick source/destination calendars and set sync interval."
echo "4) Run one sync from UI or with: $PROJECT_DIR/.venv/bin/python $PROJECT_DIR/sync_calendar.py"
