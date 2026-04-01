import os
from pathlib import Path


def _parse_csv_env(name: str, default: str = "") -> list[str]:
    value = os.environ.get(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_DB_PATH = BACKEND_DIR / "database-dev.db"
DB_PATH = Path(os.environ.get("DB_PATH", str(DEFAULT_DB_PATH))).expanduser()

# Path to Google service account credentials JSON
CREDENTIALS_PATH = os.environ.get(
    "GOOGLE_CREDENTIALS_PATH",
    str(REPO_ROOT / "google-service-account-creds.json"),
)

# Legacy fallback calendar used by the original single-tenant app.
CALENDAR_ID = os.environ.get(
    "GOOGLE_CALENDAR_ID",
    "c02403bb28d3e1dbbbffca717d10c14d8587856349243e8402bdf4ba1aee6dee@group.calendar.google.com",
)

CALENDAR_TIME_ZONE = os.environ.get("GOOGLE_CALENDAR_TIME_ZONE", "UTC")
CALENDAR_SHARE_ROLE = os.environ.get("GOOGLE_CALENDAR_SHARE_ROLE", "writer")
SESSION_TTL_DAYS = int(os.environ.get("SESSION_TTL_DAYS", "30"))
APP_HOST = os.environ.get("APP_HOST", "0.0.0.0")
APP_PORT = int(os.environ.get("APP_PORT", "8090"))
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")
FRONTEND_DIST_PATH = os.environ.get("FRONTEND_DIST_PATH")
CORS_ALLOWED_ORIGINS = _parse_csv_env("CORS_ALLOWED_ORIGINS", "http://localhost:3005")
