# icalBuddy + CalendarSync

A macOS tool that reads events from Calendar.app using [icalBuddy](http://hasseg.org/icalBuddy) and syncs them to Google Calendar.

Distributed as a DMG — drag to Applications, launch, and macOS will prompt for calendar access automatically.

## Install (end users)

1. Download **CalendarSync.dmg** from the [latest release](https://github.com/tatumdale/icalBuddy/releases).
2. Open the DMG and drag **CalendarSync** into your **Applications** folder.
3. Launch **CalendarSync**. macOS will ask for calendar access on first run — click **Allow**.
4. The setup UI opens in your browser. Follow the steps to:
   - Choose your source macOS calendar
   - Connect your Google account and pick a destination calendar
   - Set sync interval and save

Configuration and runtime files are stored in `~/Library/Application Support/CalendarSync/`.

## What it does

- Reads events from a named macOS Calendar using the bundled `icalBuddy` binary
- Creates matching events in a destination Google Calendar via the Google Calendar API
- Tracks synced events in a local state file to avoid duplicates
- Optionally runs on a schedule via macOS launchd

## Developer setup

If you want to run from source or contribute:

### Prerequisites
- macOS with Calendar.app configured
- Python 3.9+
- Homebrew
- Google Cloud OAuth Desktop credentials (`credentials.json`)

### Quick start
```bash
git clone https://github.com/tatumdale/icalBuddy.git
cd icalBuddy/calendar-sync
./scripts/setup_macos.sh
cp .env.example .env
# Edit .env and set CALSYNC_SOURCE_CALENDAR
./.venv/bin/python config_ui.py
```

### Configuration
The sync script resolves configuration in this order:
1. CLI flag
2. Environment variable (from `.env`)
3. Built-in default

Key environment variables:
- `CALSYNC_SOURCE_CALENDAR` (required)
- `CALSYNC_GOOGLE_CALENDAR_ID` (default: `primary`)
- `CALSYNC_DAYS_AHEAD` (default: `14`)
- `CALSYNC_INTERVAL_MINUTES` (default: `60`)
- `CALSYNC_ICALBUDDY_PATH` (default: `/opt/homebrew/bin/icalBuddy`)

See `.env.example` for the full list.

## Building the DMG

### Local build
```bash
./packaging/build_app.sh   # Builds CalendarSync.app
./packaging/build_dmg.sh   # Packages into CalendarSync.dmg
```

The build script will:
1. Try to compile `icalBuddy` from the Objective-C source; falls back to a Homebrew-installed binary
2. Create a Python venv and install dependencies
3. Run py2app to produce `CalendarSync.app`
4. Embed the `icalBuddy` binary into the app bundle

### CI / releases
Push a tag (e.g. `git tag v1.0.0 && git push --tags`) to trigger the GitHub Actions workflow, which builds the DMG and attaches it to a GitHub Release.

### Optional code signing
For ad-hoc signing (allows running without right-click → Open):
```bash
codesign --force --deep --sign - \
  --entitlements packaging/entitlements.plist \
  calendar-sync/dist/CalendarSync.app
```

## Calendar permissions

The `.app` bundle declares `NSCalendarsUsageDescription` in its `Info.plist`, so macOS shows a native permission prompt on first launch. No manual System Settings navigation needed.

If you run from source (not the `.app`), you may need to grant calendar access to Terminal or your IDE manually via System Settings → Privacy & Security → Calendars.

## Security notes
Never commit: `credentials.json`, `token.json`, `sync_state.json`, `*.log`

## The MIT License

Copyright (c) Ali Rantakari (original icalBuddy)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
