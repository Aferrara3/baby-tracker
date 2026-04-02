import hashlib
import json
import logging
import os
import random
from pathlib import Path
import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlmodel import Field, SQLModel, Session, create_engine, select

from calendar_service import (
    CalendarService,
    activity_label,
    infer_activity_type_from_summary,
    normalize_activity_type,
)
from config import (
    APP_HOST,
    APP_PORT,
    CALENDAR_ID,
    CORS_ALLOWED_ORIGINS,
    CREDENTIALS_PATH,
    DATABASE_URL,
    FRONTEND_DIST_PATH,
    SESSION_TTL_DAYS,
)

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)

TRACKER_BUTTON_COUNT = 8
TRACKER_BUTTON_LABEL_MAX_LENGTH = 24

TRACKER_SYMBOLS: list[dict[str, object]] = [
    {"key": "bottle-wine", "label": "Bottle", "emoji": "🍼", "keywords": ["milk", "feed", "drink"]},
    {"key": "utensils", "label": "Food", "emoji": "🥄", "keywords": ["meal", "eat", "snack"]},
    {"key": "baby", "label": "Baby", "emoji": "👶", "keywords": ["kid", "child", "care"]},
    {"key": "droplet", "label": "Pee", "emoji": "💧", "keywords": ["diaper", "wet", "bathroom"]},
    {"key": "moon", "label": "Sleep", "emoji": "😴", "keywords": ["nap", "rest", "night"]},
    {"key": "toilet", "label": "Poop", "emoji": "💩", "keywords": ["diaper", "bathroom", "change"]},
    {"key": "user-2", "label": "Person", "emoji": "🧍", "keywords": ["personal", "self", "caregiver"]},
    {"key": "milk", "label": "Milk", "emoji": "🥛", "keywords": ["pump", "drink", "feed"]},
    {"key": "help-circle", "label": "Help", "emoji": "❓", "keywords": ["other", "misc", "question"]},
    {"key": "briefcase", "label": "Work", "emoji": "💼", "keywords": ["office", "job", "career"]},
    {"key": "dumbbell", "label": "Exercise", "emoji": "🏋️", "keywords": ["workout", "gym", "fitness"]},
    {"key": "bath", "label": "Bath", "emoji": "🛁", "keywords": ["wash", "clean", "shower"]},
    {"key": "car-front", "label": "Travel", "emoji": "🚗", "keywords": ["drive", "trip", "car"]},
    {"key": "shopping-bag", "label": "Errands", "emoji": "🛍️", "keywords": ["shop", "store", "buy"]},
    {"key": "house", "label": "Home", "emoji": "🏠", "keywords": ["household", "chores", "home"]},
    {"key": "book-open", "label": "Learning", "emoji": "📚", "keywords": ["reading", "school", "study"]},
    {"key": "stethoscope", "label": "Health", "emoji": "🩺", "keywords": ["doctor", "medical", "care"]},
    {"key": "phone", "label": "Call", "emoji": "📞", "keywords": ["phone", "talk", "contact"]},
    {"key": "music-4", "label": "Music", "emoji": "🎵", "keywords": ["song", "audio", "listen"]},
    {"key": "heart", "label": "Love", "emoji": "❤️", "keywords": ["care", "family", "connection"]},
    {"key": "pill", "label": "Medicine", "emoji": "💊", "keywords": ["meds", "rx", "health"]},
    {"key": "timer", "label": "Timer", "emoji": "⏱️", "keywords": ["track", "duration", "time"]},
    {"key": "paw-print", "label": "Pet", "emoji": "🐾", "keywords": ["pet", "animal", "walk"]},
    {"key": "bone", "label": "Pet food", "emoji": "🦴", "keywords": ["dog", "pet", "treat"]},
    {"key": "cat", "label": "Cat", "emoji": "🐱", "keywords": ["pet", "animal", "feline"]},
    {"key": "dog", "label": "Dog", "emoji": "🐶", "keywords": ["pet", "animal", "canine"]},
    {"key": "fish", "label": "Fish", "emoji": "🐟", "keywords": ["pet", "tank", "aquarium"]},
    {"key": "bird", "label": "Bird", "emoji": "🐦", "keywords": ["pet", "animal", "avian"]},
    {"key": "rabbit", "label": "Rabbit", "emoji": "🐰", "keywords": ["pet", "animal", "bunny"]},
    {"key": "syringe", "label": "Shot", "emoji": "💉", "keywords": ["vaccine", "medical", "medicine"]},
    {"key": "thermometer", "label": "Temperature", "emoji": "🌡️", "keywords": ["fever", "check", "health"]},
    {"key": "heart-pulse", "label": "Vitals", "emoji": "🫀", "keywords": ["heart", "pulse", "health"]},
    {"key": "apple", "label": "Fruit", "emoji": "🍎", "keywords": ["snack", "food", "nutrition"]},
    {"key": "salad", "label": "Salad", "emoji": "🥗", "keywords": ["meal", "greens", "nutrition"]},
    {"key": "sandwich", "label": "Lunch", "emoji": "🥪", "keywords": ["meal", "food", "sandwich"]},
    {"key": "carrot", "label": "Veggies", "emoji": "🥕", "keywords": ["vegetable", "food", "nutrition"]},
    {"key": "coffee", "label": "Coffee", "emoji": "☕", "keywords": ["drink", "caffeine", "break"]},
    {"key": "cake", "label": "Treat", "emoji": "🎂", "keywords": ["dessert", "celebration", "snack"]},
    {"key": "alarm-clock", "label": "Reminder", "emoji": "⏰", "keywords": ["alarm", "wake", "time"]},
    {"key": "calendar-check", "label": "Appointment", "emoji": "🗓️", "keywords": ["calendar", "meeting", "scheduled"]},
    {"key": "calendar-heart", "label": "Special day", "emoji": "💗", "keywords": ["date", "anniversary", "celebration"]},
    {"key": "clipboard-list", "label": "Checklist", "emoji": "📋", "keywords": ["tasks", "todo", "notes"]},
    {"key": "sun", "label": "Daytime", "emoji": "☀️", "keywords": ["morning", "day", "outside"]},
    {"key": "moon-star", "label": "Night", "emoji": "🌙", "keywords": ["evening", "bedtime", "night"]},
    {"key": "bed", "label": "Rest", "emoji": "🛏️", "keywords": ["sleep", "nap", "bed"]},
    {"key": "plane", "label": "Flight", "emoji": "✈️", "keywords": ["travel", "airport", "trip"]},
    {"key": "train-front", "label": "Train", "emoji": "🚆", "keywords": ["commute", "travel", "rail"]},
    {"key": "bus", "label": "Bus", "emoji": "🚌", "keywords": ["commute", "school", "transport"]},
    {"key": "fork-knife", "label": "Meal", "emoji": "🍽️", "keywords": ["dinner", "restaurant", "food"]},
    {"key": "laptop", "label": "Laptop", "emoji": "💻", "keywords": ["computer", "work", "study"]},
    {"key": "notebook-pen", "label": "Notes", "emoji": "📝", "keywords": ["journal", "write", "study"]},
    {"key": "shower-head", "label": "Shower", "emoji": "🚿", "keywords": ["bath", "wash", "clean"]},
    {"key": "sparkles", "label": "Self care", "emoji": "✨", "keywords": ["beauty", "care", "reset"]},
    {"key": "smile", "label": "Good mood", "emoji": "🙂", "keywords": ["happy", "mood", "emotion"]},
    {"key": "frown", "label": "Low mood", "emoji": "☹️", "keywords": ["sad", "mood", "emotion"]},
    {"key": "popcorn", "label": "Movie", "emoji": "🍿", "keywords": ["show", "movie", "fun"]},
    {"key": "gamepad-2", "label": "Gaming", "emoji": "🎮", "keywords": ["game", "play", "hobby"]},
    {"key": "leaf", "label": "Outdoors", "emoji": "🍃", "keywords": ["walk", "nature", "outside"]},
    {"key": "pill-bottle", "label": "Meds", "emoji": "💊", "keywords": ["medicine", "rx", "dose"]},
    {"key": "bike", "label": "Ride", "emoji": "🚴", "keywords": ["bike", "exercise", "commute"]},
    {"key": "tent-tree", "label": "Adventure", "emoji": "🏕️", "keywords": ["camp", "trip", "outdoors"]},
    {"key": "shopping-cart", "label": "Shopping", "emoji": "🛒", "keywords": ["groceries", "store", "errands"]},
    {"key": "wallet", "label": "Money", "emoji": "👛", "keywords": ["spending", "budget", "wallet"]},
    {"key": "banknote", "label": "Cash", "emoji": "💵", "keywords": ["money", "finance", "pay"]},
    {"key": "gift", "label": "Gift", "emoji": "🎁", "keywords": ["present", "birthday", "celebration"]},
    {"key": "camera", "label": "Photo", "emoji": "📷", "keywords": ["picture", "memory", "camera"]},
    {"key": "cooking-pot", "label": "Cooking", "emoji": "🍲", "keywords": ["kitchen", "meal", "cook"]},
    {"key": "scan-heart", "label": "Checkup", "emoji": "🩺", "keywords": ["scan", "health", "medical"]},
    {"key": "hand-heart", "label": "Care", "emoji": "🫶", "keywords": ["support", "care", "love"]},
]
TRACKER_SYMBOL_META = {
    str(symbol["key"]): {
        "label": str(symbol["label"]),
        "emoji": str(symbol["emoji"]),
        "keywords": [str(keyword) for keyword in symbol["keywords"]],
    }
    for symbol in TRACKER_SYMBOLS
}
TRACKER_COLOR_KEYS = ("blue", "amber", "cyan", "pink", "indigo", "rose", "orange", "slate")
DEFAULT_TRACKER_BUTTONS: list[dict[str, object]] = [
    {"id": "bottle", "label": "Bottle", "icon_key": "bottle-wine", "color_key": "blue", "position": 0},
    {"id": "food", "label": "Food", "icon_key": "utensils", "color_key": "amber", "position": 1},
    {"id": "diaper_pee", "label": "Pee", "icon_key": "droplet", "color_key": "cyan", "position": 2},
    {"id": "diaper_poop", "label": "Poop", "icon_key": "toilet", "color_key": "pink", "position": 3},
    {"id": "sleep", "label": "Sleep", "icon_key": "moon", "color_key": "indigo", "position": 4},
    {"id": "breastfeeding", "label": "Nursing", "icon_key": "user-2", "color_key": "rose", "position": 5},
    {"id": "pump", "label": "Pump", "icon_key": "milk", "color_key": "orange", "position": 6},
    {"id": "help", "label": "Other", "icon_key": "help-circle", "color_key": "slate", "position": 7},
]
DEFAULT_TRACKER_BUTTON_IDS = {str(button["id"]) for button in DEFAULT_TRACKER_BUTTONS}

