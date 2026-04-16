#!/usr/bin/env python3
"""
Lightweight local UI for configuring calendar-sync.

Features:
- dependency checks (Homebrew, iCalBuddy, credentials.json)
- optional iCalBuddy installation via Homebrew
- local macOS calendar listing via icalBuddy
- Google Calendar destination listing via Google Calendar API
- save settings to .env
- apply launchd schedule from selected interval
"""

import os
import plistlib
import re
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, render_template_string, request

from app_paths import BUNDLED, DATA_DIR, RESOURCES_DIR, bundled_icalbuddy_path
from sync_calendar import (
    DEFAULT_DAYS_AHEAD,
    DEFAULT_GOOGLE_CALENDAR_ID,
    DEFAULT_ICALBUDDY_PATH,
    DEFAULT_STATE_RETENTION_DAYS,
    get_google_service,
    resolve_icalbuddy_command,
)

# In bundled mode, writable files live in ~/Library/Application Support/CalendarSync;
# in dev mode this is just the script directory (preserves existing behaviour).
PROJECT_DIR = DATA_DIR
ENV_PATH = PROJECT_DIR / ".env"
DEFAULT_INTERVAL_MINUTES = 60
DEFAULT_CREDENTIALS_SETTING = "./credentials.json"
DEFAULT_TOKEN_SETTING = "./token.json"
DEFAULT_STATE_SETTING = "./sync_state.json"
DEFAULT_LOG_SETTING = "./sync.log"
_BUNDLED_ICALBUDDY = bundled_icalbuddy_path()
DEFAULT_ICALBUDDY_PATHS = [
    p for p in [
        _BUNDLED_ICALBUDDY,
        DEFAULT_ICALBUDDY_PATH,
        "/usr/local/bin/icalBuddy",
    ] if p is not None
]
LAUNCH_AGENT_LABEL = "com.user.calendarsync"
LAUNCH_AGENT_PATH = Path.home() / "Library/LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"

GOOGLE_CALENDAR_CACHE: List[Dict[str, str]] = []

