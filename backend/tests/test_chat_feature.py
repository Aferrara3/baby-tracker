import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import main


class FakeCalendarService:
    def create_event_from_baby_event(self, event, calendar_id=None):  # pragma: no cover - unused helper
        return {"id": "fake-event", "summary": getattr(event, "title", None), "updated": datetime.now(timezone.utc).isoformat()}

    def update_event_from_baby_event(self, calendar_event_id, event, calendar_id=None):  # pragma: no cover - unused helper
        return {"id": calendar_event_id, "summary": getattr(event, "title", None), "updated": datetime.now(timezone.utc).isoformat()}

    def list_event_changes(self, calendar_id=None, sync_token=None):  # pragma: no cover - unused helper
        return {"items": [], "next_sync_token": sync_token or "sync-token-empty", "full_sync": sync_token is None}


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


def register(client: TestClient, username: str, password: str):
    response = client.post("/auth/register", json={"username": username, "password": password, "share_emails": []})
    assert response.status_code == 200
    return response.json()


def create_event(client: TestClient, token: str, *, event_type: str, details: str | None = None, start_time: str | None = None):
    response = client.post(
        "/events",
        headers=auth_headers(token),
        json={
            "type": event_type,
            "start_time": start_time or datetime.now(timezone.utc).isoformat(),
            "details": details,
        },
    )
    assert response.status_code == 200
    return response.json()


def ready_status():
    return main.chat_service.ChatReadiness(ready=True, provider="ollama", model="gemma3:latest", detail=None)


def test_chat_readiness_requires_auth(client: TestClient):
    response = client.get("/chat/readiness")

    assert response.status_code == 401