def _prepare_database() -> None:
    if not DATABASE_URL.startswith("sqlite:///"):
        return

    database_path = DATABASE_URL.removeprefix("sqlite:///")
    if not database_path or database_path == ":memory:":
        return

    Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _connect_args() -> dict[str, bool]:
    if DATABASE_URL.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


_prepare_database()
engine = create_engine(DATABASE_URL, connect_args=_connect_args())


class Account(SQLModel, table=True):
    __tablename__ = "account"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True)
    password_hash: str
    password_salt: str
    baby_name: Optional[str] = None
    google_calendar_id: Optional[str] = None
    google_calendar_summary: Optional[str] = None
    service_managed_calendar: bool = False
    calendar_connected_at: Optional[datetime] = None
    calendar_shared_at: Optional[datetime] = None
    google_sync_token: Optional[str] = None
    google_last_synced_at: Optional[datetime] = None
    google_last_sync_status: Optional[str] = None
    tracker_buttons_json: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AccountShareEmail(SQLModel, table=True):
    __tablename__ = "account_share_email"

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(index=True, foreign_key="account.id")
    email: str = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuthSession(SQLModel, table=True):
    __tablename__ = "auth_session"

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(index=True, foreign_key="account.id")
    token_hash: str = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime


class Event(SQLModel, table=True):
    __tablename__ = "event"

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: Optional[int] = Field(default=None, index=True, foreign_key="account.id")
    type: str
    title: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    duration: Optional[int] = None
    details: Optional[str] = None
    is_active: bool = False
    google_description: Optional[str] = None
    calendar_event_id: Optional[str] = None
    calendar_synced_at: Optional[datetime] = None
    google_etag: Optional[str] = None
    google_updated_at: Optional[datetime] = None


