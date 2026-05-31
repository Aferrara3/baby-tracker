"""Google Calendar integration for tracker event sync."""

from __future__ import annotations

import logging
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app_profile import get_activity_meta, get_app_profile, get_tracker_button_templates, resolve_profile_config_path
from config import CALENDAR_SHARE_ROLE, CALENDAR_TIME_ZONE

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

INSTANT_EVENT_DURATION_MINUTES = 5


def _event_datetime_payload(value: datetime) -> dict[str, str]:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return {"dateTime": value.isoformat()}


def normalize_activity_type(activity_type: str) -> str:
    return get_app_profile().type_aliases.get(activity_type, activity_type)


def activity_label(activity_type: str) -> str:
    normalized_type = normalize_activity_type(activity_type)
    profile = get_app_profile()
    return get_activity_meta().get(
        normalized_type,
        (f"{profile.unknown_activity_emoji} {normalized_type.replace('_', ' ').title()}", profile.unknown_activity_color_id),
    )[0]


def _summary_type_map_cache_key() -> tuple[str, int]:
    profile_path = resolve_profile_config_path()
    return str(profile_path), profile_path.stat().st_mtime_ns


@lru_cache(maxsize=8)
def _summary_type_map_cached(_: tuple[str, int]) -> dict[str, str]:
    summary_map: dict[str, str] = {}
    for button in get_tracker_button_templates():
        activity_type = str(button["id"])
        label = str(button["label"]).strip()
        summary_map[activity_label(activity_type)] = activity_type
        if label:
            summary_map[label] = activity_type
    for alias, canonical in get_app_profile().type_aliases.items():
        summary_map[alias.replace("_", " ").title()] = canonical
    return summary_map


def _summary_type_map() -> dict[str, str]:
    return _summary_type_map_cached(_summary_type_map_cache_key())


def infer_activity_type_from_summary(summary: Optional[str], fallback: Optional[str] = None) -> str:
    if not summary:
        return fallback or "help"

    normalized_summary = summary.strip()
    return normalize_activity_type(_summary_type_map().get(normalized_summary, fallback or "help"))


