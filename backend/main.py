import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, create_engine, Session, select, Field
from sqlalchemy import text
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Optional, List

from calendar_service import CalendarService, normalize_activity_type
from config import CREDENTIALS_PATH, CALENDAR_ID

logger = logging.getLogger(__name__)

_calendar_service: Optional[CalendarService] = None


def get_calendar_service() -> CalendarService:
    global _calendar_service
    if _calendar_service is None:
        _calendar_service = CalendarService(CREDENTIALS_PATH, CALENDAR_ID)
    return _calendar_service


# Database setup
DATABASE_URL = "sqlite:///./database.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Models
class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    type: str  # e.g., "feeding", "diaper_change", "sleep", etc.
    start_time: datetime
    end_time: Optional[datetime] = None
    duration: Optional[int] = None  # in seconds
    details: Optional[str] = None
    calendar_event_id: Optional[str] = None
    calendar_synced_at: Optional[datetime] = None


class EventCreate(BaseModel):
    type: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration: Optional[int] = None
    details: Optional[str] = None


class EventResponse(BaseModel):
    id: int
    type: str
    start_time: datetime
    end_time: Optional[datetime]
    duration: Optional[int]
    details: Optional[str]


class ActivityStart(BaseModel):
    type: str
    details: Optional[str] = None


class ActivityStop(BaseModel):
    type: str


# Initialize FastAPI app
app = FastAPI(
    title="Baby Tracker API",
    description="API for tracking baby activities",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3005"],  # Vite default
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global dict to track active timers
active_timers = {}


@app.get("/")
def read_root():
    """Health check endpoint."""
    return {"message": "Baby Tracker API is running"}


@app.post("/events", response_model=EventResponse)
def create_event(event: EventCreate):
    """Create a new event log."""
    db_event = Event(
        type=normalize_activity_type(event.type),
        start_time=event.start_time,
        end_time=event.end_time,
        duration=event.duration,
        details=event.details
    )
    with Session(engine) as session:
        session.add(db_event)
        session.commit()
        session.refresh(db_event)
        return _event_response(db_event)


@app.get("/events", response_model=List[EventResponse])
def list_events():
    """List all events."""
    with Session(engine) as session:
        events = session.exec(select(Event)).all()
        return [
            _event_response(event)
            for event in events
        ]


@app.post("/activities/start")
def start_activity(activity: ActivityStart):
    """Start a timer for an activity type."""
    activity_type = normalize_activity_type(activity.type)
    if activity_type in active_timers:
        return {
            "status": "error",
            "message": f"Activity '{activity_type}' is already running"
        }
    
    active_timers[activity_type] = {
        "start_time": datetime.now(timezone.utc),
        "details": activity.details
    }
    
    return {
        "status": "success",
        "message": f"Started tracking '{activity_type}'",
        "start_time": active_timers[activity_type]["start_time"]
    }


@app.post("/activities/stop")
def stop_activity(activity: ActivityStop):
    """Stop a timer and log the duration."""
    activity_type = normalize_activity_type(activity.type)
    if activity_type not in active_timers:
        return {
            "status": "error",
            "message": f"No active timer for '{activity_type}'"
        }
    
    timer_data = active_timers.pop(activity_type)
    start_time = timer_data["start_time"]
    end_time = datetime.now(timezone.utc)
    duration = int((end_time - start_time).total_seconds())
    
    # Create and save the event
    db_event = Event(
        type=activity_type,
        start_time=start_time,
        end_time=end_time,
        duration=duration,
        details=timer_data.get("details")
    )
    
    with Session(engine) as session:
        session.add(db_event)
        session.commit()
        session.refresh(db_event)
        return {
            "status": "success",
            "message": f"Stopped tracking '{activity_type}'",
            "event_id": db_event.id,
            "start_time": start_time,
            "end_time": end_time,
            "duration_seconds": duration
        }


class EventUpdate(BaseModel):
    details: Optional[str] = None


class EventFinalize(BaseModel):
    details: Optional[str] = None


def _ensure_event_columns() -> None:
    """Add new event columns to an existing SQLite database."""
    with engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(event)")).fetchall()
        }
        if "calendar_event_id" not in columns:
            connection.execute(text("ALTER TABLE event ADD COLUMN calendar_event_id VARCHAR"))
        if "calendar_synced_at" not in columns:
            connection.execute(text("ALTER TABLE event ADD COLUMN calendar_synced_at DATETIME"))


def _event_response(event: Event) -> EventResponse:
    return EventResponse(
        id=event.id,
        type=event.type,
        start_time=event.start_time,
        end_time=event.end_time,
        duration=event.duration,
        details=event.details,
    )


def _sync_event_to_calendar(session: Session, event: Event) -> Event:
    service = get_calendar_service()
    if event.calendar_event_id:
        result = service.update_event_from_baby_event(event.calendar_event_id, event)
    else:
        result = service.create_event_from_baby_event(event)

    event.calendar_event_id = result["id"]
    event.calendar_synced_at = datetime.now(timezone.utc)
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


# Create tables
SQLModel.metadata.create_all(engine)
_ensure_event_columns()


@app.patch("/events/{event_id}", response_model=EventResponse)
def update_event(event_id: int, event_update: EventUpdate):
    """Update event details."""
    with Session(engine) as session:
        event = session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

        event.details = event_update.details.strip() if event_update.details else None
        session.add(event)
        session.commit()
        session.refresh(event)
        if event.calendar_event_id:
            event = _sync_event_to_calendar(session, event)
        return _event_response(event)


@app.post("/events/{event_id}/finalize", response_model=EventResponse)
def finalize_event(event_id: int, event_finalize: EventFinalize):
    """Persist final notes and then sync the event to Google Calendar."""
    with Session(engine) as session:
        event = session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

        if event_finalize.details is not None:
            event.details = event_finalize.details.strip() or None
            session.add(event)
            session.commit()
            session.refresh(event)

        event = _sync_event_to_calendar(session, event)
        return _event_response(event)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)
