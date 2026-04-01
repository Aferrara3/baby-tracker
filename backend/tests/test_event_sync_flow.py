import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import main
from calendar_service import ACTIVITY_META
from dateutil.parser import parse as parse_dt


class FakeCalendarService:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.updated: list[dict] = []

    def create_event_from_baby_event(self, event) -> dict:
        payload = {
            "id": f"created-{len(self.created) + 1}",
            "type": event.type,
            "start_time": event.start_time,
            "end_time": event.end_time,
            "duration": event.duration,
            "details": event.details,
            "summary": ACTIVITY_META.get(event.type, ("unknown", ""))[0],
        }
        self.created.append(payload)
        return payload

    def update_event_from_baby_event(self, calendar_event_id: str, event) -> dict:
        payload = {
            "id": calendar_event_id,
            "type": event.type,
            "start_time": event.start_time,
            "end_time": event.end_time,
            "duration": event.duration,
            "details": event.details,
            "summary": ACTIVITY_META.get(event.type, ("unknown", ""))[0],
        }
        self.updated.append(payload)
        return payload


@pytest.fixture()
def isolated_backend(monkeypatch, tmp_path):
    database_path = tmp_path / "test.db"
    test_engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )

    old_engine = main.engine
    old_timers = main.active_timers
    old_service = main._calendar_service

    main.engine = test_engine
    main.active_timers = {}
    main._calendar_service = FakeCalendarService()
    SQLModel.metadata.create_all(main.engine)
    main._ensure_event_columns()

    try:
        yield main._calendar_service
    finally:
        main.engine = old_engine
        main.active_timers = old_timers
        main._calendar_service = old_service


def test_tap_event_waits_for_finalize_and_keeps_details(isolated_backend):
    response = main.create_event(
        main.EventCreate(
            type="bottle",
            start_time=datetime.now(timezone.utc),
        )
    )

    assert isolated_backend.created == []

    finalized = main.finalize_event(
        response.id,
        main.EventFinalize(details="ate 4 oz"),
    )

    assert finalized.details == "ate 4 oz"
    assert len(isolated_backend.created) == 1
    assert isolated_backend.created[0]["details"] == "ate 4 oz"
    assert isolated_backend.created[0]["summary"] == "🍼 Bottle"


def test_legacy_frontend_ids_are_normalized(isolated_backend):
    response = main.create_event(
        main.EventCreate(
            type="diaper1",
            start_time=datetime.now(timezone.utc),
        )
    )

    assert response.type == "diaper_pee"

    finalized = main.finalize_event(response.id, main.EventFinalize())
    assert finalized.type == "diaper_pee"
    assert isolated_backend.created[0]["summary"] == "💧 Diaper (Pee)"


def test_patch_updates_existing_calendar_event(isolated_backend):
    created = main.create_event(
        main.EventCreate(
            type="food",
            start_time=datetime.now(timezone.utc),
        )
    )
    main.finalize_event(created.id, main.EventFinalize(details="puree"))

    updated = main.update_event(created.id, main.EventUpdate(details="puree + yogurt"))

    assert updated.details == "puree + yogurt"
    assert len(isolated_backend.created) == 1
    assert len(isolated_backend.updated) == 1
    assert isolated_backend.updated[0]["details"] == "puree + yogurt"


def test_hold_event_uses_real_start_stop_times_and_waits_for_finalize(isolated_backend, monkeypatch):
    class FakeDateTime(datetime):
        current = datetime(2026, 3, 30, 1, 0, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls.current.replace(tzinfo=None)
            return cls.current.astimezone(tz)

    monkeypatch.setattr(main, "datetime", FakeDateTime)

    start_at = datetime(2026, 3, 30, 1, 0, 0, tzinfo=timezone.utc)
    stop_at = start_at + timedelta(minutes=42, seconds=30)

    FakeDateTime.current = start_at
    main.start_activity(main.ActivityStart(type="sleep"))

    assert isolated_backend.created == []

    FakeDateTime.current = stop_at
    stopped = main.stop_activity(main.ActivityStop(type="sleep"))

    assert isolated_backend.created == []
    assert stopped["duration_seconds"] == 2550

    main.finalize_event(stopped["event_id"], main.EventFinalize(details="slept on parent"))

    created_payload = isolated_backend.created[0]
    assert created_payload["type"] == "sleep"
    assert created_payload["start_time"].replace(tzinfo=timezone.utc) == start_at
    assert created_payload["end_time"].replace(tzinfo=timezone.utc) == stop_at
    assert created_payload["duration"] == 2550
    assert created_payload["details"] == "slept on parent"

    with Session(main.engine) as session:
        event = session.exec(select(main.Event).where(main.Event.id == stopped["event_id"])).one()
        assert event.calendar_event_id == "created-1"
        assert event.duration == 2550


def test_integration_service_updates_existing_calendar_event():
    svc = main.get_calendar_service()
    now = datetime.now(timezone.utc)
    created = svc.create_event_from_baby_event(
        {
            "type": "sleep",
            "start_time": now,
            "end_time": now + timedelta(minutes=25),
            "duration": 1500,
            "details": "initial sync",
        }
    )

    updated = svc.update_event_from_baby_event(
        created["id"],
        {
            "type": "sleep",
            "start_time": now,
            "end_time": now + timedelta(minutes=25),
            "duration": 1500,
            "details": "updated metadata",
        },
    )

    assert updated["id"] == created["id"]
    assert updated["summary"] == "😴 Sleep"
    assert "updated metadata" in updated.get("description", "")
    assert parse_dt(updated["start"]["dateTime"]).astimezone(timezone.utc).replace(microsecond=0) == now.replace(microsecond=0)
