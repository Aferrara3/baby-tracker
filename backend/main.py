import hashlib
import json
import logging
import os
import random
import threading
import unicodedata
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, File, Form, HTTPException, Security, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from googleapiclient.errors import HttpError
from sqlalchemy import text
from sqlmodel import Field, SQLModel, Session, create_engine, select

from app_profile import (
    MAX_TRACKER_BUTTON_PAGES,
    TRACKER_BUTTONS_PER_PAGE,
    get_app_profile,
    get_profile_symbol_meta,
    get_profile_symbols,
    get_seed_tracker_buttons,
    get_tracker_button_templates,
    public_app_config,
)
from calendar_service import (
    CalendarService,
    activity_label,
    infer_activity_type_from_summary,
    normalize_activity_type,
)
from config import (
    APP_HOST,
    APP_PORT,
    APP_PROFILE_CONFIG_PATH,
    CALENDAR_ID,
    CORS_ALLOWED_ORIGINS,
    CREDENTIALS_PATH,
    CUSTOM_ICON_STORAGE_DIR,
    DATABASE_URL,
    FORCE_GCAL_QUEUE_RETRY_TEST,
    FRONTEND_DIST_PATH,
    SESSION_TTL_DAYS,
)

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)

TRACKER_BUTTON_LABEL_MAX_LENGTH = 24
DEFAULT_COLOR_PALETTE = "default"
COLOR_PALETTE_KEYS = ("default", "blossom", "meadow", "twilight")
CALENDAR_SYNC_ACTIVE_JOB_STATUSES = ("pending", "retrying", "processing")
CALENDAR_SYNC_QUEUE_POLL_INTERVAL_SECONDS = 30
CALENDAR_SYNC_BASE_RETRY_SECONDS = 30
CALENDAR_SYNC_MAX_RETRY_SECONDS = 60 * 60
CALENDAR_SYNC_MAX_BATCH_SIZE = 10

TRACKER_COLOR_KEYS = ("blue", "amber", "cyan", "pink", "indigo", "rose", "orange", "slate")

def _prepare_database() -> None:
    if not DATABASE_URL.startswith("sqlite:///"):
        return

    database_path = DATABASE_URL.removeprefix("sqlite:///")
    if not database_path or database_path == ":memory:":
        return

    Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _prepare_custom_icon_storage() -> None:
    CUSTOM_ICON_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def _connect_args() -> dict[str, bool]:
    if DATABASE_URL.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


_prepare_database()
_prepare_custom_icon_storage()
engine = create_engine(DATABASE_URL, connect_args=_connect_args())


class Account(SQLModel, table=True):
    __tablename__ = "account"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True)
    password_hash: str
    password_salt: str
    baby_name: Optional[str] = None
    color_palette: str = DEFAULT_COLOR_PALETTE
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
    deleted_at: Optional[datetime] = None
    calendar_sync_status: Optional[str] = None
    calendar_sync_error: Optional[str] = None
    calendar_sync_queued_at: Optional[datetime] = None


class CalendarSyncJob(SQLModel, table=True):
    __tablename__ = "calendar_sync_job"

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(index=True, foreign_key="account.id")
    event_id: Optional[int] = Field(default=None, index=True, foreign_key="event.id")
    operation: str
    status: str = "pending"
    payload_json: Optional[str] = None
    attempt_count: int = 0
    last_error: Optional[str] = None
    next_attempt_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None


class CustomIcon(SQLModel, table=True):
    __tablename__ = "custom_icon"

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(index=True, foreign_key="account.id")
    label: str
    emoji: str
    keywords_json: Optional[str] = None
    asset_filename: str
    asset_token: str = Field(index=True)
    is_public: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
    color_palette: Optional[str] = None
    share_emails: Optional[list[str]] = None


class AccountResponse(SQLModel):
    id: int
    username: str
    baby_name: Optional[str]
    color_palette: str
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
    calendar_sync_state: str
    calendar_sync_message: Optional[str] = None


class DayActionResponse(SQLModel):
    target_date: str
    deleted_count: int
    created_count: int = 0
    synced_to_calendar: bool = False
    calendar_sync_state: Optional[str] = None


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
    emoji_override: Optional[str] = None


class TrackerButtonResponse(TrackerButtonConfig):
    emoji: str
    title: str
    icon_kind: str = "lucide"
    image_url: Optional[str] = None


class TrackerSymbolOption(SQLModel):
    key: str
    label: str
    emoji: str
    keywords: list[str] = Field(default_factory=list)
    category: Optional[str] = None
    icon_kind: str = "lucide"
    image_url: Optional[str] = None
    is_public: Optional[bool] = None
    can_delete: Optional[bool] = None


class TrackerButtonsResponse(SQLModel):
    buttons: list[TrackerButtonResponse]
    available_symbols: list[TrackerSymbolOption]


class TrackerButtonsUpdate(SQLModel):
    buttons: list[TrackerButtonConfig]


class AppCopyResponse(SQLModel):
    auth_badge_label: str
    auth_heading: str
    auth_subheading: str
    create_account_label: str
    register_name_placeholder: str
    settings_name_label: str
    settings_name_placeholder: str
    enable_sync_name_help: str
    header_context_with_name: str
    header_context_without_name: str


class AppConfigResponse(SQLModel):
    model_config = {"populate_by_name": True}

    profile_id: str
    app_name: str
    copy_text: AppCopyResponse = Field(alias="copy")
    available_symbols: list[TrackerSymbolOption]
    button_templates: list[TrackerButtonResponse]
    tracker_buttons_per_page: int
    max_tracker_button_pages: int
    placeholder_button_label_prefix: str