def test_chat_query_rejects_irrelevant_requests(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    auth = register(client, "chat-irrelevant", "secret123")

    monkeypatch.setattr(main.chat_service, "chat_readiness_status", ready_status)
    monkeypatch.setattr(
        main.chat_service,
        "classify_request",
        lambda **kwargs: main.chat_service.ChatDecision(decision="deny_irrelevant", reason="Not about app data."),
    )

    response = client.post(
        "/chat/query",
        headers=auth_headers(auth["token"]),
        json={"messages": [{"role": "user", "content": "hello there"}], "time_zone": "UTC"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert "tracked data" in response.json()["reply"].lower()


def test_chat_query_scopes_sql_to_signed_in_account(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    first_account = register(client, "chat-owner", "secret123")
    second_account = register(client, "chat-other", "secret123")

    create_event(client, first_account["token"], event_type="bottle", details="4 oz formula")
    create_event(client, first_account["token"], event_type="bottle", details=None)
    create_event(client, second_account["token"], event_type="bottle", details="9 oz formula")

    monkeypatch.setattr(main.chat_service, "chat_readiness_status", ready_status)
    monkeypatch.setattr(
        main.chat_service,
        "classify_request",
        lambda **kwargs: main.chat_service.ChatDecision(decision="allow", reason="Allowed."),
    )
    monkeypatch.setattr(main.chat_service, "try_deterministic_answer", lambda **kwargs: None)
    monkeypatch.setattr(
        main.chat_service,
        "generate_sql_query",
        lambda **kwargs: "SELECT ROUND(SUM(COALESCE(extract_ounces(details), 1)), 2) AS total_oz FROM scoped_events WHERE type = 'bottle'",
    )
    monkeypatch.setattr(
        main.chat_service,
        "synthesize_answer",
        lambda **kwargs: f"Total ounces: {kwargs['rows'][0]['total_oz']}",
    )

    response = client.post(
        "/chat/query",
        headers=auth_headers(first_account["token"]),
        json={"messages": [{"role": "user", "content": "How many oz did the baby eat?"}], "time_zone": "UTC"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert response.json()["reply"] == "Total ounces: 5.0"


def test_chat_query_rejects_unsafe_sql(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    auth = register(client, "chat-unsafe-sql", "secret123")

    monkeypatch.setattr(main.chat_service, "chat_readiness_status", ready_status)
    monkeypatch.setattr(
        main.chat_service,
        "classify_request",
        lambda **kwargs: main.chat_service.ChatDecision(decision="allow", reason="Allowed."),
    )
    monkeypatch.setattr(main.chat_service, "try_deterministic_answer", lambda **kwargs: None)
    monkeypatch.setattr(main.chat_service, "generate_sql_query", lambda **kwargs: "SELECT * FROM event")

    response = client.post(
        "/chat/query",
        headers=auth_headers(auth["token"]),
        json={"messages": [{"role": "user", "content": "Show me every event table row"}], "time_zone": "UTC"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert "safely" in response.json()["reply"].lower()


def test_execute_scoped_chat_sql_normalizes_common_non_sqlite_patterns(client: TestClient):
    auth = register(client, "chat-sqlite-fix", "secret123")
    create_event(client, auth["token"], event_type="diaper_poop", details="Messy diaper")
    create_event(client, auth["token"], event_type="diaper_poop", details="Another diaper")

    rows = main.chat_service.execute_scoped_chat_sql(
        engine=main.engine,
        account_id=auth["account"]["id"],
        sql=(
            "SELECT COUNT(*) AS poop_count "
            "FROM scoped_events "
            "WHERE event_type = 'diaper_poop' "
            "AND local_date BETWEEN current_user_local_date() - INTERVAL 7 DAY AND current_user_local_date()"
        ),
        time_zone=main.chat_service._resolve_time_zone("UTC"),
    )

    assert rows == [{"poop_count": 2}]


def test_chat_followup_today_inherits_prior_poop_subject(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    auth = register(client, "chat-followup-poop", "secret123")
    now = datetime.now(timezone.utc)
    create_event(client, auth["token"], event_type="diaper_poop", start_time=now.isoformat())
    create_event(client, auth["token"], event_type="diaper_poop", start_time=(now - timedelta(days=1)).isoformat())

    monkeypatch.setattr(main.chat_service, "chat_readiness_status", ready_status)

    response = client.post(
        "/chat/query",
        headers=auth_headers(auth["token"]),
        json={
            "messages": [
                {"role": "assistant", "content": "Ask about your tracked data."},
                {"role": "user", "content": "How many times did my baby poop in the last 7 days?"},
                {"role": "assistant", "content": "The baby pooped 2 times in the last 7 days."},
                {"role": "user", "content": "Just today"},
            ],
            "time_zone": "UTC",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert response.json()["reply"] == "The baby pooped 1 time today."


def test_chat_nursing_yesterday_uses_requested_day(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    auth = register(client, "chat-followup-nursing", "secret123")
    now = datetime.now(timezone.utc)
    create_event(client, auth["token"], event_type="breastfeeding", start_time=now.isoformat())
    create_event(
        client,
        auth["token"],
        event_type="breastfeeding",
        start_time=(now - timedelta(days=1)).isoformat(),
    )

    with main.Session(main.engine) as session:
        events = session.exec(main.select(main.Event).where(main.Event.account_id == auth["account"]["id"])).all()
        for event in events:
            event_start = event.start_time.replace(tzinfo=timezone.utc) if event.start_time.tzinfo is None else event.start_time
            if event_start.date() == now.date():
                event.duration = 3600
            else:
                event.duration = 1800
            session.add(event)
        session.commit()

    monkeypatch.setattr(main.chat_service, "chat_readiness_status", ready_status)

    response = client.post(
        "/chat/query",
        headers=auth_headers(auth["token"]),
        json={
            "messages": [
                {"role": "assistant", "content": "Ask about your tracked data."},
                {"role": "user", "content": "How much time was spent nursing yesterday?"},
            ],
            "time_zone": "UTC",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert response.json()["reply"] == "The baby spent 30 minutes nursing yesterday."


def test_chat_nursing_weekly_breakdown_uses_grouped_daily_response(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    auth = register(client, "chat-nursing-breakdown", "secret123")
    now = datetime.now(timezone.utc)
    create_event(client, auth["token"], event_type="breastfeeding", start_time=now.isoformat())
    create_event(client, auth["token"], event_type="breastfeeding", start_time=(now - timedelta(days=1)).isoformat())

    with main.Session(main.engine) as session:
        events = session.exec(main.select(main.Event).where(main.Event.account_id == auth["account"]["id"])).all()
        for event in events:
            event_start = event.start_time.replace(tzinfo=timezone.utc) if event.start_time.tzinfo is None else event.start_time
            if event_start.date() == now.date():
                event.duration = 3600
            else:
                event.duration = 1800
            session.add(event)
        session.commit()

    monkeypatch.setattr(main.chat_service, "chat_readiness_status", ready_status)

    response = client.post(
        "/chat/query",
        headers=auth_headers(auth["token"]),
        json={
            "messages": [
                {"role": "assistant", "content": "Ask about your tracked data."},
                {"role": "user", "content": "How much time was spent nursing so far today?"},
                {"role": "assistant", "content": "The baby spent 1 hour nursing today."},
                {"role": "user", "content": "Give me a daily breakdown for past week"},
            ],
            "time_zone": "UTC",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert "daily nursing breakdown in the last 7 days" in response.json()["reply"]
    assert "- " in response.json()["reply"]


def test_chat_followup_day_before_advances_relative_day_scope(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    auth = register(client, "chat-day-before", "secret123")
    now = datetime.now(timezone.utc)
    create_event(client, auth["token"], event_type="breastfeeding", start_time=(now - timedelta(days=1)).isoformat())
    create_event(client, auth["token"], event_type="breastfeeding", start_time=(now - timedelta(days=2)).isoformat())

    with main.Session(main.engine) as session:
        events = session.exec(main.select(main.Event).where(main.Event.account_id == auth["account"]["id"])).all()
        for event in events:
            event_start = event.start_time.replace(tzinfo=timezone.utc) if event.start_time.tzinfo is None else event.start_time
            if event_start.date() == (now - timedelta(days=1)).date():
                event.duration = 1800
            else:
                event.duration = 900
            session.add(event)
        session.commit()

    monkeypatch.setattr(main.chat_service, "chat_readiness_status", ready_status)

    response = client.post(
        "/chat/query",
        headers=auth_headers(auth["token"]),
        json={
            "messages": [
                {"role": "assistant", "content": "Ask about your tracked data."},
                {"role": "user", "content": "How much time was spent nursing yesterday?"},
                {"role": "assistant", "content": "The baby spent 30 minutes nursing yesterday."},
                {"role": "user", "content": "day before"},
            ],
            "time_zone": "UTC",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert response.json()["reply"] == "The baby spent 15 minutes nursing the day before yesterday."
