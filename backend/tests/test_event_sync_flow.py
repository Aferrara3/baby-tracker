import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
        self.sync_responses: list[dict] = []
        self.create_failures: list[Exception] = []
        self.update_failures: list[Exception] = []
        self.delete_failures: list[Exception] = []
        self.sync_failures: list[Exception] = []

    def create_event_from_baby_event(self, event, calendar_id=None) -> dict:
        if self.create_failures:
            raise self.create_failures.pop(0)
        payload = {
            "id": f"event-{len(self.created_events) + 1}",
            "calendar_id": calendar_id,
            "type": event.type,
            "summary": getattr(event, "title", None) or main.activity_label(event.type),
            "description": getattr(event, "google_description", None),
            "start_time": event.start_time,
            "start": {"dateTime": event.start_time.isoformat()},
            "end_time": event.end_time,
            "end": {"dateTime": event.end_time.isoformat()} if event.end_time else None,
            "duration": event.duration,
            "details": event.details,
            "etag": f"etag-{len(self.created_events) + 1}",
            "updated": datetime.now(timezone.utc).isoformat(),
        }
        self.created_events.append(payload)
        return payload

    def update_event_from_baby_event(self, calendar_event_id, event, calendar_id=None) -> dict:
        if self.update_failures:
            raise self.update_failures.pop(0)
        payload = {
            "id": calendar_event_id,
            "calendar_id": calendar_id,
            "type": event.type,
            "summary": getattr(event, "title", None) or main.activity_label(event.type),
            "description": getattr(event, "google_description", None),
            "details": event.details,
            "etag": f"etag-update-{len(self.updated_events) + 1}",
            "updated": datetime.now(timezone.utc).isoformat(),
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
        if self.delete_failures:
            raise self.delete_failures.pop(0)
        self.deleted_events.append(
            {
                "id": calendar_event_id,
                "calendar_id": calendar_id,
            }
        )

    def list_event_changes(self, calendar_id=None, sync_token=None) -> dict:
        if self.sync_failures:
            raise self.sync_failures.pop(0)
        if self.sync_responses:
            response = self.sync_responses.pop(0)
            return {
                "items": response.get("items", []),
                "next_sync_token": response.get("next_sync_token"),
                "full_sync": response.get("full_sync", sync_token is None),
            }
        return {
            "items": [],
            "next_sync_token": sync_token or "sync-token-empty",
            "full_sync": sync_token is None,
        }


@pytest.fixture()
def client(tmp_path):
    database_path = tmp_path / "test.db"
    custom_icon_dir = tmp_path / "custom-icons"
    test_engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})

    old_engine = main.engine
    old_service = main._calendar_service
    old_worker_enabled = main._calendar_sync_worker_enabled
    old_custom_icon_storage_dir = main.CUSTOM_ICON_STORAGE_DIR

    main.engine = test_engine
    main._calendar_service = FakeCalendarService()
    main._calendar_sync_worker_enabled = False
    main.CUSTOM_ICON_STORAGE_DIR = custom_icon_dir
    main._stop_calendar_sync_worker()
    main._prepare_custom_icon_storage()

    SQLModel.metadata.create_all(main.engine)
    main._ensure_account_columns()
    main._ensure_event_columns()

    with TestClient(main.app) as test_client:
        yield test_client

    main.engine = old_engine
    main._calendar_service = old_service
    main._calendar_sync_worker_enabled = old_worker_enabled
    main.CUSTOM_ICON_STORAGE_DIR = old_custom_icon_storage_dir
    main._stop_calendar_sync_worker()


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


def drain_calendar_jobs() -> None:
    for _ in range(20):
        if main._process_calendar_sync_jobs(limit=50) == 0:
            return
    raise AssertionError("calendar sync queue did not drain in time")


def make_all_calendar_jobs_due() -> None:
    with Session(main.engine) as session:
        jobs = session.exec(select(main.CalendarSyncJob)).all()
        for job in jobs:
            job.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.add(job)
        session.commit()


def test_register_returns_session_and_profile(client: TestClient):
    data = register(client, "parent1", "secret123", baby_name="Ava")

    assert data["token"]
    assert data["account"]["username"] == "parent1"
    assert data["account"]["baby_name"] == "Ava"
    assert data["account"]["color_palette"] == "default"

    me = client.get("/auth/me", headers=auth_headers(data["token"]))
    assert me.status_code == 200
    assert me.json()["username"] == "parent1"