app = Flask(__name__)

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>calendar-sync setup</title>
    <style>
      body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        margin: 0;
        padding: 0;
        background: #f7f7f8;
        color: #111827;
      }
      .container {
        max-width: 900px;
        margin: 0 auto;
        padding: 24px;
      }
      .card {
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 16px;
      }
      h1, h2 {
        margin-top: 0;
      }
      .banner {
        border-radius: 8px;
        padding: 10px 12px;
        margin-bottom: 12px;
        font-size: 0.95rem;
      }
      .banner.success { background: #ecfdf3; border: 1px solid #10b981; }
      .banner.error { background: #fef2f2; border: 1px solid #ef4444; }
      .banner.info { background: #eff6ff; border: 1px solid #3b82f6; }
      .status-list {
        list-style: none;
        padding-left: 0;
        margin: 0 0 12px 0;
      }
      .status-list li {
        margin-bottom: 6px;
      }
      .grid {
        display: grid;
        grid-template-columns: 1fr;
        gap: 10px;
      }
      @media (min-width: 760px) {
        .grid.two-col {
          grid-template-columns: 1fr 1fr;
        }
      }
      label {
        font-weight: 600;
        margin-bottom: 4px;
        display: block;
      }
      input, select {
        width: 100%;
        padding: 8px;
        border: 1px solid #d1d5db;
        border-radius: 8px;
        font-size: 0.95rem;
        box-sizing: border-box;
      }
      .muted {
        color: #6b7280;
        font-size: 0.9rem;
      }
      .buttons {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 14px;
      }
      button {
        border: 1px solid #2563eb;
        background: #2563eb;
        color: white;
        border-radius: 8px;
        padding: 8px 12px;
        cursor: pointer;
      }
      button.secondary {
        background: white;
        color: #1f2937;
        border: 1px solid #d1d5db;
      }
      code {
        background: #f3f4f6;
        padding: 0 4px;
        border-radius: 4px;
      }
    </style>
  </head>
  <body>
    <main class="container">
      <h1>calendar-sync setup</h1>
      <p class="muted">
        Configure source/destination calendars, sync range, and schedule without editing files manually.
      </p>

      {% if message %}
        <div class="banner {{ message_type }}">{{ message }}</div>
      {% endif %}

      <section class="card">
        <h2>1) Dependency status</h2>
        <ul class="status-list">
          <li><strong>Homebrew:</strong> {{ "Installed" if dependency["brew_installed"] else "Missing" }}</li>
          <li><strong>iCalBuddy:</strong> {{ dependency["icalbuddy_path"] if dependency["icalbuddy_path"] else "Missing" }}</li>
          <li><strong>Google credentials file:</strong> {{ "Found" if dependency["credentials_exists"] else "Missing" }} ({{ dependency["credentials_path"] }})</li>
          <li><strong>launchd schedule:</strong> {{ "Configured" if dependency["launch_agent_exists"] else "Not configured yet" }} ({{ launch_agent_path }})</li>
        </ul>
        <form method="post">
          <div class="buttons">
            <button type="submit" name="action" value="install_icalbuddy">Install iCalBuddy (Homebrew)</button>
            <button type="submit" name="action" value="refresh_google_calendars" class="secondary">Connect Google + load calendars</button>
          </div>
        </form>
      </section>

      <section class="card">
        <h2>2) Sync settings</h2>
        {% if local_calendar_error %}
          <p class="muted">{{ local_calendar_error }}</p>
        {% endif %}
        {% if google_calendar_error %}
          <p class="muted">{{ google_calendar_error }}</p>
        {% endif %}

        <form method="post">
          <div class="grid two-col">
            <div>
              <label for="source_calendar">Source local calendar</label>
              <select id="source_calendar" name="source_calendar">
                <option value="">-- Select source calendar --</option>
                {% for calendar in local_calendars %}
                  <option value="{{ calendar }}" {% if calendar == selected_source_calendar %}selected{% endif %}>{{ calendar }}</option>
                {% endfor %}
              </select>
              <p class="muted">If yours is not listed, type it manually below.</p>
              <input type="text" name="source_calendar_manual" value="{{ source_calendar_manual }}" placeholder="Manual source calendar name">
            </div>

            <div>
              <label for="google_calendar_id">Destination Google calendar</label>
              <select id="google_calendar_id" name="google_calendar_id">
                <option value="">-- Select destination calendar --</option>
                {% for calendar in google_calendars %}
                  <option value="{{ calendar['id'] }}" {% if calendar['id'] == selected_google_calendar_id %}selected{% endif %}>{{ calendar['label'] }}</option>
                {% endfor %}
              </select>
              <p class="muted">If needed, paste a calendar ID manually below.</p>
              <input type="text" name="google_calendar_manual" value="{{ google_calendar_manual }}" placeholder="Manual Google calendar ID">
            </div>
          </div>

          <div class="grid two-col" style="margin-top: 10px;">
            <div>
              <label for="days_ahead">Time period to sync (days ahead)</label>
              <input id="days_ahead" type="number" min="1" max="365" name="days_ahead" value="{{ days_ahead }}">
            </div>
            <div>
              <label for="interval_minutes">Sync interval (minutes)</label>
              <input id="interval_minutes" type="number" min="5" max="1440" name="interval_minutes" value="{{ interval_minutes }}">
            </div>
          </div>

          <div class="grid two-col" style="margin-top: 10px;">
            <div>
              <label for="state_retention_days">State retention (days)</label>
              <input id="state_retention_days" type="number" min="1" max="3650" name="state_retention_days" value="{{ state_retention_days }}">
            </div>
            <div>
              <label for="icalbuddy_path">iCalBuddy path/command</label>
              <input id="icalbuddy_path" type="text" name="icalbuddy_path" value="{{ icalbuddy_setting }}">
            </div>
          </div>

          <div class="grid two-col" style="margin-top: 10px;">
            <div>
              <label for="credentials_path">Google credentials path</label>
              <input id="credentials_path" type="text" name="credentials_path" value="{{ credentials_setting }}">
            </div>
            <div>
              <label for="token_path">Google token path</label>
              <input id="token_path" type="text" name="token_path" value="{{ token_setting }}">
            </div>
          </div>

          <div class="buttons">
            <button type="submit" name="action" value="save_settings">Save settings only</button>
            <button type="submit" name="action" value="save_and_apply_schedule">Save settings + apply launchd schedule</button>
            <button type="submit" name="action" value="run_sync_now" class="secondary">Run sync now</button>
          </div>
        </form>
      </section>

      <section class="card">
        <h2>3) What gets written</h2>
        <p class="muted">
          Settings are saved to <code>{{ env_path }}</code>.
          The schedule is written to <code>{{ launch_agent_path }}</code> when you click
          <em>Save settings + apply launchd schedule</em>.
        </p>
      </section>
    </main>
  </body>
