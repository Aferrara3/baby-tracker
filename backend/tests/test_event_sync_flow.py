import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import main


class FakeCalendarService:
    def __init__(self) -> None:
        self.created_events: list[dict] = []
        self.updated_events: list[dict] = []
        self.deleted_events: list[dict] = []
        self.created_calendars: list[dict] = []
        self.shared_calendars: list[dict] = []
        self.updated_calendars: list[dict] = []

    def create_event_from_baby_event(self, event, calendar_id=None) -> dict:
        payload = {
            "id": f"event-{len(self.created_events) + 1}",
            "calendar_id": calendar_id,
            "type": event.type,
            "start_time": event.start_time,
            "end_time": event.end_time,
            "duration": event.duration,
            "details": event.details,
        }
        self.created_events.append(payload)
        return payload

    def update_event_from_baby_event(self, calendar_event_id, event, calendar_id=None) -> dict:
        payload = {
            "id": calendar_event_id,
            "calendar_id": calendar_id,
            "type": event.type,
            "details": event.details,
        }
        self.updated_events.append(payload)
        return payload

    def create_calendar(self, summary, description=None, time_zone="UTC") -> dict:
        payload = {
            "id": f"calendar-{len(self.created_calendars) + 1}",
            "summary": summary,
            "description": description,
            "timeZone": time_zone,
        }
        self.created_calendars.append(payload)
        return payload

    def share_calendar(self, calendar_id, email, role="writer", send_notifications=True) -> dict:
        payload = {
            "calendar_id": calendar_id,
            "email": email,
            "role": role,
            "send_notifications": send_notifications,
        }
        self.shared_calendars.append(payload)
        return payload

    def update_calendar_metadata(self, calendar_id, summary, description=None, time_zone="UTC") -> dict:
        payload = {
            "id": calendar_id,
            "summary": summary,
            "description": description,
            "timeZone": time_zone,
        }
        self.updated_calendars.append(payload)
        return payload

    def delete_event(self, calendar_event_id, calendar_id=None) -> None:
        self.deleted_events.append(
            {
                "id": calendar_event_id,
                "calendar_id": calendar_id,
            }
        )


