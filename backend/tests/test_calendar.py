"""
Integration tests for Google Calendar service.

These tests make real API calls against the shared calendar.
Run from the backend directory with the venv active:

    pytest tests/test_calendar.py -v

Set GOOGLE_CREDENTIALS_PATH / GOOGLE_CALENDAR_ID env vars to override defaults.
"""

import sys
import os
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import CREDENTIALS_PATH, CALENDAR_ID
from calendar_service import CalendarService, ACTIVITY_META, INSTANT_EVENT_DURATION_MINUTES

LIVE_CALENDAR_TESTS_ENABLED = os.environ.get("ENABLE_LIVE_CALENDAR_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not LIVE_CALENDAR_TESTS_ENABLED,
    reason="Live Google Calendar tests are opt-in. Set ENABLE_LIVE_CALENDAR_TESTS=1 to run them.",
)


@pytest.fixture(scope="module")
def svc() -> CalendarService:
    """Shared CalendarService instance for all tests in this module."""
    return CalendarService(CREDENTIALS_PATH, CALENDAR_ID)


@pytest.fixture(scope="module")
def created_event_ids():
    return []


@pytest.fixture(scope="module", autouse=True)
def cleanup_live_events(svc, created_event_ids):
    yield
    for event_id in created_event_ids:
        svc.delete_event(event_id, calendar_id=CALENDAR_ID)


# ---------------------------------------------------------------------------
# Auth / connectivity
# ---------------------------------------------------------------------------

class TestCalendarAccess:
    def test_credentials_file_exists(self):
        assert os.path.isfile(CREDENTIALS_PATH), (
            f"Credentials file not found: {CREDENTIALS_PATH}"
        )

    def test_can_reach_calendar(self, svc):
        """Service account can authenticate and read the target calendar."""
        assert svc.verify_calendar_access() is True


# ---------------------------------------------------------------------------
# Low-level create_event
# ---------------------------------------------------------------------------

class TestCreateEvent:
    def test_creates_event_returns_dict_with_id(self, svc, created_event_ids):
        now = datetime.now(timezone.utc)
        result = svc.create_event(
            summary="[test] Baby Tracker smoke test",
            start_time=now,
            end_time=now + timedelta(minutes=5),
            description="Automated test event – safe to delete",
            color_id="1",
        )
        created_event_ids.append(result["id"])
        assert isinstance(result, dict)
        assert result.get("id"), "Response should contain an event id"
        assert result.get("summary") == "[test] Baby Tracker smoke test"

    def test_event_times_are_stored_correctly(self, svc, created_event_ids):
        from dateutil.parser import parse as parse_dt
        start = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        end   = datetime(2025, 6, 1, 10, 30, 0, tzinfo=timezone.utc)
        result = svc.create_event(
            summary="[test] Time accuracy check",
            start_time=start,
            end_time=end,
        )
        created_event_ids.append(result["id"])
        # Google returns times in the calendar's local timezone; compare as UTC instants
        returned_start = parse_dt(result["start"]["dateTime"]).astimezone(timezone.utc)
        returned_end   = parse_dt(result["end"]["dateTime"]).astimezone(timezone.utc)
        assert returned_start == start
        assert returned_end   == end


# ---------------------------------------------------------------------------
# High-level create_event_from_baby_event
# ---------------------------------------------------------------------------

class TestCreateEventFromBabyEvent:

    @pytest.mark.parametrize("activity_type", list(ACTIVITY_META.keys()))
    def test_all_activity_types_create_event(self, svc, activity_type, created_event_ids):
        """Every known activity type should produce a calendar event."""
        now = datetime.now(timezone.utc)
        event_dict = {
            "type": activity_type,
            "start_time": now,
            "end_time": now + timedelta(minutes=10),
            "duration": 600,
            "details": f"pytest – {activity_type}",
        }
        result = svc.create_event_from_baby_event(event_dict)
        created_event_ids.append(result["id"])
        assert result.get("id"), f"No event id returned for activity type: {activity_type}"
        expected_label, expected_color = ACTIVITY_META[activity_type]
        assert result.get("summary") == expected_label
        assert result.get("colorId") == expected_color

    def test_instant_tap_event_gets_default_duration(self, svc, created_event_ids):
        """Events with no end_time or duration should still be created."""
        now = datetime.now(timezone.utc)
        result = svc.create_event_from_baby_event({
            "type": "bottle",
            "start_time": now,
        })
        created_event_ids.append(result["id"])
        assert result.get("id")
        # End should be start + INSTANT_EVENT_DURATION_MINUTES; compare as UTC instants
        from dateutil.parser import parse as parse_dt
        end   = parse_dt(result["end"]["dateTime"]).astimezone(timezone.utc)
        start = parse_dt(result["start"]["dateTime"]).astimezone(timezone.utc)
        diff_minutes = (end - start).total_seconds() / 60
        assert diff_minutes == INSTANT_EVENT_DURATION_MINUTES

    def test_duration_in_description(self, svc, created_event_ids):
        """Duration seconds should be formatted in the event description."""
        now = datetime.now(timezone.utc)
        result = svc.create_event_from_baby_event({
            "type": "sleep",
            "start_time": now,
            "end_time": now + timedelta(hours=2),
            "duration": 7200,
        })
        created_event_ids.append(result["id"])
        assert "Duration: 120m 0s" in result.get("description", "")

    def test_notes_in_description(self, svc, created_event_ids):
        """User-supplied details/notes should appear in the description."""
        now = datetime.now(timezone.utc)
        result = svc.create_event_from_baby_event({
            "type": "food",
            "start_time": now,
            "end_time": now + timedelta(minutes=15),
            "details": "ate 4 oz of puree",
        })
        created_event_ids.append(result["id"])
        assert "ate 4 oz of puree" in result.get("description", "")

    def test_unknown_activity_type_uses_fallback(self, svc, created_event_ids):
        """Unrecognised activity types should not raise, using fallback label/color."""
        now = datetime.now(timezone.utc)
        result = svc.create_event_from_baby_event({
            "type": "custom_activity",
            "start_time": now,
            "end_time": now + timedelta(minutes=5),
        })
        created_event_ids.append(result["id"])
        assert result.get("id")
        assert "Custom_Activity" in result.get("summary", "")

    def test_naive_datetime_is_handled(self, svc, created_event_ids):
        """Timezone-naive datetimes should be accepted without error."""
        naive_start = datetime(2025, 7, 4, 8, 0, 0)  # no tzinfo
        result = svc.create_event_from_baby_event({
            "type": "pump",
            "start_time": naive_start,
            "duration": 900,
        })
        created_event_ids.append(result["id"])
        assert result.get("id")