class RegisterRequest(SQLModel):
    username: str
    password: str
    baby_name: Optional[str] = None
    share_emails: list[str] = Field(default_factory=list)


class LoginRequest(SQLModel):
    username: str
    password: str


class AccountSettingsUpdate(SQLModel):
    baby_name: Optional[str] = None
    share_emails: Optional[list[str]] = None


class AccountResponse(SQLModel):
    id: int
    username: str
    baby_name: Optional[str]
    share_emails: list[str]
    google_calendar_id: Optional[str]
    google_calendar_summary: Optional[str]
    calendar_connected: bool
    service_managed_calendar: bool
    calendar_url: Optional[str]
    google_last_synced_at: Optional[datetime]
    google_last_sync_status: Optional[str]


class AuthResponse(SQLModel):
    token: str
    account: AccountResponse


class EventCreate(SQLModel):
    type: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration: Optional[int] = None
    details: Optional[str] = None


class EventResponse(SQLModel):
    id: int
    type: str
    title: Optional[str]
    start_time: datetime
    end_time: Optional[datetime]
    duration: Optional[int]
    details: Optional[str]
    is_active: bool


class DayActionResponse(SQLModel):
    target_date: str
    deleted_count: int
    created_count: int = 0
    synced_to_calendar: bool = False


class CalendarSyncResponse(SQLModel):
    imported_count: int
    updated_count: int
    deleted_count: int
    next_sync_token: Optional[str]
    full_sync: bool


class ActivityStart(SQLModel):
    type: str
    details: Optional[str] = None


class ActivityStop(SQLModel):
    type: str


class EventUpdate(SQLModel):
    details: Optional[str] = None


class EventFinalize(SQLModel):
    details: Optional[str] = None


class TrackerButtonConfig(SQLModel):
    id: str
    label: str
    icon_key: str
    color_key: str
    position: int


class TrackerButtonResponse(TrackerButtonConfig):
    emoji: str
    title: str


class TrackerSymbolOption(SQLModel):
    key: str
    label: str
    emoji: str
    keywords: list[str] = Field(default_factory=list)


class TrackerButtonsResponse(SQLModel):
    buttons: list[TrackerButtonResponse]
    available_symbols: list[TrackerSymbolOption]


class TrackerButtonsUpdate(SQLModel):
    buttons: list[TrackerButtonConfig]


class SessionContext(SQLModel):
    account_id: int
    token_hash: str


app = FastAPI(
    title="Baby Tracker API",
    description="API for tracking baby activities",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_calendar_service: Optional[CalendarService] = None


def get_calendar_service() -> CalendarService:
    global _calendar_service
    if _calendar_service is None:
        _calendar_service = CalendarService(CREDENTIALS_PATH, CALENDAR_ID)
    return _calendar_service


def _ensure_column(table_name: str, column_name: str, ddl: str) -> None:
    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()}
        if column_name not in columns:
            connection.execute(text(ddl))


def _ensure_event_columns() -> None:
    _ensure_column("event", "account_id", "ALTER TABLE event ADD COLUMN account_id INTEGER")
    _ensure_column("event", "title", "ALTER TABLE event ADD COLUMN title VARCHAR")
    _ensure_column("event", "is_active", "ALTER TABLE event ADD COLUMN is_active BOOLEAN DEFAULT 0")
    _ensure_column("event", "google_description", "ALTER TABLE event ADD COLUMN google_description VARCHAR")
    _ensure_column("event", "calendar_event_id", "ALTER TABLE event ADD COLUMN calendar_event_id VARCHAR")
    _ensure_column("event", "calendar_synced_at", "ALTER TABLE event ADD COLUMN calendar_synced_at DATETIME")
    _ensure_column("event", "google_etag", "ALTER TABLE event ADD COLUMN google_etag VARCHAR")
    _ensure_column("event", "google_updated_at", "ALTER TABLE event ADD COLUMN google_updated_at DATETIME")


def _ensure_account_columns() -> None:
    _ensure_column("account", "google_sync_token", "ALTER TABLE account ADD COLUMN google_sync_token VARCHAR")
    _ensure_column("account", "google_last_synced_at", "ALTER TABLE account ADD COLUMN google_last_synced_at DATETIME")
    _ensure_column("account", "google_last_sync_status", "ALTER TABLE account ADD COLUMN google_last_sync_status VARCHAR")
    _ensure_column("account", "tracker_buttons_json", "ALTER TABLE account ADD COLUMN tracker_buttons_json TEXT")


def _normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Username is required")
    return normalized


def _normalize_share_emails(emails: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_email in emails:
        email = raw_email.strip().lower()
        if not email:
            continue
        if email in seen:
            continue
        seen.add(email)
        normalized.append(email)
    return normalized


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000)
    return digest.hex()


def _create_password_hash(password: str) -> tuple[str, str]:
    if len(password) < 6:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Password must be at least 6 characters")
    salt = secrets.token_hex(16)
    return _hash_password(password, salt), salt


def _verify_password(password: str, password_hash: str, salt: str) -> bool:
    return secrets.compare_digest(_hash_password(password, salt), password_hash)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ensure_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _to_utc(dt: datetime) -> datetime:
    return _ensure_utc(dt).astimezone(timezone.utc)