@pytest.fixture()
def client(tmp_path):
    database_path = tmp_path / "test.db"
    test_engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})

    old_engine = main.engine
    old_timers = main.active_timers
    old_service = main._calendar_service

    main.engine = test_engine
    main.active_timers = {}
    main._calendar_service = FakeCalendarService()

    SQLModel.metadata.create_all(main.engine)
    main._ensure_event_columns()

    with TestClient(main.app) as test_client:
        yield test_client

    main.engine = old_engine
    main.active_timers = old_timers
    main._calendar_service = old_service


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register(client: TestClient, username: str, password: str, baby_name: str | None = None, share_emails: list[str] | None = None):
    payload = {
        "username": username,
        "password": password,
        "baby_name": baby_name,
        "share_emails": share_emails or [],
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 200
    return response.json()


def test_register_returns_session_and_profile(client: TestClient):
    data = register(client, "parent1", "secret123", baby_name="Ava")

    assert data["token"]
    assert data["account"]["username"] == "parent1"
    assert data["account"]["baby_name"] == "Ava"

    me = client.get("/auth/me", headers=auth_headers(data["token"]))
    assert me.status_code == 200
    assert me.json()["username"] == "parent1"


def test_first_account_adopts_legacy_events(client: TestClient):
    with Session(main.engine) as session:
        session.add(
            main.Event(
                type="bottle",
                start_time=datetime.now(timezone.utc),
            )
        )
        session.commit()

    data = register(client, "owner", "secret123")

    assert data["account"]["google_calendar_id"] == main.CALENDAR_ID
    assert data["account"]["service_managed_calendar"] is False

    with Session(main.engine) as session:
        account = session.exec(select(main.Account).where(main.Account.username == "owner")).first()
        event = session.exec(select(main.Event)).first()
        assert event.account_id == account.id


def test_events_are_isolated_by_account(client: TestClient):
    account_one = register(client, "alpha", "secret123")
    account_two = register(client, "beta", "secret123")

    created = client.post(
        "/events",
        headers=auth_headers(account_one["token"]),
        json={"type": "food", "start_time": datetime.now(timezone.utc).isoformat()},
    )
    assert created.status_code == 200

    first_list = client.get("/events", headers=auth_headers(account_one["token"]))
    second_list = client.get("/events", headers=auth_headers(account_two["token"]))

    assert len(first_list.json()) == 1
    assert second_list.json() == []


def test_timers_are_scoped_per_account(client: TestClient):
    account_one = register(client, "timer1", "secret123")
    account_two = register(client, "timer2", "secret123")

    start_one = client.post("/activities/start", headers=auth_headers(account_one["token"]), json={"type": "sleep"})
    start_two = client.post("/activities/start", headers=auth_headers(account_two["token"]), json={"type": "sleep"})

    assert start_one.status_code == 200
    assert start_two.status_code == 200
    assert start_one.json()["status"] == "success"
    assert start_two.json()["status"] == "success"

    stop_one = client.post("/activities/stop", headers=auth_headers(account_one["token"]), json={"type": "sleep"})
    stop_two = client.post("/activities/stop", headers=auth_headers(account_two["token"]), json={"type": "sleep"})

    assert stop_one.json()["status"] == "success"
    assert stop_two.json()["status"] == "success"
    assert stop_one.json()["event_id"] != stop_two.json()["event_id"]


def test_enable_sync_provisions_calendar_and_shares_to_saved_emails(client: TestClient):
    data = register(client, "calendar-user", "secret123")
    token = data["token"]

    settings = client.patch(
        "/account/settings",
        headers=auth_headers(token),
        json={"baby_name": "Milo", "share_emails": ["mom@example.com", "dad@example.com"]},
    )
    assert settings.status_code == 200

    enabled = client.post("/calendar/enable-sync", headers=auth_headers(token))
    assert enabled.status_code == 200
    payload = enabled.json()

    assert payload["service_managed_calendar"] is True
    assert payload["google_calendar_id"] == "calendar-1"
    assert payload["google_calendar_summary"] == "Baby Tracker - Milo"

    fake_service = main.get_calendar_service()
    assert len(fake_service.created_calendars) == 1
    assert {row["email"] for row in fake_service.shared_calendars} == {"mom@example.com", "dad@example.com"}


def test_finalize_routes_event_to_account_calendar(client: TestClient):
    data = register(client, "sync-user", "secret123", baby_name="Noah", share_emails=["parent@example.com"])
    token = data["token"]
    enable = client.post("/calendar/enable-sync", headers=auth_headers(token))
    assert enable.status_code == 200

    created = client.post(
        "/events",
        headers=auth_headers(token),
        json={"type": "bottle", "start_time": datetime.now(timezone.utc).isoformat()},
    )
    assert created.status_code == 200

    finalized = client.post(
        f"/events/{created.json()['id']}/finalize",
        headers=auth_headers(token),
        json={"details": "4 oz formula"},
    )
    assert finalized.status_code == 200

    fake_service = main.get_calendar_service()
    assert len(fake_service.created_events) == 1
    assert fake_service.created_events[0]["calendar_id"] == "calendar-1"
    assert fake_service.created_events[0]["details"] == "4 oz formula"


def test_updating_settings_renames_service_managed_calendar(client: TestClient):
    data = register(client, "rename-user", "secret123", baby_name="Old")
    token = data["token"]
    enable = client.post("/calendar/enable-sync", headers=auth_headers(token))
    assert enable.status_code == 200

    updated = client.patch(
        "/account/settings",
        headers=auth_headers(token),
        json={"baby_name": "New Baby"},
    )
    assert updated.status_code == 200

    fake_service = main.get_calendar_service()
    assert fake_service.updated_calendars[-1]["summary"] == "Baby Tracker - New Baby"


def test_reshare_replays_acl_entries(client: TestClient):
    data = register(client, "reshare-user", "secret123", share_emails=["one@example.com", "two@example.com"])
    token = data["token"]
    client.post("/calendar/enable-sync", headers=auth_headers(token))

    fake_service = main.get_calendar_service()
    initial_shares = len(fake_service.shared_calendars)

    reshare = client.post("/calendar/reshare", headers=auth_headers(token))
    assert reshare.status_code == 200
    assert len(fake_service.shared_calendars) == initial_shares + 2


def test_existing_synced_event_updates_same_calendar_event(client: TestClient):
    data = register(client, "update-user", "secret123")
    token = data["token"]
    client.post("/calendar/enable-sync", headers=auth_headers(token))

    created = client.post(
        "/events",
        headers=auth_headers(token),
        json={"type": "food", "start_time": datetime.now(timezone.utc).isoformat()},
    )
    client.post(
        f"/events/{created.json()['id']}/finalize",
        headers=auth_headers(token),
        json={"details": "puree"},
    )

    updated = client.patch(
        f"/events/{created.json()['id']}",
        headers=auth_headers(token),
        json={"details": "puree + yogurt"},
    )
    assert updated.status_code == 200

    fake_service = main.get_calendar_service()
    assert len(fake_service.created_events) == 1
    assert len(fake_service.updated_events) == 1
    assert fake_service.updated_events[0]["details"] == "puree + yogurt"


def test_delete_events_for_day_is_user_scoped_and_removes_calendar_events(client: TestClient):
    first = register(client, "cleanup-user", "secret123")
    second = register(client, "other-user", "secret123")
    first_headers = auth_headers(first["token"])
    second_headers = auth_headers(second["token"])

    client.post("/calendar/enable-sync", headers=first_headers)

    today = datetime.now(timezone.utc).date().isoformat()
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

    today_event = client.post(
        "/events",
        headers=first_headers,
        json={"type": "bottle", "start_time": datetime.now(timezone.utc).isoformat()},
    )
    client.post(
        f"/events/{today_event.json()['id']}/finalize",
        headers=first_headers,
        json={"details": "delete me"},
    )

    client.post(
        "/events",
        headers=first_headers,
        json={"type": "food", "start_time": f"{yesterday}T10:00:00+00:00"},
    )
    client.post(
        "/events",
        headers=second_headers,
        json={"type": "sleep", "start_time": f"{today}T08:00:00+00:00", "end_time": f"{today}T09:00:00+00:00", "duration": 3600},
    )

    deleted = client.delete(f"/events/day?target_date={today}&time_zone=UTC", headers=first_headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted_count"] == 1

    first_events = client.get("/events", headers=first_headers)
    second_events = client.get("/events", headers=second_headers)
    assert len(first_events.json()) == 1
    assert first_events.json()[0]["start_time"].startswith(yesterday)
    assert len(second_events.json()) == 1

    fake_service = main.get_calendar_service()
    assert len(fake_service.deleted_events) == 1
    assert fake_service.deleted_events[0]["calendar_id"] == "calendar-1"


def test_simulate_day_replaces_selected_day_and_syncs_sample_events(client: TestClient):
    data = register(client, "sim-user", "secret123", baby_name="Demo")
    headers = auth_headers(data["token"])
    client.post("/calendar/enable-sync", headers=headers)

    target_date = "2026-04-02"
    existing = client.post(
        "/events",
        headers=headers,
        json={"type": "help", "start_time": f"{target_date}T07:00:00+00:00"},
    )
    client.post(
        f"/events/{existing.json()['id']}/finalize",
        headers=headers,
        json={"details": "old event"},
    )

    simulated = client.post(
        f"/events/simulate-day?target_date={target_date}&time_zone=America/Los_Angeles",
        headers=headers,
    )
    assert simulated.status_code == 200
    payload = simulated.json()
    assert payload["target_date"] == target_date
    assert payload["deleted_count"] == 1
    assert payload["created_count"] == 12
    assert payload["synced_to_calendar"] is True

    fake_service = main.get_calendar_service()
    assert len(fake_service.deleted_events) == 1
    assert len(fake_service.created_events) == 13

    pacific = ZoneInfo("America/Los_Angeles")
    earliest_event = min(fake_service.created_events[1:], key=lambda event: event["start_time"])
    latest_event = max(fake_service.created_events[1:], key=lambda event: event["start_time"])
    assert main._ensure_utc(earliest_event["start_time"]).astimezone(pacific).date().isoformat() == target_date
    assert main._ensure_utc(latest_event["start_time"]).astimezone(pacific).date().isoformat() == target_date


def test_delete_events_for_day_uses_local_timezone_boundaries(client: TestClient):
    data = register(client, "tz-user", "secret123")
    headers = auth_headers(data["token"])

    local_day = "2026-04-02"
    client.post(
        "/events",
        headers=headers,
        json={"type": "food", "start_time": "2026-04-02T06:30:00+00:00"},
    )
    client.post(
        "/events",
        headers=headers,
        json={"type": "food", "start_time": "2026-04-02T08:00:00+00:00"},
    )

    deleted = client.delete(
        f"/events/day?target_date={local_day}&time_zone=America/Los_Angeles",
        headers=headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted_count"] == 1

    remaining = client.get("/events", headers=headers)
    assert len(remaining.json()) == 1
    assert remaining.json()[0]["start_time"].startswith("2026-04-02T06:30:00")


def test_unauthenticated_requests_are_rejected(client: TestClient):
    response = client.get("/events")
    assert response.status_code == 401
