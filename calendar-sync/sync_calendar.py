#!/usr/bin/env python3
"""
Syncs events from a macOS Calendar (for example O365) to Google Calendar
using icalBuddy and the Google Calendar API.

Configuration precedence:
1) CLI flags
2) Environment variables
3) Built-in defaults
"""

import argparse
import datetime
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app_paths import BUNDLED, DATA_DIR, bundled_icalbuddy_path

SCOPES = ["https://www.googleapis.com/auth/calendar"]
# In bundled mode writable files go to ~/Library/Application Support/CalendarSync;
# in dev mode they stay next to the script.
SCRIPT_DIR = str(DATA_DIR) if BUNDLED else os.path.dirname(os.path.abspath(__file__))

DEFAULT_DAYS_AHEAD = 14
DEFAULT_GOOGLE_CALENDAR_ID = "primary"
DEFAULT_ICALBUDDY_PATH = bundled_icalbuddy_path() or "/opt/homebrew/bin/icalBuddy"
DEFAULT_STATE_RETENTION_DAYS = 30
DEFAULT_CREDENTIALS_PATH = os.path.join(SCRIPT_DIR, "credentials.json")
DEFAULT_TOKEN_PATH = os.path.join(SCRIPT_DIR, "token.json")
DEFAULT_STATE_FILE = os.path.join(SCRIPT_DIR, "sync_state.json")
DEFAULT_LOG_FILE = os.path.join(SCRIPT_DIR, "sync.log")
DEFAULT_ENV_FILE = os.path.join(SCRIPT_DIR, ".env")

def resolve_config_path(path_value):
    """Resolve config paths relative to script directory when not absolute."""
    expanded = os.path.expanduser(path_value)
    if os.path.isabs(expanded):
        return expanded
    return os.path.join(SCRIPT_DIR, expanded)