def _resolve_time_zone(time_zone_name: Optional[str]):
    if time_zone_name:
        try:
            return ZoneInfo(time_zone_name)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unknown time_zone value",
            ) from exc
    return datetime.now().astimezone().tzinfo or timezone.utc


def _calendar_description(account: Account) -> str:
    return f"Baby Tracker calendar for account {account.id} ({account.username})"


def _calendar_summary(account: Account) -> str:
    label = account.baby_name.strip() if account.baby_name else account.username
    return f"Baby Tracker - {label}"


def _calendar_url(calendar_id: Optional[str]) -> Optional[str]:
    if not calendar_id:
        return None
    return f"https://calendar.google.com/calendar/u/0/r?cid={quote(calendar_id, safe='')}"


def _tracker_symbol_emoji(icon_key: str) -> str:
    return TRACKER_SYMBOL_META.get(icon_key, {}).get("emoji", "🏷️")


def _tracker_button_title(label: str, icon_key: str) -> str:
    cleaned_label = label.strip()
    return f"{_tracker_symbol_emoji(icon_key)} {cleaned_label}" if cleaned_label else _tracker_symbol_emoji(icon_key)


def _tracker_button_response(button: TrackerButtonConfig) -> TrackerButtonResponse:
    return TrackerButtonResponse(
        **button.model_dump(),
        emoji=_tracker_symbol_emoji(button.icon_key),
        title=_tracker_button_title(button.label, button.icon_key),
    )


def _available_tracker_symbols() -> list[TrackerSymbolOption]:
    return [
        TrackerSymbolOption(
            key=str(symbol["key"]),
            label=str(symbol["label"]),
            emoji=str(symbol["emoji"]),
            keywords=[str(keyword) for keyword in symbol["keywords"]],
        )
        for symbol in TRACKER_SYMBOLS
    ]


def _default_tracker_buttons() -> list[TrackerButtonConfig]:
    return [TrackerButtonConfig(**button) for button in DEFAULT_TRACKER_BUTTONS]


def _validate_tracker_buttons(buttons: list[TrackerButtonConfig]) -> list[TrackerButtonConfig]:
    if len(buttons) != TRACKER_BUTTON_COUNT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Exactly {TRACKER_BUTTON_COUNT} tracker buttons are required",
        )

    normalized_buttons: list[TrackerButtonConfig] = []
    seen_ids: set[str] = set()
    for position, button in enumerate(sorted(buttons, key=lambda item: item.position)):
        button_id = normalize_activity_type(button.id)
        if button_id not in DEFAULT_TRACKER_BUTTON_IDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown tracker button id '{button.id}'",
            )
        if button_id in seen_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Duplicate tracker button id '{button.id}'",
            )

        label = button.label.strip()
        if not label:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Button labels are required")
        if len(label) > TRACKER_BUTTON_LABEL_MAX_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Button labels must be {TRACKER_BUTTON_LABEL_MAX_LENGTH} characters or fewer",
            )

        icon_key = button.icon_key.strip()
        if icon_key not in TRACKER_SYMBOL_META:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown tracker symbol '{button.icon_key}'",
            )

        color_key = button.color_key.strip()
        if color_key not in TRACKER_COLOR_KEYS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown tracker color '{button.color_key}'",
            )

        normalized_buttons.append(
            TrackerButtonConfig(
                id=button_id,
                label=label,
                icon_key=icon_key,
                color_key=color_key,
                position=position,
            )
        )
        seen_ids.add(button_id)

    if seen_ids != DEFAULT_TRACKER_BUTTON_IDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tracker button ids must match the editable default set",
        )

    return normalized_buttons


def _store_tracker_buttons(session: Session, account: Account, buttons: list[TrackerButtonConfig]) -> list[TrackerButtonConfig]:
    validated_buttons = _validate_tracker_buttons(buttons)
    account.tracker_buttons_json = json.dumps(
        [button.model_dump() for button in validated_buttons],
        separators=(",", ":"),
    )
    account.updated_at = datetime.now(timezone.utc)
    session.add(account)
    session.commit()
    session.refresh(account)
    return validated_buttons


def _get_tracker_buttons(session: Session, account: Account) -> list[TrackerButtonConfig]:
    if not account.tracker_buttons_json:
        return _store_tracker_buttons(session, account, _default_tracker_buttons())

    try:
        raw_buttons = json.loads(account.tracker_buttons_json)
        parsed_buttons = [TrackerButtonConfig.model_validate(raw_button) for raw_button in raw_buttons]
        return _validate_tracker_buttons(parsed_buttons)
    except (json.JSONDecodeError, TypeError, ValueError, HTTPException):
        return _store_tracker_buttons(session, account, _default_tracker_buttons())


def _tracker_buttons_response(session: Session, account: Account) -> TrackerButtonsResponse:
    buttons = _get_tracker_buttons(session, account)
    return TrackerButtonsResponse(
        buttons=[_tracker_button_response(button) for button in buttons],
        available_symbols=_available_tracker_symbols(),
    )


def _find_tracker_button(buttons: list[TrackerButtonConfig], activity_type: str) -> Optional[TrackerButtonConfig]:
    normalized_type = normalize_activity_type(activity_type)
    return next((button for button in buttons if button.id == normalized_type), None)


def _resolved_event_title(buttons: list[TrackerButtonConfig], activity_type: str) -> str:
    button = _find_tracker_button(buttons, activity_type)
    if button is None:
        return activity_label(activity_type)
    return _tracker_button_title(button.label, button.icon_key)


def _parse_target_date(target_date: Optional[str], local_time_zone) -> date:
    if not target_date:
        return datetime.now(local_time_zone).date()
    try:
        return date.fromisoformat(target_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="target_date must be ISO format YYYY-MM-DD",
        ) from exc