</html>
"""

def load_env_values() -> Dict[str, str]:
    """Load .env values as a dict."""
    values: Dict[str, str] = {}
    if not ENV_PATH.exists():
        return values

    with open(ENV_PATH, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def write_env_values(values: Dict[str, str]) -> None:
    """Write selected config keys back to .env in stable order."""
    preferred_order = [
        "CALSYNC_SOURCE_CALENDAR",
        "CALSYNC_GOOGLE_CALENDAR_ID",
        "CALSYNC_DAYS_AHEAD",
        "CALSYNC_INTERVAL_MINUTES",
        "CALSYNC_STATE_RETENTION_DAYS",
        "CALSYNC_ICALBUDDY_PATH",
        "CALSYNC_CREDENTIALS_PATH",
        "CALSYNC_TOKEN_PATH",
        "CALSYNC_STATE_FILE",
        "CALSYNC_LOG_FILE",
    ]

    lines: List[str] = []
    for key in preferred_order:
        if key in values and values[key] != "":
            lines.append(f"{key}={values[key]}\n")

    remaining_keys = sorted(key for key in values.keys() if key not in preferred_order)
    for key in remaining_keys:
        if values[key] != "":
            lines.append(f"{key}={values[key]}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as env_file:
        env_file.writelines(lines)


def resolve_setting_path(path_value: str) -> Path:
    """Resolve path settings relative to project directory."""
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return PROJECT_DIR / path


def safe_int(value: Optional[str], default_value: int) -> int:
    """Parse int safely with default fallback."""
    if value is None:
        return default_value
    try:
        return int(value)
    except ValueError:
        return default_value

def candidate_icalbuddy_settings(configured_path: Optional[str]) -> List[str]:
    """Build unique candidate values to locate iCalBuddy."""
    candidates: List[str] = []
    for candidate in [
        configured_path,
        *DEFAULT_ICALBUDDY_PATHS,
        shutil.which("icalBuddy"),
        "icalBuddy",
    ]:
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def detect_icalbuddy_path(configured_path: Optional[str]) -> Optional[str]:
    """Return first resolvable iCalBuddy path from known candidates."""
    for candidate in candidate_icalbuddy_settings(configured_path):
        resolved = resolve_icalbuddy_command(candidate)
        if resolved:
            return resolved
    return None


def run_icalbuddy_command(command: List[str]) -> subprocess.CompletedProcess[str]:
    """Run an iCalBuddy command with explicit PATH for Homebrew locations."""
    env = os.environ.copy()
    path_prefix = "/opt/homebrew/bin:/usr/local/bin"
    existing_path = env.get("PATH", "")
    env["PATH"] = f"{path_prefix}:{existing_path}" if existing_path else path_prefix
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )


def dependency_status(config: Dict[str, str]) -> Dict[str, Any]:
    """Return dependency and environment status info for display."""
    icalbuddy_setting = config.get("CALSYNC_ICALBUDDY_PATH", DEFAULT_ICALBUDDY_PATH)
    credentials_setting = config.get("CALSYNC_CREDENTIALS_PATH", DEFAULT_CREDENTIALS_SETTING)
    credentials_path = resolve_setting_path(credentials_setting)
    detected_icalbuddy_path = detect_icalbuddy_path(icalbuddy_setting)

    return {
        "brew_installed": shutil.which("brew") is not None,
        "icalbuddy_path": detected_icalbuddy_path,
        "credentials_exists": credentials_path.exists(),
        "credentials_path": str(credentials_path),
        "launch_agent_exists": LAUNCH_AGENT_PATH.exists(),
    }


def parse_icalbuddy_calendar_lines(output: str) -> List[str]:
    """Parse calendar names from icalBuddy calendars output."""
    calendars: List[str] = []
    ansi_escape_pattern = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
    for line in output.splitlines():
        cleaned = ansi_escape_pattern.sub("", line).strip()
        if not cleaned:
            continue
        if cleaned.lower() in {"calendars", "calendars:"}:
            continue
        cleaned = cleaned.lstrip("•").strip()
        cleaned = cleaned.lstrip("-").strip()
        cleaned = cleaned.lstrip("*").strip()
        if cleaned:
            calendars.append(cleaned)
    return calendars


def get_local_calendars(icalbuddy_setting: str) -> Tuple[List[str], str]:
    """Return local macOS calendar names and any status message."""
    last_error = (
        "iCalBuddy returned no calendars. "
        "Open System Settings → Privacy & Security → Calendars and allow access, "
        "then restart the UI."
    )

    for candidate in candidate_icalbuddy_settings(icalbuddy_setting):
        command_path = resolve_icalbuddy_command(candidate) or candidate
        for command in [[command_path, "calendars"], [command_path, "-f", "calendars"]]:
            try:
                result = run_icalbuddy_command(command)
            except subprocess.TimeoutExpired:
                return [], "iCalBuddy calendars command timed out."
            except OSError:
                continue

            calendars = parse_icalbuddy_calendar_lines(result.stdout)
            if calendars:
                return calendars, ""

            if result.returncode != 0:
                last_error = result.stderr.strip() or "Unable to query local calendars."

    for shell_command in ["icalBuddy calendars", "icalBuddy -f calendars"]:
        try:
            result = run_icalbuddy_command(["zsh", "-lc", shell_command])
        except subprocess.TimeoutExpired:
            return [], "iCalBuddy calendars command timed out."
        except OSError:
            continue

        calendars = parse_icalbuddy_calendar_lines(result.stdout)
        if calendars:
            return calendars, ""

        if result.returncode != 0:
            last_error = result.stderr.strip() or last_error

    return [], last_error


def get_google_calendars(
    config: Dict[str, str],
    allow_interactive_auth: bool,
) -> Tuple[List[Dict[str, str]], str]:
    """Fetch Google calendars for destination selection."""
    credentials_setting = config.get("CALSYNC_CREDENTIALS_PATH", DEFAULT_CREDENTIALS_SETTING)
    token_setting = config.get("CALSYNC_TOKEN_PATH", DEFAULT_TOKEN_SETTING)

    credentials_path = resolve_setting_path(credentials_setting)
    token_path = resolve_setting_path(token_setting)

    if not credentials_path.exists():
        return [], f"Missing credentials file: {credentials_path}"

    if not allow_interactive_auth and not token_path.exists():
        return [], "Google token not created yet. Click 'Connect Google + load calendars'."

    try:
        service = get_google_service(str(token_path), str(credentials_path))
    except Exception as error:  # pragma: no cover - runtime auth/env dependent
        return [], str(error)

    page_token: Optional[str] = None
    calendars: List[Dict[str, str]] = []
    while True:
        response = service.calendarList().list(pageToken=page_token).execute()
        for item in response.get("items", []):
            calendar_id = item.get("id", "")
            summary = item.get("summary", "(unnamed)")
            is_primary = bool(item.get("primary", False))
            label = f"{summary} ({calendar_id})"
            if is_primary:
                label = f"{label} [primary]"
            calendars.append({"id": calendar_id, "label": label})

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    calendars.sort(key=lambda item: item["label"].casefold())
    return calendars, ""


def summarize_command_output(result: subprocess.CompletedProcess[str]) -> str:
    """Return concise command output for UI messages."""
    combined_output = "\n".join(
        part for part in [result.stdout.strip(), result.stderr.strip()] if part
    ).strip()
    if not combined_output:
        return "No output returned."

    lines = combined_output.splitlines()
    if len(lines) > 12:
        lines = lines[-12:]
    return "\n".join(lines)


def install_icalbuddy() -> Tuple[bool, str]:
    """Install iCalBuddy via Homebrew."""
    brew_path = shutil.which("brew")
    if not brew_path:
        return False, "Homebrew is not installed. Install Homebrew first: https://brew.sh/"

    result = subprocess.run(
        [brew_path, "install", "ical-buddy"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = summarize_command_output(result).lower()
        if "already installed" in output:
            return True, "iCalBuddy is already installed."
        return False, f"Failed to install iCalBuddy.\n{summarize_command_output(result)}"

    return True, "iCalBuddy installed successfully."


def choose_python_interpreter() -> str:
    """Prefer project virtualenv Python when available."""
    if BUNDLED:
        # In a .app bundle, use the bundled Python executable
        return sys.executable
    venv_python = PROJECT_DIR / ".venv/bin/python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def write_launch_agent(interval_minutes: int) -> None:
    """Write launchd plist using the selected interval."""
    LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)

    plist_data: Dict[str, Any] = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            choose_python_interpreter(),
            _locate_sync_script(),
        ],
        "WorkingDirectory": str(PROJECT_DIR),
        "StartInterval": interval_minutes * 60,
        "StandardOutPath": str(PROJECT_DIR / "launchd.log"),
        "StandardErrorPath": str(PROJECT_DIR / "launchd_error.log"),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        },
    }

    with open(LAUNCH_AGENT_PATH, "wb") as plist_file:
        plistlib.dump(plist_data, plist_file)


def apply_launch_agent_schedule(interval_minutes: int) -> Tuple[bool, str]:
    """Save and reload launchd schedule."""
    write_launch_agent(interval_minutes)

    domain_target = f"gui/{os.getuid()}"

    subprocess.run(
        ["launchctl", "bootout", domain_target, str(LAUNCH_AGENT_PATH)],
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        ["launchctl", "bootstrap", domain_target, str(LAUNCH_AGENT_PATH)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, f"Failed to apply launchd schedule.\n{summarize_command_output(result)}"

    return True, (
        f"launchd schedule updated to run every {interval_minutes} minutes."
    )


def _locate_sync_script() -> str:
    """Return the path to sync_calendar.py (bundled Resources or dev tree)."""
    if BUNDLED:
        return str(RESOURCES_DIR / "sync_calendar.py")
    return str(PROJECT_DIR / "sync_calendar.py")


def run_sync_now() -> Tuple[bool, str]:
    """Execute sync immediately."""
    result = subprocess.run(
        [choose_python_interpreter(), _locate_sync_script()],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, f"Sync failed.\n{summarize_command_output(result)}"
    return True, "Sync completed successfully."


def save_settings_from_form(
    form_data: Dict[str, str],
    config: Dict[str, str],
) -> Tuple[bool, str, int]:
    """Validate and save form values to .env."""
    source_calendar = (
        form_data.get("source_calendar_manual", "").strip()
        or form_data.get("source_calendar", "").strip()
    )
    google_calendar_id = (
        form_data.get("google_calendar_manual", "").strip()
        or form_data.get("google_calendar_id", "").strip()
    )

    days_ahead = safe_int(form_data.get("days_ahead"), DEFAULT_DAYS_AHEAD)
    interval_minutes = safe_int(form_data.get("interval_minutes"), DEFAULT_INTERVAL_MINUTES)
    state_retention_days = safe_int(
        form_data.get("state_retention_days"),
        DEFAULT_STATE_RETENTION_DAYS,
    )

    if not source_calendar:
        return False, "Please select or enter a source calendar.", interval_minutes
    if not google_calendar_id:
        return False, "Please select or enter a destination Google calendar.", interval_minutes
    if days_ahead < 1 or days_ahead > 365:
        return False, "Time period (days ahead) must be between 1 and 365.", interval_minutes
    if interval_minutes < 5 or interval_minutes > 1440:
        return False, "Sync interval must be between 5 and 1440 minutes.", interval_minutes
    if state_retention_days < 1 or state_retention_days > 3650:
        return False, "State retention must be between 1 and 3650 days.", interval_minutes

    updated = dict(config)
    updated["CALSYNC_SOURCE_CALENDAR"] = source_calendar
    updated["CALSYNC_GOOGLE_CALENDAR_ID"] = google_calendar_id
    updated["CALSYNC_DAYS_AHEAD"] = str(days_ahead)
    updated["CALSYNC_INTERVAL_MINUTES"] = str(interval_minutes)
    updated["CALSYNC_STATE_RETENTION_DAYS"] = str(state_retention_days)
    detected_icalbuddy_path = detect_icalbuddy_path(
        config.get("CALSYNC_ICALBUDDY_PATH", DEFAULT_ICALBUDDY_PATH)
    )
    updated["CALSYNC_ICALBUDDY_PATH"] = (
        form_data.get("icalbuddy_path", "").strip()
        or detected_icalbuddy_path
        or config.get("CALSYNC_ICALBUDDY_PATH", DEFAULT_ICALBUDDY_PATH)
    )
    updated["CALSYNC_CREDENTIALS_PATH"] = (
        form_data.get("credentials_path", "").strip() or DEFAULT_CREDENTIALS_SETTING
    )
    updated["CALSYNC_TOKEN_PATH"] = (
        form_data.get("token_path", "").strip() or DEFAULT_TOKEN_SETTING
    )
    updated["CALSYNC_STATE_FILE"] = config.get("CALSYNC_STATE_FILE", DEFAULT_STATE_SETTING)
    updated["CALSYNC_LOG_FILE"] = config.get("CALSYNC_LOG_FILE", DEFAULT_LOG_SETTING)

    write_env_values(updated)
    return True, "Settings saved to .env.", interval_minutes


@app.route("/", methods=["GET", "POST"])
def index():
    """Render settings UI and process actions."""
    global GOOGLE_CALENDAR_CACHE

    message = ""
    message_type = "info"
    local_calendar_error = ""
    google_calendar_error = ""

    config = load_env_values()

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "install_icalbuddy":
            success, message = install_icalbuddy()
            message_type = "success" if success else "error"
            if success:
                config = load_env_values()
                detected_icalbuddy_path = detect_icalbuddy_path(
                    config.get("CALSYNC_ICALBUDDY_PATH", DEFAULT_ICALBUDDY_PATH)
                )
                if detected_icalbuddy_path:
                    config["CALSYNC_ICALBUDDY_PATH"] = detected_icalbuddy_path
                    write_env_values(config)
                calendars, calendar_error = get_local_calendars(
                    config.get("CALSYNC_ICALBUDDY_PATH", DEFAULT_ICALBUDDY_PATH)
                )
                if calendars:
                    message = (
                        f"iCalBuddy installed successfully. "
                        f"Detected {len(calendars)} local calendars."
                    )
                else:
                    message = (
                        "iCalBuddy installed successfully, but local calendars are not readable yet. "
                        f"{calendar_error} "
                        "Verify by running: /opt/homebrew/bin/icalBuddy calendars"
                    )
                    message_type = "error"

        elif action == "refresh_google_calendars":
            calendars, google_calendar_error = get_google_calendars(
                config,
                allow_interactive_auth=True,
            )
            if calendars:
                GOOGLE_CALENDAR_CACHE = calendars
                message = f"Loaded {len(calendars)} Google calendars."
                message_type = "success"
            else:
                message = google_calendar_error or "No Google calendars found."
                message_type = "error"

        elif action in {"save_settings", "save_and_apply_schedule"}:
            success, save_message, interval_minutes = save_settings_from_form(
                request.form.to_dict(),
                config,
            )
            if not success:
                message = save_message
                message_type = "error"
            else:
                config = load_env_values()
                if action == "save_and_apply_schedule":
                    schedule_success, schedule_message = apply_launch_agent_schedule(
                        interval_minutes
                    )
                    message = f"{save_message} {schedule_message}"
                    message_type = "success" if schedule_success else "error"
                else:
                    message = save_message
                    message_type = "success"

        elif action == "run_sync_now":
            success, message = run_sync_now()
            message_type = "success" if success else "error"

        config = load_env_values()

    dependency = dependency_status(config)

    local_calendars, local_calendar_error = get_local_calendars(
        config.get("CALSYNC_ICALBUDDY_PATH", DEFAULT_ICALBUDDY_PATH)
    )

    if not GOOGLE_CALENDAR_CACHE:
        cached_calendars, cache_message = get_google_calendars(
            config,
            allow_interactive_auth=False,
        )
        if cached_calendars:
            GOOGLE_CALENDAR_CACHE = cached_calendars
        elif not google_calendar_error:
            google_calendar_error = cache_message

    selected_source_calendar = config.get("CALSYNC_SOURCE_CALENDAR", "")
    selected_google_calendar_id = config.get(
        "CALSYNC_GOOGLE_CALENDAR_ID",
        DEFAULT_GOOGLE_CALENDAR_ID,
    )

    source_calendar_manual = ""
    if selected_source_calendar and selected_source_calendar not in local_calendars:
        source_calendar_manual = selected_source_calendar

    known_google_ids = {calendar["id"] for calendar in GOOGLE_CALENDAR_CACHE}
    google_calendar_manual = ""
    if selected_google_calendar_id and selected_google_calendar_id not in known_google_ids:
        google_calendar_manual = selected_google_calendar_id

    return render_template_string(
        HTML_TEMPLATE,
        message=message,
        message_type=message_type,
        dependency=dependency,
        local_calendars=local_calendars,
        local_calendar_error=local_calendar_error,
        google_calendars=GOOGLE_CALENDAR_CACHE,
        google_calendar_error=google_calendar_error,
        selected_source_calendar=selected_source_calendar,
        selected_google_calendar_id=selected_google_calendar_id,
        source_calendar_manual=source_calendar_manual,
        google_calendar_manual=google_calendar_manual,
        days_ahead=safe_int(config.get("CALSYNC_DAYS_AHEAD"), DEFAULT_DAYS_AHEAD),
        interval_minutes=safe_int(
            config.get("CALSYNC_INTERVAL_MINUTES"),
            DEFAULT_INTERVAL_MINUTES,
        ),
        state_retention_days=safe_int(
            config.get("CALSYNC_STATE_RETENTION_DAYS"),
            DEFAULT_STATE_RETENTION_DAYS,
        ),
        icalbuddy_setting=config.get("CALSYNC_ICALBUDDY_PATH", DEFAULT_ICALBUDDY_PATH),
        credentials_setting=config.get(
            "CALSYNC_CREDENTIALS_PATH",
            DEFAULT_CREDENTIALS_SETTING,
        ),
        token_setting=config.get("CALSYNC_TOKEN_PATH", DEFAULT_TOKEN_SETTING),
        env_path=str(ENV_PATH),
        launch_agent_path=str(LAUNCH_AGENT_PATH),
    )


if __name__ == "__main__":
    url = "http://127.0.0.1:8787"
    print(f"Starting config UI at {url}")
    webbrowser.open(url)
    app.run(host="127.0.0.1", port=8787, debug=False)
