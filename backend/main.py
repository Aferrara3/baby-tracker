from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, create_engine, Session, select, Field
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
import os

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


# Create tables
SQLModel.metadata.create_all(engine)

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
        type=event.type,
        start_time=event.start_time,
        end_time=event.end_time,
        duration=event.duration,
        details=event.details
    )
    with Session(engine) as session:
        session.add(db_event)
        session.commit()
        session.refresh(db_event)
        return EventResponse(
            id=db_event.id,
            type=db_event.type,
            start_time=db_event.start_time,
            end_time=db_event.end_time,
            duration=db_event.duration,
            details=db_event.details
        )


@app.get("/events", response_model=List[EventResponse])
def list_events():
    """List all events."""
    with Session(engine) as session:
        events = session.exec(select(Event)).all()
        return [
            EventResponse(
                id=event.id,
                type=event.type,
                start_time=event.start_time,
                end_time=event.end_time,
                duration=event.duration,
                details=event.details
            )
            for event in events
        ]


@app.post("/activities/start")
def start_activity(activity: ActivityStart):
    """Start a timer for an activity type."""
    if activity.type in active_timers:
        return {
            "status": "error",
            "message": f"Activity '{activity.type}' is already running"
        }
    
    active_timers[activity.type] = {
        "start_time": datetime.now(),
        "details": activity.details
    }
    
    return {
        "status": "success",
        "message": f"Started tracking '{activity.type}'",
        "start_time": active_timers[activity.type]["start_time"]
    }


@app.post("/activities/stop")
def stop_activity(activity: ActivityStop):
    """Stop a timer and log the duration."""
    if activity.type not in active_timers:
        return {
            "status": "error",
            "message": f"No active timer for '{activity.type}'"
        }
    
    timer_data = active_timers.pop(activity.type)
    start_time = timer_data["start_time"]
    end_time = datetime.now()
    duration = int((end_time - start_time).total_seconds())
    
    # Create and save the event
    db_event = Event(
        type=activity.type,
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
        "message": f"Stopped tracking '{activity.type}'",
        "event_id": db_event.id,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": duration
    }


class EventUpdate(BaseModel):
    details: str


@app.patch("/events/{event_id}", response_model=EventResponse)
def update_event(event_id: int, event_update: EventUpdate):
    """Update event details."""
    with Session(engine) as session:
        event = session.get(Event, event_id)
        if not event:
            return {"error": "Event not found"}
        
        event.details = event_update.details
        session.add(event)
        session.commit()
        session.refresh(event)
        return EventResponse(
            id=event.id,
            type=event.type,
            start_time=event.start_time,
            end_time=event.end_time,
            duration=event.duration,
            details=event.details
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)