def _replace_share_emails(session: Session, account_id: int, emails: list[str]) -> None:
    existing = session.exec(select(AccountShareEmail).where(AccountShareEmail.account_id == account_id)).all()
    for row in existing:
        session.delete(row)
    for email in _normalize_share_emails(emails):
        session.add(AccountShareEmail(account_id=account_id, email=email))
    session.commit()


def _get_share_emails(session: Session, account_id: int) -> list[str]:
    rows = session.exec(
        select(AccountShareEmail).where(AccountShareEmail.account_id == account_id).order_by(AccountShareEmail.email)
    ).all()
    return [row.email for row in rows]


def _account_response(session: Session, account: Account) -> AccountResponse:
    share_emails = _get_share_emails(session, account.id)
    return AccountResponse(
        id=account.id,
        username=account.username,
        baby_name=account.baby_name,
        share_emails=share_emails,
        google_calendar_id=account.google_calendar_id,
        google_calendar_summary=account.google_calendar_summary,
        calendar_connected=account.google_calendar_id is not None,
        service_managed_calendar=account.service_managed_calendar,
        calendar_url=_calendar_url(account.google_calendar_id),
        google_last_synced_at=_ensure_utc(account.google_last_synced_at) if account.google_last_synced_at else None,
        google_last_sync_status=account.google_last_sync_status,
    )


def _event_response(event: Event) -> EventResponse:
    return EventResponse(
        id=event.id,
        type=event.type,
        title=event.title,
        start_time=_ensure_utc(event.start_time),
        end_time=_ensure_utc(event.end_time) if event.end_time else None,
        duration=event.duration,
        details=event.details,
        is_active=event.is_active,
    )


def _load_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found")
    return account


def _create_auth_session(session: Session, account_id: int) -> str:
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    auth_session = AuthSession(
        account_id=account_id,
        token_hash=_hash_token(raw_token),
        expires_at=now + timedelta(days=SESSION_TTL_DAYS),
        last_used_at=now,
    )
    session.add(auth_session)
    session.commit()
    return raw_token


def _adopt_legacy_events(session: Session, account: Account) -> None:
    account_count = session.exec(select(Account)).all()
    orphaned_events = session.exec(select(Event).where(Event.account_id.is_(None))).all()
    if len(account_count) != 1 or not orphaned_events:
        return

    for event in orphaned_events:
        event.account_id = account.id
        session.add(event)

    if CALENDAR_ID and not account.google_calendar_id:
        account.google_calendar_id = CALENDAR_ID
        account.google_calendar_summary = "Legacy Shared Calendar"
        account.service_managed_calendar = False
        account.calendar_connected_at = datetime.now(timezone.utc)
        session.add(account)

    session.commit()


def require_session(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)) -> SessionContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    token_hash = _hash_token(credentials.credentials)
    with Session(engine) as session:
        auth_session = session.exec(select(AuthSession).where(AuthSession.token_hash == token_hash)).first()
        if not auth_session:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
        if _ensure_utc(auth_session.expires_at) < datetime.now(timezone.utc):
            session.delete(auth_session)
            session.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

        auth_session.last_used_at = datetime.now(timezone.utc)
        session.add(auth_session)
        session.commit()
        return SessionContext(account_id=auth_session.account_id, token_hash=token_hash)


def _sync_event_to_calendar(session: Session, account: Account, event: Event) -> Event:
    if not account.google_calendar_id:
        return event

    service = get_calendar_service()
    if event.calendar_event_id:
        result = service.update_event_from_baby_event(
            event.calendar_event_id,
            event,
            calendar_id=account.google_calendar_id,
        )
    else:
        result = service.create_event_from_baby_event(event, calendar_id=account.google_calendar_id)

    event.calendar_event_id = result["id"]
    _update_event_sync_metadata_from_google(event, result)
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _get_active_event(session: Session, account_id: int, activity_type: str) -> Optional[Event]:
    return session.exec(
        select(Event)
        .where(
            Event.account_id == account_id,
            Event.type == activity_type,
            Event.is_active.is_(True),
        )
        .order_by(Event.start_time.desc())
    ).first()


def _sync_google_calendar_to_db(session: Session, account: Account) -> CalendarSyncResponse:
    if not account.google_calendar_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enable personal calendar sync first")

    response = get_calendar_service().list_event_changes(
        calendar_id=account.google_calendar_id,
        sync_token=account.google_sync_token,
    )
    items = response["items"]
    full_sync = response["full_sync"]

    imported_count = 0
    updated_count = 0
    deleted_count = 0

    local_events = {
        event.calendar_event_id: event
        for event in session.exec(
            select(Event).where(
                Event.account_id == account.id,
                Event.calendar_event_id.is_not(None),
            )
        ).all()
        if event.calendar_event_id
    }
    seen_remote_ids: set[str] = set()

    for google_event in items:
        google_event_id = google_event.get("id")
        if not google_event_id:
            continue

        seen_remote_ids.add(google_event_id)
        existing_event = local_events.get(google_event_id)
        if google_event.get("status") == "cancelled":
            if existing_event:
                session.delete(existing_event)
                deleted_count += 1
            continue

        event = _apply_google_event_to_local(existing_event, google_event, account.id)
        session.add(event)
        if existing_event:
            updated_count += 1
        else:
            imported_count += 1

    if full_sync:
        remote_active_ids = {
            google_event.get("id")
            for google_event in items
            if google_event.get("id") and google_event.get("status") != "cancelled"
        }
        for google_event_id, existing_event in local_events.items():
            if google_event_id not in remote_active_ids:
                session.delete(existing_event)
                deleted_count += 1

    account.google_sync_token = response.get("next_sync_token")
    account.google_last_synced_at = datetime.now(timezone.utc)
    account.google_last_sync_status = "ok"
    account.updated_at = datetime.now(timezone.utc)
    session.add(account)
    session.commit()

    return CalendarSyncResponse(
        imported_count=imported_count,
        updated_count=updated_count,
        deleted_count=deleted_count,
        next_sync_token=account.google_sync_token,
        full_sync=full_sync,
    )