def load_env_file(env_file):
    """Load KEY=VALUE pairs from an .env file if present."""
    if not os.path.exists(env_file):
        return

    with open(env_file, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key:
                os.environ.setdefault(key, value)


def resolve_int_option(cli_value, env_name, default_value, parser):
    """Resolve an integer option from CLI first, then environment, then default."""
    if cli_value is not None:
        return cli_value

    env_value = os.getenv(env_name)
    if env_value is None:
        return default_value

    try:
        return int(env_value)
    except ValueError:
        parser.error(f"{env_name} must be an integer. Current value: '{env_value}'")


def parse_args():
    """Parse CLI arguments and merge them with environment/default settings."""
    parser = argparse.ArgumentParser(
        description="Copy events from a macOS Calendar to a Google Calendar."
    )
    parser.add_argument(
        "--source-calendar",
        default=None,
        help="Source calendar name in macOS Calendar (or CALSYNC_SOURCE_CALENDAR).",
    )
    parser.add_argument(
        "--google-calendar-id",
        default=None,
        help="Google destination calendar ID (or CALSYNC_GOOGLE_CALENDAR_ID).",
    )
    parser.add_argument(
        "--days-ahead",
        type=int,
        default=None,
        help="Days ahead to sync (or CALSYNC_DAYS_AHEAD).",
    )
    parser.add_argument(
        "--icalbuddy-path",
        default=None,
        help="Path or command name for icalBuddy (or CALSYNC_ICALBUDDY_PATH).",
    )
    parser.add_argument(
        "--credentials-path",
        default=None,
        help="Path to Google OAuth credentials JSON (or CALSYNC_CREDENTIALS_PATH).",
    )
    parser.add_argument(
        "--token-path",
        default=None,
        help="Path to Google OAuth token JSON (or CALSYNC_TOKEN_PATH).",
    )
    parser.add_argument(
        "--state-file",
        default=None,
        help="Path to sync state JSON file (or CALSYNC_STATE_FILE).",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Path to sync log file (or CALSYNC_LOG_FILE).",
    )
    parser.add_argument(
        "--state-retention-days",
        type=int,
        default=None,
        help="Days to keep local sync state entries (or CALSYNC_STATE_RETENTION_DAYS).",
    )

    args = parser.parse_args()

    args.source_calendar = args.source_calendar or os.getenv("CALSYNC_SOURCE_CALENDAR")
    if not args.source_calendar:
        parser.error(
            "source calendar is required. Use --source-calendar or set CALSYNC_SOURCE_CALENDAR."
        )

    args.google_calendar_id = (
        args.google_calendar_id
        or os.getenv("CALSYNC_GOOGLE_CALENDAR_ID")
        or DEFAULT_GOOGLE_CALENDAR_ID
    )
    args.days_ahead = resolve_int_option(
        args.days_ahead, "CALSYNC_DAYS_AHEAD", DEFAULT_DAYS_AHEAD, parser
    )
    args.icalbuddy_path = (
        args.icalbuddy_path
        or os.getenv("CALSYNC_ICALBUDDY_PATH")
        or DEFAULT_ICALBUDDY_PATH
    )
    args.credentials_path = resolve_config_path(
        args.credentials_path
        or os.getenv("CALSYNC_CREDENTIALS_PATH")
        or DEFAULT_CREDENTIALS_PATH
    )
    args.token_path = resolve_config_path(
        args.token_path or os.getenv("CALSYNC_TOKEN_PATH") or DEFAULT_TOKEN_PATH
    )
    args.state_file = resolve_config_path(
        args.state_file or os.getenv("CALSYNC_STATE_FILE") or DEFAULT_STATE_FILE
    )
    args.log_file = resolve_config_path(
        args.log_file or os.getenv("CALSYNC_LOG_FILE") or DEFAULT_LOG_FILE
    )
    args.state_retention_days = resolve_int_option(
        args.state_retention_days,
        "CALSYNC_STATE_RETENTION_DAYS",
        DEFAULT_STATE_RETENTION_DAYS,
        parser,
    )

    if args.days_ahead < 0:
        parser.error("days-ahead must be zero or greater.")
    if args.state_retention_days < 1:
        parser.error("state-retention-days must be at least 1.")

    return args


def setup_logging(log_file):
    """Configure logging handlers."""
    log_dir = os.path.dirname(os.path.abspath(log_file))
    os.makedirs(log_dir, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )


def get_google_service(token_path, credentials_path):
    """Authenticate and return a Google Calendar API service."""
    if not os.path.exists(credentials_path):
        raise FileNotFoundError(
            f"Missing Google OAuth credentials file at '{credentials_path}'. "
            "Create it in Google Cloud Console and save it to this path."
        )

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        token_dir = os.path.dirname(os.path.abspath(token_path))
        os.makedirs(token_dir, exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def resolve_icalbuddy_command(icalbuddy_path):
    """Resolve icalBuddy binary path from an absolute path or command name."""
    if os.path.isabs(icalbuddy_path):
        return icalbuddy_path if os.path.exists(icalbuddy_path) else None

    return shutil.which(icalbuddy_path)


def get_icalbuddy_events(source_calendar, days_ahead, icalbuddy_path):
    """Fetch events from macOS Calendar using icalBuddy."""
    icalbuddy_cmd = resolve_icalbuddy_command(icalbuddy_path)
    if not icalbuddy_cmd:
        logging.error(
            "icalBuddy was not found. Install it with Homebrew (`brew install ical-buddy`) "
            "or set CALSYNC_ICALBUDDY_PATH/--icalbuddy-path correctly."
        )
        return []

    time_window = f"eventsToday+{days_ahead}"
    cmd = [
        icalbuddy_cmd,
        "-ic",
        source_calendar,
        "-b",
        "•",
        "-nc",
        "-nrd",
        "-df",
        "%Y-%m-%d",
        "-tf",
        "%H:%M:%S",
        "-iep",
        "title,datetime,location,notes",
        "-ps",
        "| :: |",
        "-po",
        "title,datetime,location,notes",
        time_window,
    ]

    logging.info("Running icalBuddy for calendar '%s'", source_calendar)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logging.error("icalBuddy error: %s", result.stderr.strip())
        return []

    return parse_icalbuddy_output(result.stdout)


def parse_icalbuddy_output(output):
    """Parse icalBuddy output into a list of event dicts."""
    events = []
    if not output.strip():
        logging.info("No events returned from icalBuddy.")
        return events

    for line in output.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        if line.startswith("•"):
            line = line[1:].strip()

        parts = [part.strip() for part in line.split(" :: ")]
        if len(parts) < 2:
            logging.warning("Skipping malformed line: %s", line)
            continue

        title = parts[0]
        datetime_str = parts[1]
        location = parts[2] if len(parts) > 2 else ""
        notes = parts[3] if len(parts) > 3 else ""

        event = parse_event_datetime(title, datetime_str, location, notes)
        if event:
            events.append(event)

    logging.info("Parsed %d events from icalBuddy.", len(events))
    return events


def parse_event_datetime(title, datetime_str, location, notes):
    """Parse the datetime string from icalBuddy into start/end datetimes."""
    event = {
        "title": title,
        "location": location,
        "notes": notes,
    }

    allday_match = re.match(r"^(\d{4}-\d{2}-\d{2})$", datetime_str)
    if allday_match:
        event["all_day"] = True
        event["start_date"] = allday_match.group(1)
        start = datetime.datetime.strptime(allday_match.group(1), "%Y-%m-%d")
        end = start + datetime.timedelta(days=1)
        event["end_date"] = end.strftime("%Y-%m-%d")
        return event

    multiday_match = re.match(r"^(\d{4}-\d{2}-\d{2})\s*-\s*(\d{4}-\d{2}-\d{2})$", datetime_str)
    if multiday_match:
        event["all_day"] = True
        event["start_date"] = multiday_match.group(1)
        end = datetime.datetime.strptime(multiday_match.group(2), "%Y-%m-%d")
        end = end + datetime.timedelta(days=1)
        event["end_date"] = end.strftime("%Y-%m-%d")
        return event

    timed_match = re.match(
        r"^(\d{4}-\d{2}-\d{2})\s+at\s+(\d{2}:\d{2}:\d{2})\s*-\s*(?:(\d{4}-\d{2}-\d{2})\s+at\s+)?(\d{2}:\d{2}:\d{2})$",
        datetime_str,
    )
    if timed_match:
        start_date = timed_match.group(1)
        start_time = timed_match.group(2)
        end_date = timed_match.group(3) or start_date
        end_time = timed_match.group(4)

        event["all_day"] = False
        event["start_datetime"] = f"{start_date}T{start_time}"
        event["end_datetime"] = f"{end_date}T{end_time}"
        return event

    logging.warning("Could not parse datetime '%s' for event '%s'", datetime_str, title)
    return None


def generate_event_id(event):
    """Generate a deterministic ID for an event to avoid duplicates."""
    if event.get("all_day"):
        key = f"{event['title']}|{event['start_date']}"
    else:
        key = f"{event['title']}|{event['start_datetime']}"
    return hashlib.md5(key.encode()).hexdigest()


def load_state(state_file):
    """Load the sync state (which events have been synced)."""
    if os.path.exists(state_file):
        with open(state_file, "r", encoding="utf-8") as file:
            return json.load(file)
    return {}


def save_state(state_file, state):
    """Save the sync state."""
    state_dir = os.path.dirname(os.path.abspath(state_file))
    os.makedirs(state_dir, exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)


def get_local_timezone_name():
    """Try to return a stable local timezone name for Google event payloads."""
    tz_name = str(datetime.datetime.now().astimezone().tzinfo)

    if len(tz_name) <= 5:
        result = subprocess.run(["systemsetup", "-gettimezone"], capture_output=True, text=True)
        if result.returncode == 0 and "Time Zone:" in result.stdout:
            return result.stdout.split("Time Zone:")[-1].strip()

    return tz_name if tz_name else "UTC"


def sync_event_to_google(service, event, state, google_calendar_id):
    """Create or skip an event in Google Calendar."""
    event_hash = generate_event_id(event)

    if event_hash in state:
        logging.info("Skipping (already synced): %s", event["title"])
        return False

    gc_event = {"summary": event["title"]}
    if event.get("location"):
        gc_event["location"] = event["location"]
    if event.get("notes"):
        gc_event["description"] = event["notes"]

    tz_name = get_local_timezone_name()
    if event.get("all_day"):
        gc_event["start"] = {"date": event["start_date"]}
        gc_event["end"] = {"date": event["end_date"]}
    else:
        gc_event["start"] = {"dateTime": event["start_datetime"], "timeZone": tz_name}
        gc_event["end"] = {"dateTime": event["end_datetime"], "timeZone": tz_name}

    try:
        created = service.events().insert(calendarId=google_calendar_id, body=gc_event).execute()
        logging.info("Created event: %s -> %s", event["title"], created.get("htmlLink"))
        state[event_hash] = {
            "title": event["title"],
            "google_event_id": created["id"],
            "synced_at": datetime.datetime.now().isoformat(),
        }
        return True
    except HttpError as error:
        logging.error("Failed to create event '%s': %s", event["title"], error)
        return False


def cleanup_old_state(state, retention_days):
    """Remove state entries older than N days to prevent file bloat."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=retention_days)
    keys_to_remove = []

    for key, value in state.items():
        synced_at = datetime.datetime.fromisoformat(value.get("synced_at", "2000-01-01"))
        if synced_at < cutoff:
            keys_to_remove.append(key)

    for key in keys_to_remove:
        del state[key]

    if keys_to_remove:
        logging.info("Cleaned up %d old state entries.", len(keys_to_remove))


def main():
    load_env_file(DEFAULT_ENV_FILE)
    args = parse_args()
    setup_logging(args.log_file)

    logging.info("=" * 50)
    logging.info("Starting calendar sync...")
    logging.info("Source macOS calendar: %s", args.source_calendar)
    logging.info("Destination Google calendar ID: %s", args.google_calendar_id)

    events = get_icalbuddy_events(args.source_calendar, args.days_ahead, args.icalbuddy_path)
    if not events:
        logging.info("No events to sync.")
        return

    try:
        service = get_google_service(args.token_path, args.credentials_path)
    except FileNotFoundError as error:
        logging.error("%s", error)
        return

    state = load_state(args.state_file)
    created_count = 0

    for event in events:
        if sync_event_to_google(service, event, state, args.google_calendar_id):
            created_count += 1

    cleanup_old_state(state, args.state_retention_days)
    save_state(args.state_file, state)

    logging.info(
        "Sync complete. Created %d new events out of %d total.",
        created_count,
        len(events),
    )


if __name__ == "__main__":
    main()