class SessionContext(SQLModel):
    account_id: int
    token_hash: str


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    _start_calendar_sync_worker()
    try:
        yield
    finally:
        _stop_calendar_sync_worker()


app = FastAPI(
    title=get_app_profile().api_title,
    description=f"API for {get_app_profile().app_name.lower()}",
    version="1.0.0",
    lifespan=_app_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_calendar_service: Optional[CalendarService] = None
_calendar_sync_worker_enabled = os.environ.get("DISABLE_CALENDAR_SYNC_WORKER") != "1"
_calendar_sync_stop_event = threading.Event()
_calendar_sync_wakeup = threading.Event()
_calendar_sync_worker_thread: Optional[threading.Thread] = None


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
    _ensure_column("event", "deleted_at", "ALTER TABLE event ADD COLUMN deleted_at DATETIME")
    _ensure_column("event", "calendar_sync_status", "ALTER TABLE event ADD COLUMN calendar_sync_status VARCHAR")
    _ensure_column("event", "calendar_sync_error", "ALTER TABLE event ADD COLUMN calendar_sync_error VARCHAR")
    _ensure_column("event", "calendar_sync_queued_at", "ALTER TABLE event ADD COLUMN calendar_sync_queued_at DATETIME")


def _ensure_account_columns() -> None:
    _ensure_column("account", "color_palette", f"ALTER TABLE account ADD COLUMN color_palette VARCHAR DEFAULT '{DEFAULT_COLOR_PALETTE}'")
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


def _normalize_color_palette(value: Optional[str]) -> str:
    palette = (value or DEFAULT_COLOR_PALETTE).strip().lower()
    if palette not in COLOR_PALETTE_KEYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown color palette '{value}'",
        )
    return palette


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
    return get_app_profile().calendar_description_template.format(
        account_id=account.id,
        username=account.username,
    )


def _calendar_summary(account: Account) -> str:
    label = account.baby_name.strip() if account.baby_name else account.username
    return f"{get_app_profile().calendar_summary_prefix} - {label}"


def _calendar_url(calendar_id: Optional[str]) -> Optional[str]:
    if not calendar_id:
        return None
    return f"https://calendar.google.com/calendar/u/0/r?cid={quote(calendar_id, safe='')}"


def _custom_icon_key(custom_icon_id: int) -> str:
    return f"custom:{custom_icon_id}"


def _parse_custom_icon_id(icon_key: str) -> Optional[int]:
    prefix = "custom:"
    if not icon_key.startswith(prefix):
        return None
    try:
        return int(icon_key.removeprefix(prefix))
    except ValueError:
        return None


def _custom_icon_asset_url(custom_icon: CustomIcon) -> str:
    return f"/custom-icons/assets/{custom_icon.asset_token}"


def _custom_icon_keywords(custom_icon: CustomIcon) -> list[str]:
    if not custom_icon.keywords_json:
        return []
    try:
        payload = json.loads(custom_icon.keywords_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item).strip() for item in payload if str(item).strip()]


def _custom_icon_symbol_option(custom_icon: CustomIcon, can_delete: bool = False) -> TrackerSymbolOption:
    return TrackerSymbolOption(
        key=_custom_icon_key(custom_icon.id or 0),
        label=custom_icon.label,
        emoji=custom_icon.emoji,
        keywords=_custom_icon_keywords(custom_icon),
        category="custom",
        icon_kind="custom",
        image_url=_custom_icon_asset_url(custom_icon),
        is_public=custom_icon.is_public,
        can_delete=can_delete,
    )


def _all_tracker_symbols(session: Session, account: Optional[Account] = None) -> list[TrackerSymbolOption]:
    symbols = [
        TrackerSymbolOption(
            key=str(symbol["key"]),
            label=str(symbol["label"]),
            emoji=str(symbol["emoji"]),
            keywords=[str(keyword) for keyword in symbol["keywords"]],
            category=str(symbol.get("category", "general")) if symbol.get("category") is not None else None,
            icon_kind=str(symbol.get("icon_kind", "lucide")),
        )
        for symbol in get_profile_symbols()
    ]
    if account is None or account.id is None:
        return symbols

    custom_icons = session.exec(
        select(CustomIcon)
        .where((CustomIcon.account_id == account.id) | (CustomIcon.is_public.is_(True)))
        .order_by(CustomIcon.is_public.desc(), CustomIcon.label.asc())
    ).all()
    symbols.extend(
        _custom_icon_symbol_option(
            custom_icon,
            can_delete=bool(account.id is not None and custom_icon.account_id == account.id),
        )
        for custom_icon in custom_icons
        if custom_icon.id is not None
    )
    return symbols


def _tracker_symbol_meta(symbols: list[TrackerSymbolOption]) -> dict[str, dict[str, object]]:
    return {
        symbol.key: {
            "label": symbol.label,
            "emoji": symbol.emoji,
            "keywords": list(symbol.keywords),
            "category": symbol.category,
            "icon_kind": symbol.icon_kind,
            "image_url": symbol.image_url,
            "is_public": symbol.is_public,
            "can_delete": symbol.can_delete,
        }
        for symbol in symbols
    }