def _date_bounds(target_date: date, local_time_zone) -> tuple[datetime, datetime]:
    start_at_local = datetime.combine(target_date, time.min, tzinfo=local_time_zone)
    end_at_local = start_at_local + timedelta(days=1)
    return start_at_local.astimezone(timezone.utc), end_at_local.astimezone(timezone.utc)


def _delete_events_for_day(session: Session, account: Account, target_date: date, local_time_zone) -> int:
    day_start, day_end = _date_bounds(target_date, local_time_zone)
    events = session.exec(
        select(Event).where(
            Event.account_id == account.id,
            Event.start_time >= day_start,
            Event.start_time < day_end,
        )
    ).all()

    for event in events:
        _delete_event(session, account, event)

    session.commit()
    return len(events)


def _delete_event(session: Session, account: Account, event: Event) -> None:
    if account.google_calendar_id and event.calendar_event_id:
        get_calendar_service().delete_event(event.calendar_event_id, calendar_id=account.google_calendar_id)
    session.delete(event)


def _sample_day_events(target_date: date, local_time_zone, buttons: list[TrackerButtonConfig], seed_value: str) -> list[dict]:
    def at(hour: int, minute: int) -> datetime:
        return datetime.combine(
            target_date,
            time(hour=hour, minute=minute),
            tzinfo=local_time_zone,
        ).astimezone(timezone.utc)

    if not buttons:
        buttons = _default_tracker_buttons()

    rng = random.Random(seed_value)
    start_slots = [
        (0, 30),
        (6, 5),
        (6, 40),
        (8, 0),
        (9, 30),
        (11, 15),
        (12, 5),
        (13, 10),
        (14, 0),
        (17, 45),
        (19, 30),
        (20, 15),
    ]
    day_end = at(23, 59)
    ordered_buttons = sorted(buttons, key=lambda button: button.position)
    sampled_buttons = ordered_buttons + [
        rng.choice(ordered_buttons)
        for _ in range(max(0, len(start_slots) - len(ordered_buttons)))
    ]
    rng.shuffle(sampled_buttons)

    events: list[dict] = []
    for index, (hour, minute) in enumerate(start_slots):
        button = sampled_buttons[index]
        start_time = at(hour, minute)
        next_start_time = at(*start_slots[index + 1]) if index + 1 < len(start_slots) else day_end
        max_duration_seconds = max(5 * 60, int((next_start_time - start_time).total_seconds()) - 5 * 60)
        default_max = 2 * 60 * 60 if button.id == "sleep" else 50 * 60
        duration = rng.randint(5 * 60, min(default_max, max_duration_seconds))
        end_time = min(start_time + timedelta(seconds=duration), day_end)
        duration = int((end_time - start_time).total_seconds())
        events.append(
            {
                "type": button.id,
                "title": _tracker_button_title(button.label, button.icon_key),
                "start_time": start_time,
                "end_time": end_time,
                "duration": duration,
                "details": f"Sample {button.label.lower()} event",
            }
        )

    return events


def _parse_google_datetime(value: Optional[dict]) -> Optional[datetime]:
    if not value:
        return None

    if value.get("dateTime"):
        return _to_utc(datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00")))

    if value.get("date"):
        day = date.fromisoformat(value["date"])
        return datetime.combine(day, time.min, tzinfo=timezone.utc)

    return None


def _extract_details_from_google_description(description: Optional[str]) -> Optional[str]:
    if not description:
        return None

    lines = [line.strip() for line in description.splitlines() if line.strip()]
    note_lines = [line.removeprefix("Notes: ").strip() for line in lines if line.startswith("Notes: ")]
    if note_lines:
        return "\n".join(note_lines) or None

    non_duration_lines = [line for line in lines if not line.startswith("Duration: ")]
    if non_duration_lines:
        return "\n".join(non_duration_lines) or None

    return None


def _apply_google_event_to_local(existing_event: Optional[Event], google_event: dict, account_id: int) -> Event:
    start_time = _parse_google_datetime(google_event.get("start"))
    end_time = _parse_google_datetime(google_event.get("end"))
    if start_time is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Google event missing start time")

    duration = None
    if end_time is not None:
        duration = max(0, int((end_time - start_time).total_seconds()))

    summary = google_event.get("summary")
    inferred_type = infer_activity_type_from_summary(summary, fallback=existing_event.type if existing_event else "help")

    event = existing_event or Event(
        account_id=account_id,
        type=inferred_type,
        title=summary or activity_label(inferred_type),
        start_time=start_time,
    )
    event.account_id = account_id
    event.type = inferred_type
    event.title = summary or activity_label(inferred_type)
    event.start_time = start_time
    event.end_time = end_time
    event.duration = duration
    event.details = _extract_details_from_google_description(google_event.get("description"))
    event.google_description = google_event.get("description")
    event.calendar_event_id = google_event.get("id")
    event.google_etag = google_event.get("etag")
    updated = google_event.get("updated")
    event.google_updated_at = (
        _to_utc(datetime.fromisoformat(updated.replace("Z", "+00:00")))
        if updated
        else event.google_updated_at
    )
    event.calendar_synced_at = datetime.now(timezone.utc)
    return event


def _update_event_sync_metadata_from_google(event: Event, google_event: dict) -> Event:
    event.title = google_event.get("summary") or event.title or activity_label(event.type)
    event.google_description = google_event.get("description")
    event.google_etag = google_event.get("etag")
    updated = google_event.get("updated")
    if updated:
        event.google_updated_at = _to_utc(datetime.fromisoformat(updated.replace("Z", "+00:00")))
    event.calendar_synced_at = datetime.now(timezone.utc)
    return event


def _frontend_dist_dir() -> Optional[Path]:
    configured_dist_path = os.environ.get("FRONTEND_DIST_PATH", FRONTEND_DIST_PATH or "")
    if not configured_dist_path:
        return None

    dist_dir = Path(configured_dist_path).expanduser().resolve()
    if dist_dir.is_dir():
        return dist_dir
    return None


def _frontend_file_response(relative_path: str) -> Optional[FileResponse]:
    dist_dir = _frontend_dist_dir()
    if dist_dir is None:
        return None

    candidate = (dist_dir / relative_path).resolve()
    try:
        candidate.relative_to(dist_dir)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found") from exc

    if candidate.is_file():
        return FileResponse(candidate)
    return None


SQLModel.metadata.create_all(engine)
_ensure_account_columns()
_ensure_event_columns()


@app.get("/health")
def read_health():
    return {"message": "Baby Tracker API is running"}


@app.get("/")
def read_root():
    return _frontend_file_response("index.html") or {"message": "Baby Tracker API is running"}


@app.post("/auth/register", response_model=AuthResponse)
def register(payload: RegisterRequest):
    with Session(engine) as session:
        username = _normalize_username(payload.username)
        existing = session.exec(select(Account).where(Account.username == username)).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

        password_hash, password_salt = _create_password_hash(payload.password)
        account = Account(
            username=username,
            password_hash=password_hash,
            password_salt=password_salt,
            baby_name=payload.baby_name.strip() if payload.baby_name else None,
        )
        session.add(account)
        session.commit()
        session.refresh(account)

        _replace_share_emails(session, account.id, payload.share_emails)
        _adopt_legacy_events(session, account)
        session.refresh(account)

        token = _create_auth_session(session, account.id)
        return AuthResponse(token=token, account=_account_response(session, account))


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest):
    with Session(engine) as session:
        username = _normalize_username(payload.username)
        account = session.exec(select(Account).where(Account.username == username)).first()
        if not account or not _verify_password(payload.password, account.password_hash, account.password_salt):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

        token = _create_auth_session(session, account.id)
        return AuthResponse(token=token, account=_account_response(session, account))


