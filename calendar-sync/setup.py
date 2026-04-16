"""
py2app setup for CalendarSync.

Build with:
    python setup.py py2app

The resulting .app lives in dist/CalendarSync.app
"""

from setuptools import setup

APP = ["config_ui.py"]
DATA_FILES = [
    ("", ["sync_calendar.py", "app_paths.py", ".env.example"]),
    ("launchd", ["launchd/com.user.calendarsync.plist.template"]),
]

OPTIONS = {
    "iconfile": "resources/CalendarSync.icns",
    "argv_emulation": False,
    "includes": [
        "flask",
        "google.auth",
        "google.auth.transport.requests",
        "google.oauth2.credentials",
        "google_auth_oauthlib.flow",
        "googleapiclient.discovery",
        "googleapiclient.errors",
        "google_auth_httplib2",
    ],
    "plist": {
        "CFBundleName": "CalendarSync",
        "CFBundleDisplayName": "CalendarSync",
        "CFBundleIdentifier": "com.tatumdale.calendarsync",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "NSCalendarsUsageDescription": (
            "CalendarSync needs access to your calendars to read events "
            "and sync them to Google Calendar."
        ),
        "NSHumanReadableCopyright": "MIT License",
        "LSBackgroundOnly": False,
    },
}

setup(
    app=APP,
    name="CalendarSync",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