def _is_valid_emoji_value(value: str) -> bool:
    normalized = value.strip()
    if not normalized or len(normalized) > 16:
        return False

    has_emoji = False
    for char in normalized:
        codepoint = ord(char)
        if codepoint in {0x200D, 0xFE0F, 0xFE0E, 0x20E3}:
            continue
        if 0x1F1E6 <= codepoint <= 0x1F1FF:
            has_emoji = True
            continue
        if unicodedata.category(char) == "So" or 0x2600 <= codepoint <= 0x27BF:
            has_emoji = True
            continue
        return False
    return has_emoji


def _normalize_emoji_value(value: str, field_label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_label} is required",
        )
    if not _is_valid_emoji_value(normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_label} must be a valid emoji",
        )
    return normalized


def _normalize_optional_emoji_value(value: Optional[str], field_label: str) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return _normalize_emoji_value(normalized, field_label)


def _tracker_symbol_emoji(
    icon_key: str,
    symbol_meta: Optional[dict[str, dict[str, object]]] = None,
    emoji_override: Optional[str] = None,
) -> str:
    if emoji_override:
        return emoji_override
    lookup = symbol_meta or get_profile_symbol_meta()
    return str(lookup.get(icon_key, {}).get("emoji", get_app_profile().unknown_activity_emoji))


def _normalize_custom_icon_label(label: str) -> str:
    normalized = label.strip()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Custom icon label is required")
    if len(normalized) > 64:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Custom icon label must be 64 characters or fewer",
        )
    return normalized


def _normalize_custom_icon_emoji(emoji: str) -> str:
    return _normalize_emoji_value(emoji, "Custom icon emoji")


def _normalize_custom_icon_keywords(raw_keywords: Optional[str]) -> list[str]:
    if raw_keywords is None:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for piece in raw_keywords.replace("\n", ",").split(","):
        keyword = piece.strip().lower()
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        normalized.append(keyword)
    return normalized[:24]


def _is_truthy_form_value(value: Optional[str]) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _custom_icon_extension(upload: UploadFile) -> str:
    content_type = (upload.content_type or "").lower()
    suffix = Path(upload.filename or "").suffix.lower()
    if content_type == "image/png" or suffix == ".png":
        return ".png"
    if content_type == "image/svg+xml" or suffix == ".svg":
        return ".svg"
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Custom icons must be uploaded as PNG or SVG",
    )


def _write_custom_icon_asset(upload: UploadFile) -> tuple[str, str]:
    extension = _custom_icon_extension(upload)
    asset_token = secrets.token_urlsafe(24)
    asset_filename = f"{asset_token}{extension}"
    asset_path = CUSTOM_ICON_STORAGE_DIR / asset_filename
    payload = upload.file.read()
    if len(payload) > 2 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Custom icon files must be 2MB or smaller",
        )
    asset_path.write_bytes(payload)
    return asset_token, asset_filename


def _tracker_button_title(
    label: str,
    icon_key: str,
    symbol_meta: Optional[dict[str, dict[str, object]]] = None,
    emoji_override: Optional[str] = None,
) -> str:
    cleaned_label = label.strip()
    resolved_emoji = _tracker_symbol_emoji(icon_key, symbol_meta, emoji_override)
    return f"{resolved_emoji} {cleaned_label}" if cleaned_label else resolved_emoji


def _tracker_button_response(button: TrackerButtonConfig, symbol_meta: Optional[dict[str, dict[str, object]]] = None) -> TrackerButtonResponse:
    resolved_meta = symbol_meta or get_profile_symbol_meta()
    symbol = resolved_meta.get(button.icon_key, {})
    return TrackerButtonResponse(
        **button.model_dump(),
        emoji=_tracker_symbol_emoji(button.icon_key, resolved_meta, button.emoji_override),
        title=_tracker_button_title(button.label, button.icon_key, resolved_meta, button.emoji_override),
        icon_kind=str(symbol.get("icon_kind", "lucide")),
        image_url=str(symbol["image_url"]) if symbol.get("image_url") else None,
    )


def _available_tracker_symbols() -> list[TrackerSymbolOption]:
    with Session(engine) as session:
        return _all_tracker_symbols(session)


def _default_tracker_buttons() -> list[TrackerButtonConfig]:
    return [TrackerButtonConfig.model_validate(button) for button in get_seed_tracker_buttons()]


def _validate_tracker_buttons(
    buttons: list[TrackerButtonConfig],
    symbol_meta: dict[str, dict[str, object]],
    *,
    allow_unknown_icon_fallback: bool = False,
) -> list[TrackerButtonConfig]:
    if len(buttons) < TRACKER_BUTTONS_PER_PAGE or len(buttons) % TRACKER_BUTTONS_PER_PAGE != 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Tracker buttons must be saved in full pages of {TRACKER_BUTTONS_PER_PAGE}",
        )
    if len(buttons) > TRACKER_BUTTONS_PER_PAGE * MAX_TRACKER_BUTTON_PAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Tracker buttons are limited to {MAX_TRACKER_BUTTON_PAGES} pages",
        )

    normalized_buttons: list[TrackerButtonConfig] = []
    seen_ids: set[str] = set()
    for position, button in enumerate(sorted(buttons, key=lambda item: item.position)):
        button_id = normalize_activity_type(button.id.strip())
        if not button_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Tracker button ids are required")
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
        if icon_key not in symbol_meta:
            if allow_unknown_icon_fallback:
                icon_key = "help-circle" if "help-circle" in symbol_meta else next(iter(symbol_meta.keys()))
            else:
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

        emoji_override = _normalize_optional_emoji_value(button.emoji_override, "Button emoji override")

        normalized_buttons.append(
            TrackerButtonConfig(
                id=button_id,
                label=label,
                icon_key=icon_key,
                color_key=color_key,
                position=position,
                emoji_override=emoji_override,
            )
        )
        seen_ids.add(button_id)

    return normalized_buttons