@app.get("/auth/me", response_model=AccountResponse)
def me(session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        return _account_response(session, account)


@app.post("/auth/logout")
def logout(session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        auth_session = session.exec(select(AuthSession).where(AuthSession.token_hash == session_context.token_hash)).first()
        if auth_session:
            session.delete(auth_session)
            session.commit()
    return {"status": "success"}


@app.get("/account/settings", response_model=AccountResponse)
def get_account_settings(session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        return _account_response(session, account)


@app.patch("/account/settings", response_model=AccountResponse)
def update_account_settings(payload: AccountSettingsUpdate, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        baby_name_changed = payload.baby_name is not None and (payload.baby_name.strip() or None) != account.baby_name

        if payload.baby_name is not None:
            account.baby_name = payload.baby_name.strip() or None
        account.updated_at = datetime.now(timezone.utc)
        session.add(account)
        session.commit()
        session.refresh(account)

        if payload.share_emails is not None:
            _replace_share_emails(session, account.id, payload.share_emails)
            session.refresh(account)

        if baby_name_changed and account.google_calendar_id and account.service_managed_calendar:
            calendar = get_calendar_service().update_calendar_metadata(
                calendar_id=account.google_calendar_id,
                summary=_calendar_summary(account),
                description=_calendar_description(account),
            )
            account.google_calendar_summary = calendar.get("summary", account.google_calendar_summary)
            account.updated_at = datetime.now(timezone.utc)
            session.add(account)
            session.commit()
            session.refresh(account)

        return _account_response(session, account)


@app.get("/tracker-buttons", response_model=TrackerButtonsResponse)
def get_tracker_buttons(session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        return _tracker_buttons_response(session, account)


@app.patch("/tracker-buttons", response_model=TrackerButtonsResponse)
def update_tracker_buttons(payload: TrackerButtonsUpdate, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        _store_tracker_buttons(session, account, payload.buttons)
        return _tracker_buttons_response(session, account)


@app.post("/calendar/enable-sync", response_model=AccountResponse)
def enable_calendar_sync(session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        share_emails = _get_share_emails(session, account.id)

        if account.google_calendar_id and account.service_managed_calendar:
            for email in share_emails:
                get_calendar_service().share_calendar(account.google_calendar_id, email)
            if share_emails:
                account.calendar_shared_at = datetime.now(timezone.utc)
                session.add(account)
                session.commit()
                session.refresh(account)
            return _account_response(session, account)

        calendar = get_calendar_service().create_calendar(
            summary=_calendar_summary(account),
            description=_calendar_description(account),
        )
        account.google_calendar_id = calendar["id"]
        account.google_calendar_summary = calendar.get("summary") or _calendar_summary(account)
        account.service_managed_calendar = True
        account.calendar_connected_at = datetime.now(timezone.utc)
        account.google_sync_token = None
        account.google_last_synced_at = None
        account.google_last_sync_status = None

        for email in share_emails:
            get_calendar_service().share_calendar(account.google_calendar_id, email)
        if share_emails:
            account.calendar_shared_at = datetime.now(timezone.utc)

        account.updated_at = datetime.now(timezone.utc)
        session.add(account)
        session.commit()
        session.refresh(account)
        return _account_response(session, account)


@app.post("/calendar/reshare", response_model=AccountResponse)
def reshare_calendar(session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        if not account.google_calendar_id or not account.service_managed_calendar:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enable personal calendar sync first")

        share_emails = _get_share_emails(session, account.id)
        if not share_emails:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No share emails configured")

        for email in share_emails:
            get_calendar_service().share_calendar(account.google_calendar_id, email)

        account.calendar_shared_at = datetime.now(timezone.utc)
        account.updated_at = datetime.now(timezone.utc)
        session.add(account)
        session.commit()
        session.refresh(account)
        return _account_response(session, account)


@app.post("/calendar/sync", response_model=CalendarSyncResponse)
def sync_calendar_changes(session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        try:
            return _sync_google_calendar_to_db(session, account)
        except Exception:
            account.google_last_sync_status = "error"
            account.updated_at = datetime.now(timezone.utc)
            session.add(account)
            session.commit()
            raise


@app.post("/events", response_model=EventResponse)
def create_event_endpoint(event: EventCreate, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        tracker_buttons = _get_tracker_buttons(session, account)
        activity_type = normalize_activity_type(event.type)
        db_event = Event(
            account_id=account.id,
            type=activity_type,
            title=_resolved_event_title(tracker_buttons, activity_type),
            start_time=_to_utc(event.start_time),
            end_time=_to_utc(event.end_time) if event.end_time is not None else None,
            duration=event.duration,
            details=event.details,
            is_active=False,
        )
        session.add(db_event)
        session.commit()
        session.refresh(db_event)
        return _event_response(db_event)


@app.get("/events", response_model=list[EventResponse])
def list_events_endpoint(session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        events = session.exec(
            select(Event).where(Event.account_id == account.id).order_by(Event.start_time.desc())
        ).all()
        return [_event_response(event) for event in events]


@app.delete("/events/day", response_model=DayActionResponse)
def delete_events_for_day_endpoint(
    target_date: Optional[str] = None,
    time_zone: Optional[str] = None,
    session_context: SessionContext = Depends(require_session),
):
    local_time_zone = _resolve_time_zone(time_zone)
    parsed_date = _parse_target_date(target_date, local_time_zone)
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        deleted_count = _delete_events_for_day(session, account, parsed_date, local_time_zone)
        return DayActionResponse(
            target_date=parsed_date.isoformat(),
            deleted_count=deleted_count,
            synced_to_calendar=account.google_calendar_id is not None,
        )


@app.delete("/events/{event_id}")
def delete_event_endpoint(event_id: int, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        event = session.exec(
            select(Event).where(Event.id == event_id, Event.account_id == account.id)
        ).first()
        if not event:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

        _delete_event(session, account, event)
        session.commit()
        return {"status": "success"}


@app.post("/events/simulate-day", response_model=DayActionResponse)
def simulate_day_endpoint(
    target_date: Optional[str] = None,
    time_zone: Optional[str] = None,
    session_context: SessionContext = Depends(require_session),
):
    local_time_zone = _resolve_time_zone(time_zone)
    parsed_date = _parse_target_date(target_date, local_time_zone)
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        if not account.google_calendar_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Enable calendar sync before simulating a day",
            )

        deleted_count = _delete_events_for_day(session, account, parsed_date, local_time_zone)
        created_count = 0
        tracker_buttons = _get_tracker_buttons(session, account)
        for payload in _sample_day_events(
            parsed_date,
            local_time_zone,
            tracker_buttons,
            seed_value=f"{account.id}:{parsed_date.isoformat()}",
        ):
            event = Event(account_id=account.id, **payload)
            session.add(event)
            session.commit()
            session.refresh(event)
            _sync_event_to_calendar(session, account, event)
            created_count += 1

        return DayActionResponse(
            target_date=parsed_date.isoformat(),
            deleted_count=deleted_count,
            created_count=created_count,
            synced_to_calendar=True,
        )


@app.post("/activities/start")
def start_activity_endpoint(activity: ActivityStart, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        tracker_buttons = _get_tracker_buttons(session, account)
        activity_type = normalize_activity_type(activity.type)
        if _get_active_event(session, account.id, activity_type):
            return {"status": "error", "message": f"Activity '{activity_type}' is already running"}

        db_event = Event(
            account_id=account.id,
            type=activity_type,
            title=_resolved_event_title(tracker_buttons, activity_type),
            start_time=datetime.now(timezone.utc),
            details=activity.details.strip() if activity.details else None,
            is_active=True,
        )
        session.add(db_event)
        session.commit()
        session.refresh(db_event)
        start_time = _ensure_utc(db_event.start_time)
        return {
            "status": "success",
            "message": f"Started tracking '{activity_type}'",
            "event_id": db_event.id,
            "start_time": start_time,
        }


@app.post("/activities/stop")
def stop_activity_endpoint(activity: ActivityStop, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        activity_type = normalize_activity_type(activity.type)
        db_event = _get_active_event(session, account.id, activity_type)
        if not db_event:
            return {"status": "error", "message": f"No active timer for '{activity_type}'"}

        start_time = _ensure_utc(db_event.start_time)
        db_event.start_time = start_time
        end_time = datetime.now(timezone.utc)
        duration = int((end_time - start_time).total_seconds())
        db_event.end_time = end_time
        db_event.duration = duration
        db_event.is_active = False
        session.add(db_event)
        session.commit()
        session.refresh(db_event)
        if account.google_calendar_id:
            db_event = _sync_event_to_calendar(session, account, db_event)
        return {
            "status": "success",
            "message": f"Stopped tracking '{activity_type}'",
            "event_id": db_event.id,
            "start_time": start_time,
            "end_time": _ensure_utc(end_time),
            "duration_seconds": duration,
        }


@app.patch("/events/{event_id}", response_model=EventResponse)
def update_event_endpoint(event_id: int, event_update: EventUpdate, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        event = session.exec(
            select(Event).where(Event.id == event_id, Event.account_id == account.id)
        ).first()
        if not event:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

        event.details = event_update.details.strip() if event_update.details else None
        session.add(event)
        session.commit()
        session.refresh(event)
        if event.calendar_event_id:
            event = _sync_event_to_calendar(session, account, event)
        return _event_response(event)


@app.post("/events/{event_id}/finalize", response_model=EventResponse)
def finalize_event_endpoint(event_id: int, event_finalize: EventFinalize, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        event = session.exec(
            select(Event).where(Event.id == event_id, Event.account_id == account.id)
        ).first()
        if not event:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

        if event_finalize.details is not None:
            event.details = event_finalize.details.strip() or None
            session.add(event)
            session.commit()
            session.refresh(event)

        if not event.is_active:
            event = _sync_event_to_calendar(session, account, event)
        return _event_response(event)


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    file_response = _frontend_file_response(full_path)
    if file_response is not None:
        return file_response

    index_response = _frontend_file_response("index.html")
    if index_response is not None:
        return index_response

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=APP_HOST, port=APP_PORT)
