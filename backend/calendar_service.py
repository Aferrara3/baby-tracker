"""
Google Calendar integration for Baby Tracker.

Usage:
    from calendar_service import CalendarService
    svc = CalendarService(credentials_path, calendar_id)
    svc.create_event_from_baby_event(event)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# Maps baby tracker activity type → (emoji label, Google Calendar colorId)
# Calendar color IDs: 1=Lavender, 2=Sage, 3=Grape, 4=Flamingo, 5=Banana,
#                     6=Tangerine, 7=Peacock, 8=Graphite, 9=Blueberry, 10=Basil, 11=Tomato
ACTIVITY_META: dict[str, tuple[str, str]] = {
    "bottle":        ("🍼 Bottle",         "5"),   # Banana
    "food":          ("🥄 Food",           "2"),   # Sage
    "diaper_pee":    ("💧 Diaper (Pee)",   "7"),   # Peacock
    "diaper_poop":   ("💩 Diaper (Poop)",  "8"),   # Graphite
    "sleep":         ("😴 Sleep",          "9"),   # Blueberry
    "breastfeeding": ("🤱 Breastfeeding",  "4"),   # Flamingo
    "pump":          ("🥛 Pump",           "6"),   # Tangerine
    "help":          ("❓ Help",           "1"),   # Lavender
}

ACTIVITY_TYPE_ALIASES: dict[str, str] = {
    "diaper1": "diaper_pee",
    "diaper2": "diaper_poop",
    "nursing": "breastfeeding",
    "other": "help",
}

# Minimum event duration for instant-tap events (Google Calendar requires a non-zero span)
INSTANT_EVENT_DURATION_MINUTES = 5


def normalize_activity_type(activity_type: str) -> str:
    """Map legacy/frontend activity identifiers onto the canonical calendar IDs."""
    return ACTIVITY_TYPE_ALIASES.get(activity_type, activity_type)


class CalendarService:
    """Wraps the Google Calendar API for Baby Tracker event creation."""

    def __init__(self, credentials_path: str, calendar_id: str) -> None:
        self.credentials_path = credentials_path
        self.calendar_id = calendar_id
        self._service = None  # lazy-initialised

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_event_from_baby_event(self, event) -> dict:
        """
        Create a Google Calendar event from a baby tracker Event/dict-like object.

        Accepts either a SQLModel Event instance or any object/dict with the
        fields: type, start_time, end_time, duration, details.
        """
        if isinstance(event, dict):
            event_type  = event.get("type", "unknown")
            start_time  = event.get("start_time") or datetime.now(timezone.utc)
            end_time    = event.get("end_time")
            duration    = event.get("duration")
            details     = event.get("details")
        else:
            event_type  = getattr(event, "type", "unknown")
            start_time  = getattr(event, "start_time", datetime.now(timezone.utc))
            end_time    = getattr(event, "end_time", None)
            duration    = getattr(event, "duration", None)
            details     = getattr(event, "details", None)

        body = self.build_event_body(
            event_type=event_type,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            details=details,
        )

        return self.create_event(body=body)

    def update_event_from_baby_event(self, calendar_event_id: str, event) -> dict:
        """Update an existing Google Calendar event from a baby tracker Event."""
        if isinstance(event, dict):
            event_type = event.get("type", "unknown")
            start_time = event.get("start_time") or datetime.now(timezone.utc)
            end_time = event.get("end_time")
            duration = event.get("duration")
            details = event.get("details")
        else:
            event_type = getattr(event, "type", "unknown")
            start_time = getattr(event, "start_time", datetime.now(timezone.utc))
            end_time = getattr(event, "end_time", None)
            duration = getattr(event, "duration", None)
            details = getattr(event, "details", None)

        body = self.build_event_body(
            event_type=event_type,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            details=details,
        )

        return self.update_event(calendar_event_id=calendar_event_id, body=body)

    def build_event_body(
        self,
        event_type: str,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        duration: Optional[int] = None,
        details: Optional[str] = None,
    ) -> dict:
        """Build a Google Calendar event payload from a baby tracker event."""
        normalized_type = normalize_activity_type(event_type)
        label, color_id = ACTIVITY_META.get(
            normalized_type,
            (f"🍼 {normalized_type.title()}", "1"),
        )

        # Ensure start_time is timezone-aware
        if isinstance(start_time, datetime) and start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        # Determine end_time
        if end_time is not None:
            if isinstance(end_time, datetime) and end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
        elif duration:
            end_time = start_time + timedelta(seconds=duration)
        else:
            end_time = start_time + timedelta(minutes=INSTANT_EVENT_DURATION_MINUTES)

        description_parts = []
        if duration:
            minutes, seconds = divmod(duration, 60)
            description_parts.append(f"Duration: {minutes}m {seconds}s")
        if details:
            description_parts.append(f"Notes: {details}")
        description = "\n".join(description_parts) if description_parts else None

        body: dict = {
            "summary": label,
            "start": {"dateTime": start_time.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end_time.isoformat(), "timeZone": "UTC"},
        }
        if description:
            body["description"] = description
        if color_id:
            body["colorId"] = color_id
        return body

    def create_event(
        self,
        body: Optional[dict] = None,
        summary: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        description: Optional[str] = None,
        color_id: Optional[str] = None,
    ) -> dict:
        """
        Create a single Google Calendar event and return the API response.

        Raises googleapiclient.errors.HttpError on API failures.
        """
        if body is None:
            if summary is None or start_time is None or end_time is None:
                raise ValueError("summary, start_time, and end_time are required when body is not provided")
            body = {
                "summary": summary,
                "start": {"dateTime": start_time.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": end_time.isoformat(), "timeZone": "UTC"},
            }
            if description:
                body["description"] = description
            if color_id:
                body["colorId"] = color_id

        service = self._get_service()
        result = (
            service.events()
            .insert(calendarId=self.calendar_id, body=body)
            .execute()
        )
        logger.info("Calendar event created: %s (%s)", result.get("summary"), result.get("id"))
        return result

    def update_event(self, calendar_event_id: str, body: dict) -> dict:
        """Update a single Google Calendar event and return the API response."""
        service = self._get_service()
        result = (
            service.events()
            .update(calendarId=self.calendar_id, eventId=calendar_event_id, body=body)
            .execute()
        )
        logger.info("Calendar event updated: %s (%s)", result.get("summary"), result.get("id"))
        return result

    def verify_calendar_access(self) -> bool:
        """
        Confirm the service account can reach the target calendar.
        Returns True on success, raises on failure.

        Uses events.list (compatible with calendar.events scope).
        """
        service = self._get_service()
        response = (
            service.events()
            .list(calendarId=self.calendar_id, maxResults=1)
            .execute()
        )
        logger.info("Calendar access verified; kind=%s", response.get("kind"))
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_service(self):
        """Lazily build and cache the Google Calendar API service client."""
        if self._service is None:
            creds = service_account.Credentials.from_service_account_file(
                self.credentials_path, scopes=SCOPES
            )
            self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service
