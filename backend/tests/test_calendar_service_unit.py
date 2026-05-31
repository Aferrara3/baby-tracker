import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import calendar_service


def test_infer_activity_type_from_summary_reuses_cached_summary_map_until_profile_changes(monkeypatch, tmp_path: Path):
    profile_one = tmp_path / "profile-one.yaml"
    profile_one.write_text("profile: one\n", encoding="utf-8")
    profile_two = tmp_path / "profile-two.yaml"
    profile_two.write_text("profile: two\n", encoding="utf-8")

    call_count = 0

    def fake_tracker_button_templates():
        nonlocal call_count
        call_count += 1
        return [{"id": "feed", "label": "Feed"}]

    monkeypatch.setenv("APP_PROFILE_CONFIG_PATH", str(profile_one))
    monkeypatch.setattr(calendar_service, "get_tracker_button_templates", fake_tracker_button_templates)
    monkeypatch.setattr(calendar_service, "get_app_profile", lambda: SimpleNamespace(type_aliases={}))
    monkeypatch.setattr(calendar_service, "activity_label", lambda activity_type: f"🍼 {activity_type.title()}")
    calendar_service._summary_type_map_cached.cache_clear()

    assert calendar_service.infer_activity_type_from_summary("Feed") == "feed"
    assert calendar_service.infer_activity_type_from_summary("Feed") == "feed"
    assert call_count == 1

    monkeypatch.setenv("APP_PROFILE_CONFIG_PATH", str(profile_two))
    assert calendar_service.infer_activity_type_from_summary("Feed") == "feed"
    assert call_count == 2


def test_build_event_body_uses_datetime_offsets_without_forcing_event_timezone(monkeypatch):
    monkeypatch.setattr(
        calendar_service,
        "get_activity_meta",
        lambda: {"feed": ("Feed", "2")},
    )
    monkeypatch.setattr(
        calendar_service,
        "get_app_profile",
        lambda: SimpleNamespace(
            type_aliases={},
            unknown_activity_color_id="1",
            unknown_activity_emoji="?",
        ),
    )

    service = calendar_service.CalendarService("fake-creds.json")
    start_time = datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)
    end_time = datetime(2025, 6, 1, 10, 30, tzinfo=timezone.utc)

    body = service.build_event_body(
        event_type="feed",
        start_time=start_time,
        end_time=end_time,
    )

    assert body["start"] == {"dateTime": start_time.isoformat()}
    assert body["end"] == {"dateTime": end_time.isoformat()}
