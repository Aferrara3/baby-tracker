import hashlib
import logging
import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlmodel import Field, SQLModel, Session, create_engine, select

from calendar_service import (
    CalendarService,
    activity_label,
    infer_activity_type_from_summary,
    normalize_activity_type,
)
from config import CALENDAR_ID, CREDENTIALS_PATH, SESSION_TTL_DAYS

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)

DATABASE_URL = "sqlite:///./database.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


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
    allow_origins=["http://localhost:3005"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_calendar_service: Optional[CalendarService] = None
active_timers: dict[int, dict[str, dict]] = {}


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
    _ensure_column("event", "google_description", "ALTER TABLE event ADD COLUMN google_description VARCHAR")
    _ensure_column("event", "calendar_event_id", "ALTER TABLE event ADD COLUMN calendar_event_id VARCHAR")
    _ensure_column("event", "calendar_synced_at", "ALTER TABLE event ADD COLUMN calendar_synced_at DATETIME")
    _ensure_column("event", "google_etag", "ALTER TABLE event ADD COLUMN google_etag VARCHAR")
    _ensure_column("event", "google_updated_at", "ALTER TABLE event ADD COLUMN google_updated_at DATETIME")


def _ensure_account_columns() -> None:
    _ensure_column("account", "google_sync_token", "ALTER TABLE account ADD COLUMN google_sync_token VARCHAR")
    _ensure_column("account", "google_last_synced_at", "ALTER TABLE account ADD COLUMN google_last_synced_at DATETIME")
    _ensure_column("account", "google_last_sync_status", "ALTER TABLE account ADD COLUMN google_last_sync_status VARCHAR")


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


def _timers_for_account(account_id: int) -> dict[str, dict]:
    return active_timers.setdefault(account_id, {})


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
        if account.google_calendar_id and event.calendar_event_id:
            get_calendar_service().delete_event(event.calendar_event_id, calendar_id=account.google_calendar_id)
        session.delete(event)

    session.commit()
    return len(events)


def _sample_day_events(target_date: date, local_time_zone) -> list[dict]:
    def at(hour: int, minute: int) -> datetime:
        return datetime.combine(
            target_date,
            time(hour=hour, minute=minute),
            tzinfo=local_time_zone,
        ).astimezone(timezone.utc)

    return [
        {"type": "sleep", "title": activity_label("sleep"), "start_time": at(0, 30), "end_time": at(5, 45), "duration": 5 * 3600 + 15 * 60, "details": "Overnight sleep"},
        {"type": "bottle", "title": activity_label("bottle"), "start_time": at(6, 5), "end_time": at(6, 25), "duration": 20 * 60, "details": "Morning bottle"},
        {"type": "diaper_pee", "title": activity_label("diaper_pee"), "start_time": at(6, 40), "end_time": at(6, 45), "duration": 5 * 60, "details": "Quick diaper change"},
        {"type": "breastfeeding", "title": activity_label("breastfeeding"), "start_time": at(8, 0), "end_time": at(8, 25), "duration": 25 * 60, "details": "Morning nursing session"},
        {"type": "sleep", "title": activity_label("sleep"), "start_time": at(9, 30), "end_time": at(10, 45), "duration": 75 * 60, "details": "Morning nap"},
        {"type": "food", "title": activity_label("food"), "start_time": at(11, 15), "end_time": at(11, 35), "duration": 20 * 60, "details": "Puree and water"},
        {"type": "diaper_poop", "title": activity_label("diaper_poop"), "start_time": at(12, 5), "end_time": at(12, 15), "duration": 10 * 60, "details": "Post-lunch diaper"},
        {"type": "pump", "title": activity_label("pump"), "start_time": at(13, 10), "end_time": at(13, 30), "duration": 20 * 60, "details": "Afternoon pump"},
        {"type": "sleep", "title": activity_label("sleep"), "start_time": at(14, 0), "end_time": at(15, 10), "duration": 70 * 60, "details": "Afternoon nap"},
        {"type": "food", "title": activity_label("food"), "start_time": at(17, 45), "end_time": at(18, 5), "duration": 20 * 60, "details": "Dinner solids"},
        {"type": "bottle", "title": activity_label("bottle"), "start_time": at(19, 30), "end_time": at(19, 45), "duration": 15 * 60, "details": "Bedtime top-off"},
        {"type": "sleep", "title": activity_label("sleep"), "start_time": at(20, 15), "end_time": at(23, 59), "duration": 3 * 3600 + 44 * 60, "details": "Bedtime stretch"},
    ]


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


SQLModel.metadata.create_all(engine)
_ensure_account_columns()
_ensure_event_columns()


@app.get("/")
def read_root():
    return {"message": "Baby Tracker API is running"}


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
        db_event = Event(
            account_id=account.id,
            type=normalize_activity_type(event.type),
            title=activity_label(event.type),
            start_time=_to_utc(event.start_time),
            end_time=_to_utc(event.end_time) if event.end_time is not None else None,
            duration=event.duration,
            details=event.details,
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
        for payload in _sample_day_events(parsed_date, local_time_zone):
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

    activity_type = normalize_activity_type(activity.type)
    timers = _timers_for_account(account.id)
    if activity_type in timers:
        return {"status": "error", "message": f"Activity '{activity_type}' is already running"}

    timers[activity_type] = {
        "start_time": datetime.now(timezone.utc),
        "details": activity.details,
    }
    return {
        "status": "success",
        "message": f"Started tracking '{activity_type}'",
        "start_time": timers[activity_type]["start_time"],
    }


@app.post("/activities/stop")
def stop_activity_endpoint(activity: ActivityStop, session_context: SessionContext = Depends(require_session)):
    with Session(engine) as session:
        account = _load_account(session, session_context.account_id)

        activity_type = normalize_activity_type(activity.type)
        timers = _timers_for_account(account.id)
        if activity_type not in timers:
            return {"status": "error", "message": f"No active timer for '{activity_type}'"}

        timer_data = timers.pop(activity_type)
        start_time = timer_data["start_time"]
        end_time = datetime.now(timezone.utc)
        duration = int((end_time - start_time).total_seconds())

        db_event = Event(
            account_id=account.id,
            type=activity_type,
            title=activity_label(activity_type),
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            details=timer_data.get("details"),
        )
        session.add(db_event)
        session.commit()
        session.refresh(db_event)
        return {
            "status": "success",
            "message": f"Stopped tracking '{activity_type}'",
            "event_id": db_event.id,
            "start_time": start_time,
            "end_time": end_time,
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

        event = _sync_event_to_calendar(session, account, event)
        return _event_response(event)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8090)