def test_tracker_buttons_endpoint_returns_seeded_defaults(client: TestClient):
    data = register(client, "buttons-defaults", "secret123")

    response = client.get("/tracker-buttons", headers=auth_headers(data["token"]))

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["buttons"]) == 8
    assert {button["id"] for button in payload["buttons"]} == {
        "bottle",
        "food",
        "diaper_pee",
        "diaper_poop",
        "sleep",
        "breastfeeding",
        "pump",
        "help",
    }
    assert any(symbol["key"] == "dumbbell" for symbol in payload["available_symbols"])
    assert payload["buttons"][0]["title"] == "🍼 Bottle"


def test_custom_icons_are_created_and_listed_in_tracker_symbols(client: TestClient):
    data = register(client, "custom-icons", "secret123")
    headers = auth_headers(data["token"])

    response = client.post(
        "/custom-icons",
        headers=headers,
        data={
            "label": "Pizza Slice",
            "emoji": "🍕",
            "keywords": "pizza,dinner,food",
            "is_public": "true",
        },
        files={"asset": ("pizza.png", b"fake-png", "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["key"].startswith("custom:")
    assert payload["icon_kind"] == "custom"
    assert payload["image_url"].startswith("/custom-icons/assets/")
    assert payload["is_public"] is True

    tracker_buttons = client.get("/tracker-buttons", headers=headers)
    assert tracker_buttons.status_code == 200
    available_symbols = tracker_buttons.json()["available_symbols"]
    created_symbol = next(symbol for symbol in available_symbols if symbol["key"] == payload["key"])
    assert created_symbol["label"] == "Pizza Slice"
    assert created_symbol["emoji"] == "🍕"
    assert created_symbol["icon_kind"] == "custom"

    asset_response = client.get(payload["image_url"])
    assert asset_response.status_code == 200
    assert asset_response.content == b"fake-png"


def test_custom_icon_rejects_non_emoji_calendar_value(client: TestClient):
    data = register(client, "custom-icons-invalid", "secret123")
    headers = auth_headers(data["token"])

    response = client.post(
        "/custom-icons",
        headers=headers,
        data={
            "label": "Not Valid",
            "emoji": "ambulance",
        },
        files={"asset": ("pizza.png", b"fake-png", "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Custom icon emoji must be a valid emoji"


def test_custom_icon_rejects_svg_uploads(client: TestClient):
    data = register(client, "custom-icons-svg", "secret123")
    headers = auth_headers(data["token"])

    response = client.post(
        "/custom-icons",
        headers=headers,
        data={
            "label": "Pizza Slice",
            "emoji": "🍕",
        },
        files={"asset": ("pizza.svg", b"<svg></svg>", "image/svg+xml")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Custom icons must be uploaded as PNG"


def test_deleting_custom_icon_removes_it_and_falls_back_existing_buttons(client: TestClient):
    data = register(client, "custom-icons-delete", "secret123")
    headers = auth_headers(data["token"])

    created = client.post(
        "/custom-icons",
        headers=headers,
        data={
            "label": "Penne",
            "emoji": "🍝",
        },
        files={"asset": ("penne.png", b"fake-png", "image/png")},
    )
    assert created.status_code == 200
    created_symbol = created.json()
    custom_icon_id = int(created_symbol["key"].removeprefix("custom:"))

    existing_buttons = client.get("/tracker-buttons", headers=headers)
    assert existing_buttons.status_code == 200
    buttons_payload = existing_buttons.json()["buttons"]
    buttons_payload[0]["icon_key"] = created_symbol["key"]

    saved = client.patch("/tracker-buttons", headers=headers, json={"buttons": buttons_payload})
    assert saved.status_code == 200
    assert saved.json()["buttons"][0]["icon_key"] == created_symbol["key"]

    deleted = client.delete(f"/custom-icons/{custom_icon_id}", headers=headers)
    assert deleted.status_code == 200

    refreshed = client.get("/tracker-buttons", headers=headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["buttons"][0]["icon_key"] == "help-circle"
    assert all(symbol["key"] != created_symbol["key"] for symbol in refreshed.json()["available_symbols"])


def test_tracker_buttons_accept_multiple_pages(client: TestClient):
    data = register(client, "paged-buttons", "secret123")
    token = data["token"]

    existing = client.get("/tracker-buttons", headers=auth_headers(token))
    assert existing.status_code == 200

    second_page = [
        {
            "id": "medicine",
            "label": "Medicine",
            "icon_key": "pill-bottle",
            "color_key": "rose",
            "position": 8,
        },
        {
            "id": "temperature",
            "label": "Temp",
            "icon_key": "thermometer",
            "color_key": "amber",
            "position": 9,
        },
        {
            "id": "bath",
            "label": "Bath",
            "icon_key": "bath",
            "color_key": "cyan",
            "position": 10,
        },
        {
            "id": "outside",
            "label": "Outside",
            "icon_key": "leaf",
            "color_key": "blue",
            "position": 11,
        },
        {
            "id": "tummy_time",
            "label": "Tummy",
            "icon_key": "baby",
            "color_key": "pink",
            "position": 12,
        },
        {
            "id": "play",
            "label": "Play",
            "icon_key": "gamepad-2",
            "color_key": "indigo",
            "position": 13,
        },
        {
            "id": "doctor",
            "label": "Doctor",
            "icon_key": "stethoscope",
            "color_key": "orange",
            "position": 14,
        },
        {
            "id": "notes",
            "label": "Notes",
            "icon_key": "notebook-pen",
            "color_key": "slate",
            "position": 15,
        },
    ]

    saved = client.patch(
        "/tracker-buttons",
        headers=auth_headers(token),
        json={"buttons": existing.json()["buttons"] + second_page},
    )
    assert saved.status_code == 200
    assert len(saved.json()["buttons"]) == 16
    assert saved.json()["buttons"][8]["id"] == "medicine"


def test_tracker_buttons_reject_more_than_three_pages(client: TestClient):
    data = register(client, "too-many-pages", "secret123")
    token = data["token"]

    page_one = client.get("/tracker-buttons", headers=auth_headers(token)).json()["buttons"]
    page_two = [
        {"id": "medicine", "label": "Medicine", "icon_key": "pill-bottle", "color_key": "rose", "position": 8},
        {"id": "temperature", "label": "Temp", "icon_key": "thermometer", "color_key": "amber", "position": 9},
        {"id": "bath", "label": "Bath", "icon_key": "bath", "color_key": "cyan", "position": 10},
        {"id": "outside", "label": "Outside", "icon_key": "leaf", "color_key": "blue", "position": 11},
        {"id": "tummy_time", "label": "Tummy", "icon_key": "baby", "color_key": "pink", "position": 12},
        {"id": "play", "label": "Play", "icon_key": "gamepad-2", "color_key": "indigo", "position": 13},
        {"id": "doctor", "label": "Doctor", "icon_key": "stethoscope", "color_key": "orange", "position": 14},
        {"id": "notes", "label": "Notes", "icon_key": "notebook-pen", "color_key": "slate", "position": 15},
    ]
    page_three = [
        {"id": f"extra_page_3_{index + 1}", "label": f"Other {index + 1}", "icon_key": "help-circle", "color_key": "slate", "position": 16 + index}
        for index in range(8)
    ]
    page_four = [
        {"id": f"extra_page_4_{index + 1}", "label": f"Other {index + 1}", "icon_key": "help-circle", "color_key": "slate", "position": 24 + index}
        for index in range(8)
    ]

    response = client.patch(
        "/tracker-buttons",
        headers=auth_headers(token),
        json={"buttons": page_one + page_two + page_three + page_four},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Tracker buttons are limited to 3 pages"


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
    assert datetime.fromisoformat(start_one.json()["start_time"]).tzinfo is not None
    assert datetime.fromisoformat(stop_one.json()["end_time"]).tzinfo is not None


def test_multiple_activity_timers_can_run_concurrently_for_one_account(client: TestClient):
    data = register(client, "multi-timer", "secret123")
    headers = auth_headers(data["token"])

    sleep_start = client.post("/activities/start", headers=headers, json={"type": "sleep"})
    bottle_start = client.post("/activities/start", headers=headers, json={"type": "bottle"})

    assert sleep_start.status_code == 200
    assert bottle_start.status_code == 200
    assert sleep_start.json()["status"] == "success"
    assert bottle_start.json()["status"] == "success"

    events = client.get("/events", headers=headers)
    payload = events.json()
    active_types = {event["type"] for event in payload if event["is_active"]}
    assert active_types == {"sleep", "bottle"}

    sleep_stop = client.post("/activities/stop", headers=headers, json={"type": "sleep"})
    assert sleep_stop.status_code == 200
    assert sleep_stop.json()["status"] == "success"

    after_first_stop = client.get("/events", headers=headers).json()
    sleep_event = next(event for event in after_first_stop if event["id"] == sleep_stop.json()["event_id"])
    bottle_event = next(event for event in after_first_stop if event["type"] == "bottle")
    assert sleep_event["is_active"] is False
    assert sleep_event["end_time"] is not None
    assert bottle_event["is_active"] is True

    bottle_stop = client.post("/activities/stop", headers=headers, json={"type": "bottle"})
    assert bottle_stop.status_code == 200
    assert bottle_stop.json()["status"] == "success"


def test_active_activities_endpoint_only_returns_current_account_active_timers(client: TestClient):
    account_one = register(client, "active-timer-1", "secret123")
    account_two = register(client, "active-timer-2", "secret123")

    headers_one = auth_headers(account_one["token"])
    headers_two = auth_headers(account_two["token"])

    sleep_start = client.post("/activities/start", headers=headers_one, json={"type": "sleep"})
    bottle_start = client.post("/activities/start", headers=headers_one, json={"type": "bottle"})
    assert sleep_start.status_code == 200
    assert bottle_start.status_code == 200

    stopped = client.post("/activities/stop", headers=headers_one, json={"type": "sleep"})
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "success"

    other_start = client.post("/activities/start", headers=headers_two, json={"type": "diaper"})
    assert other_start.status_code == 200

    response = client.get("/activities/active", headers=headers_one)
    assert response.status_code == 200
    payload = response.json()

    assert [event["type"] for event in payload] == ["bottle"]
    assert payload[0]["is_active"] is True
    assert payload[0]["end_time"] is None


def test_stop_syncs_started_timer_and_finalize_updates_same_calendar_event(client: TestClient):
    data = register(client, "timer-sync", "secret123")
    headers = auth_headers(data["token"])
    enabled = client.post("/calendar/enable-sync", headers=headers)
    assert enabled.status_code == 200

    started = client.post("/activities/start", headers=headers, json={"type": "sleep"})
    assert started.status_code == 200
    assert started.json()["status"] == "success"

    active_events = client.get("/events", headers=headers)
    assert active_events.status_code == 200
    active_event = active_events.json()[0]
    assert active_event["is_active"] is True
    assert active_event["end_time"] is None

    stopped = client.post("/activities/stop", headers=headers, json={"type": "sleep"})
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "success"
    assert stopped.json()["calendar_sync_state"] == "queued"

    fake_service = main.get_calendar_service()
    assert fake_service.created_events == []

    finalized = client.post(
        f"/events/{stopped.json()['event_id']}/finalize",
        headers=headers,
        json={"details": "solid nap"},
    )
    assert finalized.status_code == 200
    assert finalized.json()["calendar_sync_state"] == "queued"

    drain_calendar_jobs()

    assert len(fake_service.created_events) == 1
    assert fake_service.created_events[0]["type"] == "sleep"
    assert fake_service.created_events[0]["details"] == "solid nap"
    assert fake_service.updated_events == []


def test_enable_sync_provisions_calendar_and_shares_to_saved_emails(client: TestClient):
    data = register(client, "calendar-user", "secret123")
    token = data["token"]

    settings = client.patch(
        "/account/settings",
        headers=auth_headers(token),
        json={"baby_name": "Milo", "share_emails": ["mom@example.com", "dad@example.com"]},
    )
    assert settings.status_code == 200

    enabled = client.post(
        "/calendar/enable-sync",
        headers=auth_headers(token),
        json={"time_zone": "America/Los_Angeles"},
    )
    assert enabled.status_code == 200
    payload = enabled.json()

    assert payload["service_managed_calendar"] is True
    assert payload["google_calendar_id"] == "calendar-1"
    assert payload["google_calendar_summary"] == "Baby Tracker - Milo"

    fake_service = main.get_calendar_service()
    assert len(fake_service.created_calendars) == 1
    assert fake_service.created_calendars[0]["timeZone"] == "America/Los_Angeles"
    assert {row["email"] for row in fake_service.shared_calendars} == {"mom@example.com", "dad@example.com"}


def test_account_settings_persist_color_palette(client: TestClient):
    data = register(client, "palette-user", "secret123")
    token = data["token"]

    updated = client.patch(
        "/account/settings",
        headers=auth_headers(token),
        json={"color_palette": "meadow"},
    )
    assert updated.status_code == 200
    assert updated.json()["color_palette"] == "meadow"

    me = client.get("/auth/me", headers=auth_headers(token))
    assert me.status_code == 200
    assert me.json()["color_palette"] == "meadow"


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
    assert finalized.json()["calendar_sync_state"] == "queued"

    fake_service = main.get_calendar_service()
    assert fake_service.created_events == []
    drain_calendar_jobs()
    assert len(fake_service.created_events) == 1
    assert fake_service.created_events[0]["calendar_id"] == "calendar-1"
    assert fake_service.created_events[0]["details"] == "4 oz formula"


def test_custom_tracker_button_changes_event_and_calendar_title(client: TestClient):
    data = register(client, "custom-buttons-user", "secret123")
    headers = auth_headers(data["token"])
    client.post("/calendar/enable-sync", headers=headers)

    existing_buttons = client.get("/tracker-buttons", headers=headers)
    assert existing_buttons.status_code == 200
    buttons_payload = existing_buttons.json()["buttons"]

    updated_buttons = []
    for button in buttons_payload:
        if button["id"] == "bottle":
            updated_buttons.append(
                {
                    "id": button["id"],
                    "label": "Workout",
                    "icon_key": "dumbbell",
                    "color_key": button["color_key"],
                    "position": button["position"],
                    "emoji_override": "💪",
                }
            )
        else:
            updated_buttons.append(
                {
                    "id": button["id"],
                    "label": button["label"],
                    "icon_key": button["icon_key"],
                    "color_key": button["color_key"],
                    "position": button["position"],
                    "emoji_override": button.get("emoji_override"),
                }
            )

    saved = client.patch("/tracker-buttons", headers=headers, json={"buttons": updated_buttons})
    assert saved.status_code == 200
    assert next(button for button in saved.json()["buttons"] if button["id"] == "bottle")["title"] == "💪 Workout"

    created = client.post(
        "/events",
        headers=headers,
        json={"type": "bottle", "start_time": datetime.now(timezone.utc).isoformat()},
    )
    assert created.status_code == 200
    assert created.json()["title"] == "💪 Workout"

    finalized = client.post(
        f"/events/{created.json()['id']}/finalize",
        headers=headers,
        json={"details": "customized"},
    )
    assert finalized.status_code == 200
    assert finalized.json()["title"] == "💪 Workout"

    fake_service = main.get_calendar_service()
    drain_calendar_jobs()
    assert fake_service.created_events[-1]["summary"] == "💪 Workout"


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


def test_enable_sync_updates_existing_service_managed_calendar_time_zone(client: TestClient):
    data = register(client, "timezone-user", "secret123", baby_name="Milo")
    token = data["token"]

    enabled = client.post(
        "/calendar/enable-sync",
        headers=auth_headers(token),
        json={"time_zone": "UTC"},
    )
    assert enabled.status_code == 200

    updated = client.post(
        "/calendar/enable-sync",
        headers=auth_headers(token),
        json={"time_zone": "America/New_York"},
    )
    assert updated.status_code == 200

    fake_service = main.get_calendar_service()
    assert fake_service.updated_calendars[-1]["id"] == "calendar-1"
    assert fake_service.updated_calendars[-1]["timeZone"] == "America/New_York"


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
    drain_calendar_jobs()

    updated = client.patch(
        f"/events/{created.json()['id']}",
        headers=auth_headers(token),
        json={"details": "puree + yogurt"},
    )
    assert updated.status_code == 200
    assert updated.json()["calendar_sync_state"] == "queued"

    drain_calendar_jobs()

    fake_service = main.get_calendar_service()
    assert len(fake_service.created_events) == 1
    assert len(fake_service.updated_events) == 1
    assert fake_service.updated_events[0]["details"] == "puree + yogurt"


def test_delete_single_event_removes_synced_google_event(client: TestClient):
    data = register(client, "undo-user", "secret123")
    headers = auth_headers(data["token"])
    client.post("/calendar/enable-sync", headers=headers)

    created = client.post(
        "/events",
        headers=headers,
        json={"type": "food", "start_time": datetime.now(timezone.utc).isoformat()},
    )
    assert created.status_code == 200

    finalized = client.post(
        f"/events/{created.json()['id']}/finalize",
        headers=headers,
        json={"details": "temporary"},
    )
    assert finalized.status_code == 200
    drain_calendar_jobs()

    deleted = client.delete(f"/events/{created.json()['id']}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "success"

    remaining = client.get("/events", headers=headers)
    assert remaining.status_code == 200
    assert remaining.json() == []

    fake_service = main.get_calendar_service()
    assert fake_service.deleted_events == []
    drain_calendar_jobs()
    assert len(fake_service.deleted_events) == 1
    assert fake_service.deleted_events[0]["calendar_id"] == "calendar-1"


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
    drain_calendar_jobs()

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
    assert fake_service.deleted_events == []
    drain_calendar_jobs()
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
    drain_calendar_jobs()

    simulated = client.post(
        f"/events/simulate-day?target_date={target_date}&time_zone=America/Los_Angeles",
        headers=headers,
    )
    assert simulated.status_code == 200
    payload = simulated.json()
    assert payload["target_date"] == target_date
    assert payload["deleted_count"] == 1
    assert payload["created_count"] == 12
    assert payload["synced_to_calendar"] is False
    assert payload["calendar_sync_state"] == "queued"

    fake_service = main.get_calendar_service()
    drain_calendar_jobs()
    assert len(fake_service.deleted_events) == 1
    assert len(fake_service.created_events) == 13

    pacific = ZoneInfo("America/Los_Angeles")
    earliest_event = min(fake_service.created_events[1:], key=lambda event: event["start_time"])
    latest_event = max(fake_service.created_events[1:], key=lambda event: event["start_time"])
    assert main._ensure_utc(earliest_event["start_time"]).astimezone(pacific).date().isoformat() == target_date
    assert main._ensure_utc(latest_event["start_time"]).astimezone(pacific).date().isoformat() == target_date


def test_simulate_day_uses_current_tracker_buttons(client: TestClient):
    data = register(client, "sim-custom-user", "secret123")
    headers = auth_headers(data["token"])
    client.post("/calendar/enable-sync", headers=headers)

    existing_buttons = client.get("/tracker-buttons", headers=headers)
    assert existing_buttons.status_code == 200
    updated_buttons = []
    for button in existing_buttons.json()["buttons"]:
        updated_buttons.append(
            {
                "id": button["id"],
                "label": "Workout" if button["id"] == "bottle" else button["label"],
                "icon_key": "dumbbell" if button["id"] == "bottle" else button["icon_key"],
                "color_key": button["color_key"],
                "position": button["position"],
            }
        )

    saved = client.patch("/tracker-buttons", headers=headers, json={"buttons": updated_buttons})
    assert saved.status_code == 200

    simulated = client.post(
        "/events/simulate-day?target_date=2026-04-03&time_zone=UTC",
        headers=headers,
    )
    assert simulated.status_code == 200
    assert simulated.json()["created_count"] == 12

    fake_service = main.get_calendar_service()
    drain_calendar_jobs()
    created_titles = {event["summary"] for event in fake_service.created_events}
    assert "🏋️ Workout" in created_titles


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


def test_google_sync_imports_remote_updates_and_new_events(client: TestClient):
    data = register(client, "google-sync-user", "secret123", baby_name="Sync Baby")
    headers = auth_headers(data["token"])
    client.post("/calendar/enable-sync", headers=headers)

    created = client.post(
        "/events",
        headers=headers,
        json={
            "type": "food",
            "start_time": "2026-04-02T15:00:00+00:00",
            "end_time": "2026-04-02T15:20:00+00:00",
            "duration": 1200,
        },
    )
    client.post(
        f"/events/{created.json()['id']}/finalize",
        headers=headers,
        json={"details": "original note"},
    )
    drain_calendar_jobs()

    fake_service = main.get_calendar_service()
    fake_service.sync_responses.append(
        {
            "full_sync": False,
            "next_sync_token": "sync-token-1",
            "items": [
                {
                    "id": "event-1",
                    "status": "confirmed",
                    "summary": "Night Sleep",
                    "description": "Notes: updated from google",
                    "start": {"dateTime": "2026-04-02T16:00:00+00:00"},
                    "end": {"dateTime": "2026-04-02T18:30:00+00:00"},
                    "etag": "etag-remote-1",
                    "updated": "2026-04-02T18:31:00+00:00",
                },
                {
                    "id": "google-new-1",
                    "status": "confirmed",
                    "summary": "🍼 Bottle",
                    "description": "Notes: created directly in google",
                    "start": {"dateTime": "2026-04-02T19:00:00+00:00"},
                    "end": {"dateTime": "2026-04-02T19:15:00+00:00"},
                    "etag": "etag-remote-2",
                    "updated": "2026-04-02T19:16:00+00:00",
                },
            ],
        }
    )

    synced = client.post("/calendar/sync", headers=headers)
    assert synced.status_code == 200
    payload = synced.json()
    assert payload["updated_count"] == 1
    assert payload["imported_count"] == 1
    assert payload["deleted_count"] == 0
    assert payload["next_sync_token"] == "sync-token-1"

    events = client.get("/events", headers=headers).json()
    updated_event = next(event for event in events if event["id"] == created.json()["id"])
    imported_event = next(event for event in events if event["title"] == "🍼 Bottle" and event["id"] != created.json()["id"])

    assert updated_event["title"] == "Night Sleep"
    assert updated_event["type"] == "food"
    assert updated_event["details"] == "updated from google"
    assert updated_event["start_time"].startswith("2026-04-02T16:00:00")

    assert imported_event["type"] == "bottle"
    assert imported_event["details"] == "created directly in google"

    me = client.get("/auth/me", headers=headers).json()
    assert me["google_last_sync_status"] == "ok"
    assert me["google_last_synced_at"] is not None


def test_google_sync_deletes_cancelled_remote_events(client: TestClient):
    data = register(client, "google-delete-user", "secret123")
    headers = auth_headers(data["token"])
    client.post("/calendar/enable-sync", headers=headers)

    created = client.post(
        "/events",
        headers=headers,
        json={"type": "sleep", "start_time": "2026-04-02T10:00:00+00:00", "end_time": "2026-04-02T11:00:00+00:00", "duration": 3600},
    )
    client.post(f"/events/{created.json()['id']}/finalize", headers=headers, json={})
    drain_calendar_jobs()

    fake_service = main.get_calendar_service()
    fake_service.sync_responses.append(
        {
            "full_sync": False,
            "next_sync_token": "sync-token-delete",
            "items": [
                {
                    "id": "event-1",
                    "status": "cancelled",
                }
            ],
        }
    )

    synced = client.post("/calendar/sync", headers=headers)
    assert synced.status_code == 200
    assert synced.json()["deleted_count"] == 1

    events = client.get("/events", headers=headers)
    assert events.json() == []


def test_google_sync_reassigns_type_when_title_matches_known_activity(client: TestClient):
    data = register(client, "google-title-user", "secret123")
    headers = auth_headers(data["token"])
    client.post("/calendar/enable-sync", headers=headers)

    created = client.post(
        "/events",
        headers=headers,
        json={"type": "help", "start_time": "2026-04-02T12:00:00+00:00"},
    )
    client.post(f"/events/{created.json()['id']}/finalize", headers=headers, json={})
    drain_calendar_jobs()

    fake_service = main.get_calendar_service()
    fake_service.sync_responses.append(
        {
            "full_sync": False,
            "next_sync_token": "sync-token-title",
            "items": [
                {
                    "id": "event-1",
                    "status": "confirmed",
                    "summary": "😴 Sleep",
                    "description": "Notes: retitled in google",
                    "start": {"dateTime": "2026-04-02T12:30:00+00:00"},
                    "end": {"dateTime": "2026-04-02T13:45:00+00:00"},
                    "etag": "etag-title",
                    "updated": "2026-04-02T13:46:00+00:00",
                }
            ],
        }
    )

    synced = client.post("/calendar/sync", headers=headers)
    assert synced.status_code == 200

    event = client.get("/events", headers=headers).json()[0]
    assert event["type"] == "sleep"
    assert event["title"] == "😴 Sleep"
    assert event["details"] == "retitled in google"


def test_google_pull_sync_transient_failure_returns_503_and_marks_status_error(client: TestClient):
    data = register(client, "google-pull-error-user", "secret123")
    headers = auth_headers(data["token"])
    client.post("/calendar/enable-sync", headers=headers)

    fake_service = main.get_calendar_service()
    fake_service.sync_failures.append(OSError("tls reset"))

    synced = client.post("/calendar/sync", headers=headers)
    assert synced.status_code == 503
    assert synced.json()["detail"] == "Google pull sync temporarily unavailable"

    me = client.get("/auth/me", headers=headers).json()
    assert me["google_last_sync_status"] == "error"


def test_transient_google_create_failure_keeps_event_saved_and_retries(client: TestClient):
    data = register(client, "retry-user", "secret123")
    headers = auth_headers(data["token"])
    client.post("/calendar/enable-sync", headers=headers)

    fake_service = main.get_calendar_service()
    fake_service.create_failures.append(OSError("tls reset"))

    created = client.post(
        "/events",
        headers=headers,
        json={"type": "food", "start_time": "2026-04-02T12:00:00+00:00"},
    )
    finalized = client.post(
        f"/events/{created.json()['id']}/finalize",
        headers=headers,
        json={"details": "queued first"},
    )
    assert finalized.status_code == 200
    assert finalized.json()["calendar_sync_state"] == "queued"

    drain_calendar_jobs()

    queued_event = client.get("/events", headers=headers).json()[0]
    assert queued_event["calendar_sync_state"] == "queued"
    assert queued_event["calendar_sync_message"] == "GCal update failed. Will auto-retry in background."
    assert fake_service.created_events == []

    make_all_calendar_jobs_due()
    drain_calendar_jobs()

    synced_event = client.get("/events", headers=headers).json()[0]
    assert synced_event["calendar_sync_state"] == "synced"
    assert len(fake_service.created_events) == 1
    assert fake_service.created_events[0]["details"] == "queued first"


def test_transient_google_delete_failure_keeps_event_hidden_until_retry_succeeds(client: TestClient):
    data = register(client, "retry-delete-user", "secret123")
    headers = auth_headers(data["token"])
    client.post("/calendar/enable-sync", headers=headers)

    created = client.post(
        "/events",
        headers=headers,
        json={"type": "sleep", "start_time": "2026-04-02T10:00:00+00:00"},
    )
    client.post(f"/events/{created.json()['id']}/finalize", headers=headers, json={})
    drain_calendar_jobs()

    fake_service = main.get_calendar_service()
    fake_service.delete_failures.append(OSError("tls reset"))

    deleted = client.delete(f"/events/{created.json()['id']}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/events", headers=headers).json() == []

    drain_calendar_jobs()

    with Session(main.engine) as session:
        stored_event = session.get(main.Event, created.json()["id"])
        assert stored_event is not None
        assert stored_event.deleted_at is not None

    make_all_calendar_jobs_due()
    drain_calendar_jobs()

    with Session(main.engine) as session:
        assert session.get(main.Event, created.json()["id"]) is None
    assert len(fake_service.deleted_events) == 1


def test_unauthenticated_requests_are_rejected(client: TestClient):
    response = client.get("/events")
    assert response.status_code == 401


def test_app_config_endpoint_returns_profile_copy_and_templates(client: TestClient):
    response = client.get("/app-config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile_id"] == "baby"
    assert payload["app_name"] == "Baby Tracker"
    assert payload["copy"]["settings_name_label"] == "Baby name"
    assert payload["button_templates"][0]["id"] == "bottle"
    assert any(symbol["key"] == "pizza" for symbol in payload["available_symbols"])


def test_habit_profile_changes_public_copy_defaults_and_calendar_summary(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    profile_path = Path(__file__).resolve().parents[2] / "app-profiles" / "habit-app-config.yaml"
    monkeypatch.setenv("APP_PROFILE_CONFIG_PATH", str(profile_path))

    app_config = client.get("/app-config")
    assert app_config.status_code == 200
    assert app_config.json()["app_name"] == "Habit Tracker"
    assert app_config.json()["copy"]["settings_name_label"] == "Habit name"

    root_response = client.get("/")
    assert root_response.status_code == 200
    assert root_response.json() == {"message": "Habit Tracker API is running"}

    data = register(client, "habit-user", "secret123", baby_name="Personal")
    buttons = client.get("/tracker-buttons", headers=auth_headers(data["token"]))
    assert buttons.status_code == 200
    assert buttons.json()["buttons"][0]["id"] == "poop"
    assert buttons.json()["buttons"][0]["title"] == "💩 Poop"

    enabled = client.post("/calendar/enable-sync", headers=auth_headers(data["token"]))
    assert enabled.status_code == 200
    assert enabled.json()["google_calendar_summary"] == "Habit Tracker - Personal"


def test_root_returns_status_without_frontend_dist(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FRONTEND_DIST_PATH", raising=False)

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Baby Tracker API is running"}


def test_root_serves_frontend_when_dist_is_configured(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html><body>baby tracker</body></html>", encoding="utf-8")
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir()
    (assets_dir / "app.js").write_text("console.log('baby');", encoding="utf-8")
    monkeypatch.setenv("FRONTEND_DIST_PATH", str(dist_dir))

    root_response = client.get("/")
    asset_response = client.get("/assets/app.js")
    spa_response = client.get("/settings")

    assert root_response.status_code == 200
    assert "baby tracker" in root_response.text
    assert asset_response.status_code == 200
    assert "console.log('baby');" in asset_response.text
    assert spa_response.status_code == 200
    assert "baby tracker" in spa_response.text
