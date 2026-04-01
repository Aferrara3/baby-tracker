import os

# Path to Google service account credentials JSON
CREDENTIALS_PATH = os.environ.get(
    "GOOGLE_CREDENTIALS_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "baby-tracker-491801-5158858c7b8a.json")
)

# Google Calendar ID shared with the service account
CALENDAR_ID = os.environ.get(
    "GOOGLE_CALENDAR_ID",
    "c02403bb28d3e1dbbbffca717d10c14d8587856349243e8402bdf4ba1aee6dee@group.calendar.google.com"
)