def _store_tracker_buttons(session: Session, account: Account, buttons: list[TrackerButtonConfig]) -> list[TrackerButtonConfig]:
    validated_buttons = _validate_tracker_buttons(buttons, _tracker_symbol_meta(_all_tracker_symbols(session, account)))
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
        return _validate_tracker_buttons(
            parsed_buttons,
            _tracker_symbol_meta(_all_tracker_symbols(session, account)),
            allow_unknown_icon_fallback=True,
        )
    except (json.JSONDecodeError, TypeError, ValueError, HTTPException):
        return _store_tracker_buttons(session, account, _default_tracker_buttons())


def _tracker_buttons_response(session: Session, account: Account) -> TrackerButtonsResponse:
    buttons = _get_tracker_buttons(session, account)
    symbols = _all_tracker_symbols(session, account)
    symbol_meta = _tracker_symbol_meta(symbols)
    return TrackerButtonsResponse(
        buttons=[_tracker_button_response(button, symbol_meta) for button in buttons],
        available_symbols=symbols,
    )


def _find_tracker_button(buttons: list[TrackerButtonConfig], activity_type: str) -> Optional[TrackerButtonConfig]:
    normalized_type = normalize_activity_type(activity_type)
    return next((button for button in buttons if button.id == normalized_type), None)


def _resolved_event_title(
    buttons: list[TrackerButtonConfig],
    activity_type: str,
    symbol_meta: Optional[dict[str, dict[str, object]]] = None,
) -> str:
    button = _find_tracker_button(buttons, activity_type)
    if button is None:
        return activity_label(activity_type)
    return _tracker_button_title(button.label, button.icon_key, symbol_meta, button.emoji_override)


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
        color_palette=_normalize_color_palette(account.color_palette),
        share_emails=share_emails,
        google_calendar_id=account.google_calendar_id,
        google_calendar_summary=account.google_calendar_summary,
        calendar_connected=account.google_calendar_id is not None,
        service_managed_calendar=account.service_managed_calendar,
        calendar_url=_calendar_url(account.google_calendar_id),
        google_last_synced_at=_ensure_utc(account.google_last_synced_at) if account.google_last_synced_at else None,
        google_last_sync_status=account.google_last_sync_status,
    )


def _event_sync_state(account: Account, event: Event) -> str:
    if event.calendar_sync_status:
        return event.calendar_sync_status
    if not account.google_calendar_id:
        return "local_only"
    if event.is_active:
        return "pending"
    if event.calendar_event_id:
        return "synced"
    return "pending"


def _event_sync_message(sync_state: str, event: Event) -> Optional[str]:
    if sync_state == "local_only":
        return "Saved locally. Enable calendar sync in Settings when ready."
    if sync_state == "queued":
        if event.calendar_sync_error:
            return "GCal update failed. Will auto-retry in background."
        return None
    if sync_state == "failed":
        return "Saved locally, but Google Calendar needs attention."
    return None


def _event_response(event: Event, account: Account) -> EventResponse:
    sync_state = _event_sync_state(account, event)
    return EventResponse(
        id=event.id,
        type=event.type,
        title=event.title,
        start_time=_ensure_utc(event.start_time),
        end_time=_ensure_utc(event.end_time) if event.end_time else None,
        duration=event.duration,
        details=event.details,
        is_active=event.is_active,
        calendar_sync_state=sync_state,
        calendar_sync_message=_event_sync_message(sync_state, event),
    )


def _load_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found")
    return account


def _app_running_message() -> str:
    return f"{get_app_profile().app_name} API is running"


def _mark_event_local_only(event: Event) -> Event:
    event.calendar_sync_status = "local_only"
    event.calendar_sync_error = None
    event.calendar_sync_queued_at = None
    return event


def _mark_event_sync_pending(event: Event) -> Event:
    event.calendar_sync_status = "pending"
    event.calendar_sync_error = None
    event.calendar_sync_queued_at = None
    return event


def _mark_event_sync_queued(event: Event, error: Optional[str] = None) -> Event:
    event.calendar_sync_status = "queued"
    event.calendar_sync_error = error
    event.calendar_sync_queued_at = datetime.now(timezone.utc)
    return event


def _mark_event_synced(event: Event) -> Event:
    event.calendar_sync_status = "synced"
    event.calendar_sync_error = None
    event.calendar_sync_queued_at = None
    return event


def _mark_event_sync_failed(event: Event, error: str) -> Event:
    event.calendar_sync_status = "failed"
    event.calendar_sync_error = error
    event.calendar_sync_queued_at = None
    return event


def _serialize_sync_job_payload(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True)


def _deserialize_sync_job_payload(job: CalendarSyncJob) -> dict:
    if not job.payload_json:
        return {}
    return json.loads(job.payload_json)


