import os

# Path to Google service account credentials JSON
CREDENTIALS_PATH = os.environ.get(
    "GOOGLE_CREDENTIALS_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "baby-tracker-491801-5158858c7b8a.json"),
)

# Legacy fallback calendar used by the original single-tenant app.
CALENDAR_ID = os.environ.get(
    "GOOGLE_CALENDAR_ID",
    "c02403bb28d3e1dbbbffca717d10c14d8587856349243e8402bdf4ba1aee6dee@group.calendar.google.com",
)

CALENDAR_TIME_ZONE = os.environ.get("GOOGLE_CALENDAR_TIME_ZONE", "UTC")
CALENDAR_SHARE_ROLE = os.environ.get("GOOGLE_CALENDAR_SHARE_ROLE", "writer")
SESSION_TTL_DAYS = int(os.environ.get("SESSION_TTL_DAYS", "30"))