class CalendarService:
    """Wraps the Google Calendar API for calendar provisioning and event sync."""

    def __init__(self, credentials_path: str, calendar_id: Optional[str] = None) -> None:
        self.credentials_path = credentials_path
        self.calendar_id = calendar_id
        self._service = None

    def create_event_from_baby_event(self, event, calendar_id: Optional[str] = None) -> dict:
        if isinstance(event, dict):
            event_type = event.get("type", "unknown")
            title = event.get("title")
            start_time = event.get("start_time") or datetime.now(timezone.utc)
            end_time = event.get("end_time")
            duration = event.get("duration")
            details = event.get("details")
        else:
            event_type = getattr(event, "type", "unknown")
            title = getattr(event, "title", None)
            start_time = getattr(event, "start_time", datetime.now(timezone.utc))
            end_time = getattr(event, "end_time", None)
            duration = getattr(event, "duration", None)
            details = getattr(event, "details", None)

        body = self.build_event_body(
            event_type=event_type,
            title=title,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            details=details,
        )
        return self.create_event(body=body, calendar_id=calendar_id)

    def update_event_from_baby_event(self, calendar_event_id: str, event, calendar_id: Optional[str] = None) -> dict:
        if isinstance(event, dict):
            event_type = event.get("type", "unknown")
            title = event.get("title")
            start_time = event.get("start_time") or datetime.now(timezone.utc)
            end_time = event.get("end_time")
            duration = event.get("duration")
            details = event.get("details")
        else:
            event_type = getattr(event, "type", "unknown")
            title = getattr(event, "title", None)
            start_time = getattr(event, "start_time", datetime.now(timezone.utc))
            end_time = getattr(event, "end_time", None)
            duration = getattr(event, "duration", None)
            details = getattr(event, "details", None)

        body = self.build_event_body(
            event_type=event_type,
            title=title,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            details=details,
        )
        return self.update_event(calendar_event_id=calendar_event_id, body=body, calendar_id=calendar_id)

    def build_event_body(
        self,
        event_type: str,
        start_time: datetime,
        title: Optional[str] = None,
        end_time: Optional[datetime] = None,
        duration: Optional[int] = None,
        details: Optional[str] = None,
    ) -> dict:
        normalized_type = normalize_activity_type(event_type)
        profile = get_app_profile()
        label, color_id = get_activity_meta().get(
            normalized_type,
            (
                activity_label(normalized_type),
                profile.unknown_activity_color_id,
            ),
        )

        if isinstance(start_time, datetime) and start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

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
            "summary": title or label,
            "start": _event_datetime_payload(start_time),
            "end": _event_datetime_payload(end_time),
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
        calendar_id: Optional[str] = None,
    ) -> dict:
        if body is None:
            if summary is None or start_time is None or end_time is None:
                raise ValueError("summary, start_time, and end_time are required when body is not provided")
            body = {
                "summary": summary,
                "start": _event_datetime_payload(start_time),
                "end": _event_datetime_payload(end_time),
            }
            if description:
                body["description"] = description
            if color_id:
                body["colorId"] = color_id

        resolved_calendar_id = self._resolve_calendar_id(calendar_id)
        service = self._get_service()
        result = service.events().insert(calendarId=resolved_calendar_id, body=body).execute()
        logger.info("Calendar event created: %s (%s)", result.get("summary"), result.get("id"))
        return result

    def update_event(self, calendar_event_id: str, body: dict, calendar_id: Optional[str] = None) -> dict:
        resolved_calendar_id = self._resolve_calendar_id(calendar_id)
        service = self._get_service()
        result = (
            service.events()
            .update(calendarId=resolved_calendar_id, eventId=calendar_event_id, body=body)
            .execute()
        )
        logger.info("Calendar event updated: %s (%s)", result.get("summary"), result.get("id"))
        return result

    def delete_event(self, calendar_event_id: str, calendar_id: Optional[str] = None) -> None:
        resolved_calendar_id = self._resolve_calendar_id(calendar_id)
        service = self._get_service()
        service.events().delete(calendarId=resolved_calendar_id, eventId=calendar_event_id).execute()
        logger.info("Calendar event deleted: %s from %s", calendar_event_id, resolved_calendar_id)

    def create_calendar(self, summary: str, description: Optional[str] = None, time_zone: str = CALENDAR_TIME_ZONE) -> dict:
        body = {"summary": summary, "timeZone": time_zone}
        if description:
            body["description"] = description
        service = self._get_service()
        result = service.calendars().insert(body=body).execute()
        logger.info("Calendar provisioned: %s (%s)", result.get("summary"), result.get("id"))
        return result

    def update_calendar_metadata(
        self,
        calendar_id: str,
        summary: str,
        description: Optional[str] = None,
        time_zone: str = CALENDAR_TIME_ZONE,
    ) -> dict:
        body = {"summary": summary, "timeZone": time_zone}
        if description:
            body["description"] = description
        service = self._get_service()
        result = service.calendars().update(calendarId=calendar_id, body=body).execute()
        logger.info("Calendar metadata updated: %s (%s)", result.get("summary"), result.get("id"))
        return result

    def share_calendar(
        self,
        calendar_id: str,
        email: str,
        role: str = CALENDAR_SHARE_ROLE,
        send_notifications: bool = True,
    ) -> dict:
        body = {
            "role": role,
            "scope": {"type": "user", "value": email},
        }
        service = self._get_service()
        result = (
            service.acl()
            .insert(
                calendarId=calendar_id,
                body=body,
                sendNotifications=send_notifications,
            )
            .execute()
        )
        logger.info("Calendar shared: %s -> %s", calendar_id, email)
        return result

    def verify_calendar_access(self, calendar_id: Optional[str] = None) -> bool:
        resolved_calendar_id = self._resolve_calendar_id(calendar_id)
        service = self._get_service()
        service.events().list(calendarId=resolved_calendar_id, maxResults=1).execute()
        return True

    def list_event_changes(
        self,
        calendar_id: Optional[str] = None,
        sync_token: Optional[str] = None,
    ) -> dict:
        resolved_calendar_id = self._resolve_calendar_id(calendar_id)
        service = self._get_service()
        params = {
            "calendarId": resolved_calendar_id,
            "showDeleted": True,
        }
        if sync_token:
            params["syncToken"] = sync_token

        items: list[dict] = []
        next_sync_token: Optional[str] = None
        full_sync = sync_token is None

        while True:
            try:
                response = service.events().list(**params).execute()
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                if sync_token and status == 410:
                    logger.info("Google sync token expired for %s; falling back to full sync", resolved_calendar_id)
                    return self.list_event_changes(calendar_id=resolved_calendar_id, sync_token=None)
                raise

            items.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if page_token:
                params["pageToken"] = page_token
                continue

            next_sync_token = response.get("nextSyncToken")
            break

        return {
            "items": items,
            "next_sync_token": next_sync_token,
            "full_sync": full_sync,
        }

    def _resolve_calendar_id(self, calendar_id: Optional[str]) -> str:
        resolved = calendar_id or self.calendar_id
        if not resolved:
            raise ValueError("calendar_id is required")
        return resolved

    def _get_service(self):
        if self._service is None:
            creds = service_account.Credentials.from_service_account_file(
                self.credentials_path,
                scopes=SCOPES,
            )
            self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service