def _calendar_sync_error_message(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def _maybe_raise_forced_calendar_sync_failure() -> None:
    if not FORCE_GCAL_QUEUE_RETRY_TEST:
        return
    raise OSError("Forced Google Calendar retry test")


def _is_retryable_calendar_error(exc: Exception) -> bool:
    if isinstance(exc, HttpError):
        status_code = getattr(exc.resp, "status", None)
        return status_code in {408, 429} or (status_code is not None and status_code >= 500)
    return isinstance(exc, (ConnectionError, OSError, TimeoutError))


def _calendar_sync_retry_delay_seconds(attempt_count: int) -> int:
    base_delay = min(CALENDAR_SYNC_MAX_RETRY_SECONDS, CALENDAR_SYNC_BASE_RETRY_SECONDS * (2 ** max(0, attempt_count - 1)))
    jitter = random.randint(0, min(30, max(1, base_delay // 4)))
    return min(CALENDAR_SYNC_MAX_RETRY_SECONDS, base_delay + jitter)


def _pending_sync_jobs_by_event_id(session: Session, account_id: int) -> dict[int, CalendarSyncJob]:
    jobs = session.exec(
        select(CalendarSyncJob)
        .where(
            CalendarSyncJob.account_id == account_id,
            CalendarSyncJob.event_id.is_not(None),
            CalendarSyncJob.status.in_(CALENDAR_SYNC_ACTIVE_JOB_STATUSES),
        )
        .order_by(CalendarSyncJob.created_at.desc())
    ).all()
    return {job.event_id: job for job in jobs if job.event_id is not None}


def _queue_calendar_upsert(session: Session, account: Account, event: Event) -> bool:
    if not account.google_calendar_id:
        _mark_event_local_only(event)
        session.add(event)
        return False

    now = datetime.now(timezone.utc)
    existing_job = session.exec(
        select(CalendarSyncJob)
        .where(CalendarSyncJob.event_id == event.id, CalendarSyncJob.operation == "upsert")
        .order_by(CalendarSyncJob.id.desc())
    ).first()
    if existing_job is None:
        existing_job = CalendarSyncJob(
            account_id=account.id,
            event_id=event.id,
            operation="upsert",
        )

    existing_job.status = "pending"
    existing_job.last_error = None
    existing_job.next_attempt_at = now
    existing_job.updated_at = now
    existing_job.completed_at = None
    session.add(existing_job)
    queued_error = "Forced Google Calendar retry test" if FORCE_GCAL_QUEUE_RETRY_TEST else None
    _mark_event_sync_queued(event, error=queued_error)
    session.add(event)
    return True


def _queue_calendar_delete(session: Session, account: Account, event: Event) -> bool:
    if not account.google_calendar_id or not event.calendar_event_id:
        session.delete(event)
        return False

    for upsert_job in session.exec(
        select(CalendarSyncJob).where(CalendarSyncJob.event_id == event.id, CalendarSyncJob.operation == "upsert")
    ).all():
        session.delete(upsert_job)

    now = datetime.now(timezone.utc)
    existing_job = session.exec(
        select(CalendarSyncJob)
        .where(CalendarSyncJob.event_id == event.id, CalendarSyncJob.operation == "delete")
        .order_by(CalendarSyncJob.id.desc())
    ).first()
    if existing_job is None:
        existing_job = CalendarSyncJob(
            account_id=account.id,
            event_id=event.id,
            operation="delete",
        )

    existing_job.status = "pending"
    existing_job.last_error = None
    existing_job.next_attempt_at = now
    existing_job.updated_at = now
    existing_job.completed_at = None
    existing_job.payload_json = _serialize_sync_job_payload({"calendar_event_id": event.calendar_event_id})
    event.deleted_at = now
    event.is_active = False
    queued_error = "Forced Google Calendar retry test" if FORCE_GCAL_QUEUE_RETRY_TEST else None
    _mark_event_sync_queued(event, error=queued_error)
    session.add(existing_job)
    session.add(event)
    return True


def _wake_calendar_sync_worker() -> None:
    if _calendar_sync_worker_enabled:
        _calendar_sync_wakeup.set()


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
        account.google_calendar_summary = f"{get_app_profile().app_name} Legacy Calendar"
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
        _mark_event_local_only(event)
        session.add(event)
        session.commit()
        session.refresh(event)
        return event

    _maybe_raise_forced_calendar_sync_failure()
    service = get_calendar_service()
    if event.calendar_event_id:
        try:
            result = service.update_event_from_baby_event(
                event.calendar_event_id,
                event,
                calendar_id=account.google_calendar_id,
            )
        except HttpError as exc:
            if getattr(exc.resp, "status", None) != 404:
                raise
            event.calendar_event_id = None
            result = service.create_event_from_baby_event(event, calendar_id=account.google_calendar_id)
    else:
        result = service.create_event_from_baby_event(event, calendar_id=account.google_calendar_id)

    event.calendar_event_id = result["id"]
    _update_event_sync_metadata_from_google(event, result)
    _mark_event_synced(event)
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
            Event.deleted_at.is_(None),
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
    pending_jobs_by_event_id = _pending_sync_jobs_by_event_id(session, account.id)

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
                pending_job = pending_jobs_by_event_id.get(existing_event.id) if existing_event.id is not None else None
                if pending_job and pending_job.operation == "upsert":
                    continue
                if pending_job and pending_job.operation == "delete":
                    session.exec(
                        select(CalendarSyncJob).where(CalendarSyncJob.id == pending_job.id)
                    ).first()
                    session.delete(pending_job)
                session.delete(existing_event)
                deleted_count += 1
            continue

        pending_job = pending_jobs_by_event_id.get(existing_event.id) if existing_event and existing_event.id is not None else None
        if existing_event and existing_event.deleted_at is not None:
            continue
        if pending_job and pending_job.operation == "upsert":
            continue
        if pending_job and pending_job.operation == "delete":
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
            pending_job = pending_jobs_by_event_id.get(existing_event.id) if existing_event.id is not None else None
            if pending_job:
                continue
            if existing_event.deleted_at is not None:
                continue
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


def _delete_calendar_event_from_google(account: Account, calendar_event_id: str) -> None:
    _maybe_raise_forced_calendar_sync_failure()
    try:
        get_calendar_service().delete_event(calendar_event_id, calendar_id=account.google_calendar_id)
    except HttpError as exc:
        if getattr(exc.resp, "status", None) != 404:
            raise


def _process_calendar_sync_job(job_id: int) -> None:
    with Session(engine) as session:
        job = session.get(CalendarSyncJob, job_id)
        if job is None or job.status not in ("pending", "retrying"):
            return
        if _ensure_utc(job.next_attempt_at) > datetime.now(timezone.utc):
            return

        job.status = "processing"
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()

    try:
        with Session(engine) as session:
            job = session.get(CalendarSyncJob, job_id)
            if job is None:
                return

            account = session.get(Account, job.account_id)
            event = session.get(Event, job.event_id) if job.event_id is not None else None

            if job.operation == "upsert":
                if account is None:
                    session.delete(job)
                    session.commit()
                    return
                if event is None or event.deleted_at is not None:
                    session.delete(job)
                    session.commit()
                    return
                _sync_event_to_calendar(session, account, event)
                refreshed_job = session.get(CalendarSyncJob, job_id)
                if refreshed_job is not None:
                    session.delete(refreshed_job)
                    session.commit()
                return

            if job.operation == "delete":
                if account is None:
                    if event is not None:
                        session.delete(event)
                    session.delete(job)
                    session.commit()
                    return

                payload = _deserialize_sync_job_payload(job)
                calendar_event_id = payload.get("calendar_event_id") or (event.calendar_event_id if event else None)
                if calendar_event_id:
                    _delete_calendar_event_from_google(account, calendar_event_id)
                if event is not None:
                    session.delete(event)
                session.delete(job)
                session.commit()
                return

            raise ValueError(f"Unsupported calendar sync job operation: {job.operation}")
    except Exception as exc:
        with Session(engine) as session:
            job = session.get(CalendarSyncJob, job_id)
            if job is None:
                return

            event = session.get(Event, job.event_id) if job.event_id is not None else None
            error_message = _calendar_sync_error_message(exc)
            now = datetime.now(timezone.utc)

            job.attempt_count += 1
            job.last_error = error_message
            job.updated_at = now
            if _is_retryable_calendar_error(exc):
                job.status = "retrying"
                job.next_attempt_at = now + timedelta(seconds=_calendar_sync_retry_delay_seconds(job.attempt_count))
                if event is not None:
                    _mark_event_sync_queued(event, error=error_message)
                    session.add(event)
                logger.warning("Calendar sync job %s will retry after error: %s", job_id, error_message)
            else:
                job.status = "failed"
                job.completed_at = now
                if event is not None:
                    _mark_event_sync_failed(event, error_message)
                    session.add(event)
                logger.error("Calendar sync job %s failed permanently: %s", job_id, error_message)

            session.add(job)
            session.commit()


def _process_calendar_sync_jobs(limit: int = CALENDAR_SYNC_MAX_BATCH_SIZE) -> int:
    with Session(engine) as session:
        now = datetime.now(timezone.utc)
        due_job_ids = [
            job.id
            for job in session.exec(
                select(CalendarSyncJob)
                .where(
                    CalendarSyncJob.status.in_(("pending", "retrying")),
                    CalendarSyncJob.next_attempt_at <= now,
                )
                .order_by(CalendarSyncJob.created_at.asc())
            ).all()
            if job.id is not None
        ][:limit]

    for job_id in due_job_ids:
        _process_calendar_sync_job(job_id)

    return len(due_job_ids)


def _calendar_sync_worker_loop() -> None:
    while not _calendar_sync_stop_event.is_set():
        processed_count = _process_calendar_sync_jobs()
        if processed_count >= CALENDAR_SYNC_MAX_BATCH_SIZE:
            continue
        _calendar_sync_wakeup.wait(timeout=CALENDAR_SYNC_QUEUE_POLL_INTERVAL_SECONDS)
        _calendar_sync_wakeup.clear()


def _start_calendar_sync_worker() -> None:
    global _calendar_sync_worker_thread
    if not _calendar_sync_worker_enabled:
        return
    if _calendar_sync_worker_thread is not None and _calendar_sync_worker_thread.is_alive():
        return

    _calendar_sync_stop_event.clear()
    _calendar_sync_wakeup.clear()
    _calendar_sync_worker_thread = threading.Thread(
        target=_calendar_sync_worker_loop,
        name="calendar-sync-worker",
        daemon=True,
    )
    _calendar_sync_worker_thread.start()


def _stop_calendar_sync_worker() -> None:
    global _calendar_sync_worker_thread
    if _calendar_sync_worker_thread is None:
        return

    _calendar_sync_stop_event.set()
    _calendar_sync_wakeup.set()
    _calendar_sync_worker_thread.join(timeout=5)
    _calendar_sync_worker_thread = None


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
            Event.deleted_at.is_(None),
        )
    ).all()

    for event in events:
        _delete_event(session, account, event)

    session.commit()
    return len(events)


def _delete_event(session: Session, account: Account, event: Event) -> None:
    _queue_calendar_delete(session, account, event)


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
    sampled_buttons = ordered_buttons[: len(start_slots)]
    if len(sampled_buttons) < len(start_slots):
        sampled_buttons.extend(
            rng.choice(ordered_buttons)
            for _ in range(max(0, len(start_slots) - len(sampled_buttons)))
        )
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
    event.deleted_at = None
    updated = google_event.get("updated")
    event.google_updated_at = (
        _to_utc(datetime.fromisoformat(updated.replace("Z", "+00:00")))
        if updated
        else event.google_updated_at
    )
    event.calendar_synced_at = datetime.now(timezone.utc)
    _mark_event_synced(event)
    return event


def _update_event_sync_metadata_from_google(event: Event, google_event: dict) -> Event:
    event.title = google_event.get("summary") or event.title or activity_label(event.type)
    event.google_description = google_event.get("description")
    event.google_etag = google_event.get("etag")
    event.deleted_at = None
    updated = google_event.get("updated")
    if updated:
        event.google_updated_at = _to_utc(datetime.fromisoformat(updated.replace("Z", "+00:00")))
    event.calendar_synced_at = datetime.now(timezone.utc)
    _mark_event_synced(event)
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
    return {"message": _app_running_message()}


@app.get("/app-config", response_model=AppConfigResponse)
def read_app_config():
    payload = public_app_config()
    symbol_meta = get_profile_symbol_meta()
    return AppConfigResponse(
        profile_id=str(payload["profile_id"]),
        app_name=str(payload["app_name"]),
        copy_text=AppCopyResponse.model_validate(payload["copy"]),
        available_symbols=[TrackerSymbolOption.model_validate(symbol) for symbol in payload["available_symbols"]],
        button_templates=[
            _tracker_button_response(TrackerButtonConfig.model_validate(button), symbol_meta)
            for button in payload["button_templates"]
        ],
        tracker_buttons_per_page=int(payload["tracker_buttons_per_page"]),
        max_tracker_button_pages=int(payload["max_tracker_button_pages"]),
        placeholder_button_label_prefix=str(payload["placeholder_button_label_prefix"]),
    )


@app.get("/")
def read_root():
    return _frontend_file_response("index.html") or {"message": _app_running_message()}


@app.get("/custom-icons/assets/{asset_token}")
def read_custom_icon_asset(asset_token: str):
    with Session(engine) as session:
        custom_icon = session.exec(select(CustomIcon).where(CustomIcon.asset_token == asset_token)).first()
        if custom_icon is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom icon not found")

        asset_path = (CUSTOM_ICON_STORAGE_DIR / custom_icon.asset_filename).resolve()
        try:
            asset_path.relative_to(CUSTOM_ICON_STORAGE_DIR.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom icon not found") from exc
        if not asset_path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom icon not found")
        return FileResponse(asset_path)


@app.post("/custom-icons", response_model=TrackerSymbolOption)
def create_custom_icon_endpoint(
    label: str = Form(...),
    emoji: str = Form(...),
    keywords: Optional[str] = Form(default=None),
    is_public: Optional[str] = Form(default=None),
    asset: UploadFile = File(...),
    session_context: SessionContext = Depends(require_session),
):
    normalized_label = _normalize_custom_icon_label(label)
    normalized_emoji = _normalize_custom_icon_emoji(emoji)
    normalized_keywords = _normalize_custom_icon_keywords(keywords)
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        asset_token, asset_filename = _write_custom_icon_asset(asset)
        custom_icon = CustomIcon(
            account_id=account.id,
            label=normalized_label,
            emoji=normalized_emoji,
            keywords_json=json.dumps(normalized_keywords),
            asset_token=asset_token,
            asset_filename=asset_filename,
            is_public=_is_truthy_form_value(is_public),
        )
        session.add(custom_icon)
        session.commit()
        session.refresh(custom_icon)
        return _custom_icon_symbol_option(custom_icon, can_delete=True)


@app.delete("/custom-icons/{custom_icon_id}")
def delete_custom_icon_endpoint(custom_icon_id: int, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        custom_icon = session.exec(select(CustomIcon).where(CustomIcon.id == custom_icon_id)).first()
        if custom_icon is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom icon not found")
        if custom_icon.account_id != session_context.account_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom icon not found")

        asset_path = (CUSTOM_ICON_STORAGE_DIR / custom_icon.asset_filename).resolve()
        session.delete(custom_icon)
        session.commit()

        try:
            asset_path.relative_to(CUSTOM_ICON_STORAGE_DIR.resolve())
        except ValueError:
            return {"status": "success"}
        if asset_path.is_file():
            asset_path.unlink()
        return {"status": "success"}


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
            color_palette=DEFAULT_COLOR_PALETTE,
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
        if payload.color_palette is not None:
            account.color_palette = _normalize_color_palette(payload.color_palette)
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
        try:
            _store_tracker_buttons(session, account, payload.buttons)
        except HTTPException as exc:
            logger.warning(
                "Rejected tracker buttons update for account %s: %s",
                account.id,
                exc.detail,
            )
            raise
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
        except HTTPException:
            raise
        except Exception as exc:
            account.google_last_sync_status = "error"
            account.updated_at = datetime.now(timezone.utc)
            session.add(account)
            session.commit()
            logger.warning("Google pull sync failed for account %s: %s", account.id, _calendar_sync_error_message(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google pull sync temporarily unavailable",
            ) from exc


@app.post("/events", response_model=EventResponse)
def create_event_endpoint(event: EventCreate, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        tracker_buttons = _get_tracker_buttons(session, account)
        symbol_meta = _tracker_symbol_meta(_all_tracker_symbols(session, account))
        activity_type = normalize_activity_type(event.type)
        db_event = Event(
            account_id=account.id,
            type=activity_type,
            title=_resolved_event_title(tracker_buttons, activity_type, symbol_meta),
            start_time=_to_utc(event.start_time),
            end_time=_to_utc(event.end_time) if event.end_time is not None else None,
            duration=event.duration,
            details=event.details,
            is_active=False,
        )
        if account.google_calendar_id:
            _mark_event_sync_pending(db_event)
        else:
            _mark_event_local_only(db_event)
        session.add(db_event)
        session.commit()
        session.refresh(db_event)
        return _event_response(db_event, account)


@app.get("/events", response_model=list[EventResponse])
def list_events_endpoint(session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        events = session.exec(
            select(Event)
            .where(Event.account_id == account.id, Event.deleted_at.is_(None))
            .order_by(Event.start_time.desc())
        ).all()
        return [_event_response(event, account) for event in events]


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
        _wake_calendar_sync_worker()
        return DayActionResponse(
            target_date=parsed_date.isoformat(),
            deleted_count=deleted_count,
            synced_to_calendar=False,
            calendar_sync_state="queued" if account.google_calendar_id else "local_only",
        )


@app.delete("/events/{event_id}")
def delete_event_endpoint(event_id: int, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        event = session.exec(
            select(Event).where(Event.id == event_id, Event.account_id == account.id, Event.deleted_at.is_(None))
        ).first()
        if not event:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

        _delete_event(session, account, event)
        session.commit()
        _wake_calendar_sync_worker()
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
        symbol_meta = _tracker_symbol_meta(_all_tracker_symbols(session, account))
        for payload in _sample_day_events(
            parsed_date,
            local_time_zone,
            tracker_buttons,
            seed_value=f"{account.id}:{parsed_date.isoformat()}",
        ):
            payload["title"] = _resolved_event_title(tracker_buttons, str(payload["type"]), symbol_meta)
            event = Event(account_id=account.id, **payload)
            session.add(event)
            session.commit()
            session.refresh(event)
            _mark_event_sync_pending(event)
            session.add(event)
            session.commit()
            _queue_calendar_upsert(session, account, event)
            session.commit()
            created_count += 1

        _wake_calendar_sync_worker()

        return DayActionResponse(
            target_date=parsed_date.isoformat(),
            deleted_count=deleted_count,
            created_count=created_count,
            synced_to_calendar=False,
            calendar_sync_state="queued",
        )


@app.post("/activities/start")
def start_activity_endpoint(activity: ActivityStart, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        tracker_buttons = _get_tracker_buttons(session, account)
        symbol_meta = _tracker_symbol_meta(_all_tracker_symbols(session, account))
        activity_type = normalize_activity_type(activity.type)
        if _get_active_event(session, account.id, activity_type):
            return {"status": "error", "message": f"Activity '{activity_type}' is already running"}

        db_event = Event(
            account_id=account.id,
            type=activity_type,
            title=_resolved_event_title(tracker_buttons, activity_type, symbol_meta),
            start_time=datetime.now(timezone.utc),
            details=activity.details.strip() if activity.details else None,
            is_active=True,
        )
        if account.google_calendar_id:
            _mark_event_sync_pending(db_event)
        else:
            _mark_event_local_only(db_event)
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
            _queue_calendar_upsert(session, account, db_event)
        else:
            _mark_event_local_only(db_event)
            session.add(db_event)
        session.commit()
        session.refresh(db_event)
        _wake_calendar_sync_worker()
        return {
            "status": "success",
            "message": f"Stopped tracking '{activity_type}'",
            "event_id": db_event.id,
            "start_time": start_time,
            "end_time": _ensure_utc(end_time),
            "duration_seconds": duration,
            "calendar_sync_state": _event_sync_state(account, db_event),
            "calendar_sync_message": _event_sync_message(_event_sync_state(account, db_event), db_event),
        }


@app.patch("/events/{event_id}", response_model=EventResponse)
def update_event_endpoint(event_id: int, event_update: EventUpdate, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        event = session.exec(
            select(Event).where(Event.id == event_id, Event.account_id == account.id, Event.deleted_at.is_(None))
        ).first()
        if not event:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

        event.details = event_update.details.strip() if event_update.details else None
        session.add(event)
        session.commit()
        session.refresh(event)
        if not event.is_active:
            if account.google_calendar_id:
                _queue_calendar_upsert(session, account, event)
            else:
                _mark_event_local_only(event)
                session.add(event)
            session.commit()
            session.refresh(event)
            _wake_calendar_sync_worker()
        return _event_response(event, account)


@app.post("/events/{event_id}/finalize", response_model=EventResponse)
def finalize_event_endpoint(event_id: int, event_finalize: EventFinalize, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)
        event = session.exec(
            select(Event).where(Event.id == event_id, Event.account_id == account.id, Event.deleted_at.is_(None))
        ).first()
        if not event:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

        if event_finalize.details is not None:
            event.details = event_finalize.details.strip() or None
            session.add(event)
            session.commit()
            session.refresh(event)

        if not event.is_active:
            if account.google_calendar_id:
                _queue_calendar_upsert(session, account, event)
            else:
                _mark_event_local_only(event)
                session.add(event)
            session.commit()
            session.refresh(event)
            _wake_calendar_sync_worker()
        return _event_response(event, account)


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
