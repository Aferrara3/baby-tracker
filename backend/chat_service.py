from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlite3 import OperationalError
from sqlalchemy.engine import Engine

from config import (
    CHAT_MODEL_PROVIDER,
    CHAT_OLLAMA_BASE_URL,
    CHAT_OLLAMA_MODEL,
    CHAT_OLLAMA_READY_TIMEOUT_SECONDS,
    CHAT_OLLAMA_REQUEST_TIMEOUT_SECONDS,
)

MODEL_UNAVAILABLE_MESSAGE = (
    "Model unavailable at this time. This is a homelab hosted app and I use my computer for other things, "
    "so I do not always keep the chat model warm. Try again later or text me if you'd like your account linked "
    "to your own chat API billing."
)
logger = logging.getLogger(__name__)
IRRELEVANT_REQUEST_MESSAGE = "This beta chat only answers questions about your own tracked data in this app."
SECURITY_DENIAL_MESSAGE = (
    "I can only answer questions about your own account data in this app and cannot help bypass those limits."
)
UNSAFE_SQL_MESSAGE = "I could not answer that safely with the allowed read-only data tools."
MAX_CHAT_HISTORY_MESSAGES = 8
MAX_QUERY_ROWS = 200
CHAT_LOG_DIR = Path(__file__).resolve().parent / "chat_logs"
CHAT_SQL_SCOPE_PREFIX = """
WITH scoped_events AS (
    SELECT
        id,
        account_id,
        type,
        type AS event_type,
        title,
        start_time,
        user_local_date(start_time) AS local_date,
        end_time,
        duration,
        details,
        is_active,
        google_description,
        calendar_event_id,
        calendar_synced_at,
        google_etag,
        google_updated_at,
        deleted_at,
        calendar_sync_status,
        calendar_sync_error,
        calendar_sync_queued_at
    FROM event
    WHERE account_id = :account_id
      AND deleted_at IS NULL
)
"""


@dataclass(frozen=True)
class ChatReadiness:
    ready: bool
    provider: str
    model: str
    detail: str | None = None


@dataclass(frozen=True)
class ChatDecision:
    decision: Literal["allow", "deny_irrelevant", "deny_security"]
    reason: str


@dataclass(frozen=True)
class ChatOutcome:
    status: Literal["answered", "rejected", "unavailable"]
    reply: str
    sql: str | None = None


def _few_shot_sql_examples() -> list[dict[str, Any]]:
    return [
        {
            "question": "How many times did my baby poop in the last 7 days?",
            "sql": (
                "SELECT COUNT(*) AS poop_count "
                "FROM scoped_events "
                "WHERE type = 'diaper_poop' "
                "AND local_date BETWEEN days_ago_local(7) AND current_user_local_date()"
            ),
            "notes": "Use local_date for local-day windows and the normalized diaper_poop type id.",
        },
        {
            "question": "How much time was spent nursing so far today?",
            "sql": (
                "SELECT COALESCE(SUM(duration), 0) AS total_duration_seconds "
                "FROM scoped_events "
                "WHERE type = 'breastfeeding' "
                "AND local_date = current_user_local_date()"
            ),
            "notes": "Duration is stored in seconds; return a total the answer step can format.",
        },
        {
            "question": "How many oz did the baby eat in the last 7 days? If no notes on event, assume 1 oz each.",
            "sql": (
                "SELECT ROUND(COALESCE(SUM(COALESCE(extract_ounces(details), 1)), 0), 2) AS total_oz "
                "FROM scoped_events "
                "WHERE type = 'bottle' "
                "AND local_date BETWEEN days_ago_local(7) AND current_user_local_date()"
            ),
            "notes": "Bottle amounts come from details via extract_ounces(details), defaulting each missing note to 1 oz.",
        },
        {
            "question": "When is the baby due for Vit D drop next?",
            "sql": (
                "WITH vit_d_events AS ("
                " SELECT start_time, local_date, title, details "
                " FROM scoped_events "
                " WHERE title LIKE '%Vit D%' OR title LIKE '%vit d%' OR details LIKE '%Vit D%' OR details LIKE '%vit d%'"
                "), intervals AS ("
                " SELECT start_time, "
                "        LAG(start_time) OVER (ORDER BY start_time) AS previous_start_time "
                " FROM vit_d_events"
                ") "
                "SELECT start_time AS latest_start_time, "
                "       AVG(strftime('%s', start_time) - strftime('%s', previous_start_time)) AS avg_interval_seconds "
                "FROM intervals "
                "WHERE previous_start_time IS NOT NULL"
            ),
            "notes": "For due-next questions, return the latest event plus an average interval so the answer step can infer the next due time.",
        },
    ]


def chat_provider_name() -> str:
    return CHAT_MODEL_PROVIDER


def chat_model_name() -> str:
    return CHAT_OLLAMA_MODEL


def chat_readiness_status() -> ChatReadiness:
    if CHAT_MODEL_PROVIDER != "ollama":
        return ChatReadiness(
            ready=False,
            provider=CHAT_MODEL_PROVIDER,
            model=CHAT_OLLAMA_MODEL,
            detail="Only the Ollama chat provider is supported for this feature.",
        )

    try:
        _ollama_smoke_test()
    except Exception:
        return ChatReadiness(
            ready=False,
            provider=CHAT_MODEL_PROVIDER,
            model=CHAT_OLLAMA_MODEL,
            detail=MODEL_UNAVAILABLE_MESSAGE,
        )

    return ChatReadiness(
        ready=True,
        provider=CHAT_MODEL_PROVIDER,
        model=CHAT_OLLAMA_MODEL,
        detail=None,
    )


def answer_account_chat(
    *,
    engine: Engine,
    account_id: int,
    account_label: str,
    account_identifier: str,
    tracker_buttons: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    time_zone_name: str | None,
) -> ChatOutcome:
    readiness = chat_readiness_status()
    if not readiness.ready:
        outcome = ChatOutcome(status="unavailable", reply=MODEL_UNAVAILABLE_MESSAGE)
        _write_chat_log(account_identifier=account_identifier, messages=messages, outcome=outcome, metadata={"stage": "readiness"})
        return outcome

    normalized_messages = _normalize_messages(messages)
    latest_user_message = next((message["content"] for message in reversed(normalized_messages) if message["role"] == "user"), "")
    if not latest_user_message:
        outcome = ChatOutcome(status="rejected", reply="Ask a question about your tracked data to get started.")
        _write_chat_log(account_identifier=account_identifier, messages=messages, outcome=outcome, metadata={"stage": "empty-question"})
        return outcome

    time_zone = _resolve_time_zone(time_zone_name)
    context_snapshot = build_chat_context_snapshot(
        engine=engine,
        account_id=account_id,
        account_label=account_label,
        tracker_buttons=tracker_buttons,
        time_zone=time_zone,
    )
    decision = classify_request(messages=normalized_messages, context_snapshot=context_snapshot)
    if decision.decision == "deny_irrelevant":
        outcome = ChatOutcome(status="rejected", reply=IRRELEVANT_REQUEST_MESSAGE)
        _write_chat_log(account_identifier=account_identifier, messages=messages, outcome=outcome, metadata={"decision": decision.reason})
        return outcome
    if decision.decision == "deny_security":
        outcome = ChatOutcome(status="rejected", reply=SECURITY_DENIAL_MESSAGE)
        _write_chat_log(account_identifier=account_identifier, messages=messages, outcome=outcome, metadata={"decision": decision.reason})
        return outcome

    deterministic_outcome = try_deterministic_answer(
        engine=engine,
        account_id=account_id,
        normalized_messages=normalized_messages,
        latest_user_message=latest_user_message,
        time_zone=time_zone,
    )
    if deterministic_outcome is not None:
        _write_chat_log(account_identifier=account_identifier, messages=messages, outcome=deterministic_outcome, metadata={"path": "deterministic"})
        return deterministic_outcome

    try:
        sql = generate_sql_query(messages=normalized_messages, context_snapshot=context_snapshot)
        try:
            rows = execute_scoped_chat_sql(
                engine=engine,
                account_id=account_id,
                sql=sql,
                time_zone=time_zone,
            )
        except OperationalError as exc:
            repaired_sql = repair_sql_query(
                messages=normalized_messages,
                context_snapshot=context_snapshot,
                sql=sql,
                sql_error=str(exc),
            )
            rows = execute_scoped_chat_sql(
                engine=engine,
                account_id=account_id,
                sql=repaired_sql,
                time_zone=time_zone,
            )
            sql = repaired_sql
    except ValueError:
        outcome = ChatOutcome(status="rejected", reply=UNSAFE_SQL_MESSAGE)
        _write_chat_log(account_identifier=account_identifier, messages=messages, outcome=outcome, metadata={"path": "llm-sql", "error": "unsafe-sql"})
        return outcome
    except Exception:
        logger.exception("Chat SQL flow failed for account %s", account_id)
        outcome = ChatOutcome(status="rejected", reply=UNSAFE_SQL_MESSAGE, sql=locals().get("sql"))
        _write_chat_log(account_identifier=account_identifier, messages=messages, outcome=outcome, metadata={"path": "llm-sql", "error": "sql-flow"})
        return outcome

    try:
        reply = synthesize_answer(
            messages=normalized_messages,
            context_snapshot=context_snapshot,
            sql=sql,
            rows=rows,
        )
    except Exception:
        logger.exception("Chat answer synthesis failed for account %s", account_id)
        outcome = ChatOutcome(status="unavailable", reply=MODEL_UNAVAILABLE_MESSAGE, sql=sql)
        _write_chat_log(account_identifier=account_identifier, messages=messages, outcome=outcome, metadata={"path": "llm-sql", "error": "synthesis"})
        return outcome

    outcome = ChatOutcome(status="answered", reply=reply.strip() or "I could not form a useful answer from that data.", sql=sql)
    _write_chat_log(account_identifier=account_identifier, messages=messages, outcome=outcome, metadata={"path": "llm-sql"})
    return outcome


def try_deterministic_answer(
    *,
    engine: Engine,
    account_id: int,
    normalized_messages: list[dict[str, str]],
    latest_user_message: str,
    time_zone: ZoneInfo,
) -> ChatOutcome | None:
    lowered = latest_user_message.lower()
    subject = _infer_chat_subject(lowered, normalized_messages)
    time_scope = _infer_time_scope(lowered, normalized_messages)

    if subject == "poop" and (_has_count_intent(lowered) or time_scope["kind"] in {"today", "yesterday", "days_ago"}):
        date_filter, period_label = _time_scope_filter(time_scope, default_days=7)
        sql = (
            "SELECT COUNT(*) AS event_count "
            "FROM scoped_events "
            "WHERE type = 'diaper_poop' "
            f"AND {date_filter}"
        )
        rows = execute_scoped_chat_sql(engine=engine, account_id=account_id, sql=sql, time_zone=time_zone)
        count = int(rows[0].get("event_count", 0) or 0) if rows else 0
        return ChatOutcome(
            status="answered",
            reply=f"The baby pooped {count} time{'s' if count != 1 else ''} {period_label}.",
            sql=sql,
        )

    if subject == "nursing" and _has_breakdown_intent(lowered):
        if time_scope["kind"] in {"all_time", "today", "yesterday", "days_ago"}:
            time_scope = {"kind": "last_n_days", "days": 7}
        sql = (
            "SELECT local_date, COALESCE(SUM(duration), 0) AS total_duration_seconds "
            "FROM scoped_events "
            "WHERE type = 'breastfeeding' "
            f"AND {_time_scope_filter(time_scope, default_days=7)[0]} "
            "GROUP BY local_date "
            "ORDER BY local_date DESC"
        )
        rows = execute_scoped_chat_sql(engine=engine, account_id=account_id, sql=sql, time_zone=time_zone)
        if not rows:
            return ChatOutcome(status="answered", reply="No nursing entries were found for that breakdown window.", sql=sql)
        breakdown_lines = [
            f"- {row['local_date']}: {_format_duration(int(row.get('total_duration_seconds', 0) or 0))}"
            for row in rows
        ]
        _, period_label = _time_scope_filter(time_scope, default_days=7)
        return ChatOutcome(
            status="answered",
            reply=f"Here is the daily nursing breakdown {period_label}:\n" + "\n".join(breakdown_lines),
            sql=sql,
        )

    if subject == "nursing" and (_has_duration_intent(lowered) or time_scope["kind"] in {"today", "yesterday", "days_ago"}):
        if time_scope["kind"] not in {"today", "yesterday", "days_ago"}:
            time_scope = {"kind": "today", "days": None}
        date_filter, period_label = _time_scope_filter(time_scope, default_days=1)
        sql = (
            "SELECT COALESCE(SUM(duration), 0) AS total_duration_seconds "
            "FROM scoped_events "
            "WHERE type = 'breastfeeding' "
            f"AND {date_filter}"
        )
        rows = execute_scoped_chat_sql(engine=engine, account_id=account_id, sql=sql, time_zone=time_zone)
        seconds = int(rows[0].get("total_duration_seconds", 0) or 0) if rows else 0
        return ChatOutcome(
            status="answered",
            reply=f"The baby spent {_format_duration(seconds)} nursing {period_label}.",
            sql=sql,
        )

    if subject == "bottle" and _has_amount_intent(lowered):
        if time_scope["kind"] == "all_time":
            date_filter = "1 = 1"
            period_label = "across the logged bottle events"
        else:
            date_filter, period_label = _time_scope_filter(time_scope, default_days=0)
        sql = (
            "SELECT ROUND(COALESCE(SUM(COALESCE(extract_ounces(details), 1)), 0), 2) AS total_oz "
            "FROM scoped_events "
            "WHERE type = 'bottle' "
            f"AND {date_filter}"
        )
        rows = execute_scoped_chat_sql(engine=engine, account_id=account_id, sql=sql, time_zone=time_zone)
        total_oz = float(rows[0].get("total_oz", 0) or 0) if rows else 0.0
        return ChatOutcome(
            status="answered",
            reply=f"The baby ate {total_oz:.2f} oz {period_label}.",
            sql=sql,
        )

    if any(term in lowered for term in {"show", "list"}) and "bottle" in lowered and any(term in lowered for term in {"volume", "volumes", "oz", "timestamp", "timestamps", "logged"}):
        sql = (
            "SELECT start_time, ROUND(COALESCE(extract_ounces(details), 1), 2) AS logged_oz, details "
            "FROM scoped_events "
            "WHERE type = 'bottle' "
            "ORDER BY start_time DESC "
            "LIMIT 20"
        )
        rows = execute_scoped_chat_sql(engine=engine, account_id=account_id, sql=sql, time_zone=time_zone)
        if not rows:
            return ChatOutcome(status="answered", reply="No bottle events with logged volumes were found.", sql=sql)
        formatted_rows = []
        for row in rows:
            event_time = _parse_datetime_value(row["start_time"]).astimezone(time_zone).strftime("%b %d, %Y %I:%M %p")
            formatted_rows.append(f"- {event_time}: {float(row['logged_oz']):.2f} oz")
        return ChatOutcome(
            status="answered",
            reply="Here are the latest logged bottle events with volumes:\n" + "\n".join(formatted_rows),
            sql=sql,
        )

    if "fun facts" in lowered and any(term in lowered for term in {"baby", "data", "tracker"}):
        poop_rows = execute_scoped_chat_sql(
            engine=engine,
            account_id=account_id,
            sql="SELECT COUNT(*) AS poop_count FROM scoped_events WHERE type = 'diaper_poop' AND local_date BETWEEN days_ago_local(7) AND current_user_local_date()",
            time_zone=time_zone,
        )
        bottle_rows = execute_scoped_chat_sql(
            engine=engine,
            account_id=account_id,
            sql="SELECT ROUND(COALESCE(SUM(COALESCE(extract_ounces(details), 1)), 0), 2) AS total_oz FROM scoped_events WHERE type = 'bottle' AND local_date BETWEEN days_ago_local(7) AND current_user_local_date()",
            time_zone=time_zone,
        )
        nursing_rows = execute_scoped_chat_sql(
            engine=engine,
            account_id=account_id,
            sql="SELECT COALESCE(SUM(duration), 0) AS total_duration_seconds FROM scoped_events WHERE type = 'breastfeeding' AND local_date = current_user_local_date()",
            time_zone=time_zone,
        )
        return ChatOutcome(
            status="answered",
            reply=(
                "A few fun facts from the recent baby data:\n"
                f"- Poop logs in the last 7 days: {int(poop_rows[0].get('poop_count', 0) or 0)}\n"
                f"- Bottle intake in the last 7 days: {float(bottle_rows[0].get('total_oz', 0) or 0):.2f} oz\n"
                f"- Nursing time so far today: {_format_duration(int(nursing_rows[0].get('total_duration_seconds', 0) or 0))}"
            ),
            sql="deterministic_fun_facts",
        )

    if any(term in lowered for term in {"above", "earlier", "you said"}) and "oz" in lowered:
        all_time_rows = execute_scoped_chat_sql(
            engine=engine,
            account_id=account_id,
            sql="SELECT ROUND(COALESCE(SUM(COALESCE(extract_ounces(details), 1)), 0), 2) AS total_oz FROM scoped_events WHERE type = 'bottle' AND 1 = 1",
            time_zone=time_zone,
        )
        last_7_rows = execute_scoped_chat_sql(
            engine=engine,
            account_id=account_id,
            sql="SELECT ROUND(COALESCE(SUM(COALESCE(extract_ounces(details), 1)), 0), 2) AS total_oz FROM scoped_events WHERE type = 'bottle' AND local_date BETWEEN days_ago_local(7) AND current_user_local_date()",
            time_zone=time_zone,
        )
        prior_assistant_oz = _extract_latest_assistant_ounces(normalized_messages)
        return ChatOutcome(
            status="answered",
            reply=(
                f"I likely mixed time windows. Right now I see {float(all_time_rows[0].get('total_oz', 0) or 0):.2f} oz across all logged bottle events "
                f"and {float(last_7_rows[0].get('total_oz', 0) or 0):.2f} oz in the last 7 days."
                + (f" The earlier assistant message mentioned {prior_assistant_oz:.2f} oz." if prior_assistant_oz is not None else "")
            ),
            sql="deterministic_discrepancy_explanation",
        )

    if "vit" in lowered and "next" in lowered and any(term in lowered for term in {"due", "drop", "vit d", "vitamin d"}):
        sql = (
            "WITH vit_d_events AS ("
            " SELECT start_time "
            " FROM scoped_events "
            " WHERE title LIKE '%Vit d%' OR title LIKE '%Vit D%' OR title LIKE '%vit d%'"
            "    OR details LIKE '%Vit d%' OR details LIKE '%Vit D%' OR details LIKE '%vit d%'"
            "), intervals AS ("
            " SELECT start_time, LAG(start_time) OVER (ORDER BY start_time) AS previous_start_time "
            " FROM vit_d_events"
            ") "
            "SELECT start_time AS latest_start_time, "
            "       AVG(strftime('%s', start_time) - strftime('%s', previous_start_time)) AS avg_interval_seconds "
            "FROM intervals "
            "WHERE previous_start_time IS NOT NULL"
        )
        rows = execute_scoped_chat_sql(engine=engine, account_id=account_id, sql=sql, time_zone=time_zone)
        if not rows or not rows[0].get("latest_start_time") or not rows[0].get("avg_interval_seconds"):
            return ChatOutcome(status="answered", reply="I could not infer the next Vit D drop time from the logged data yet.", sql=sql)
        latest_start = _parse_datetime_value(rows[0]["latest_start_time"])
        avg_interval_seconds = float(rows[0]["avg_interval_seconds"])
        next_due = latest_start + timedelta(seconds=avg_interval_seconds)
        return ChatOutcome(
            status="answered",
            reply=f"Based on the logged pattern, the next Vit D drop looks due around {next_due.astimezone(time_zone).strftime('%b %d, %Y %I:%M %p')}.",
            sql=sql,
        )

    return None


def build_chat_context_snapshot(
    *,
    engine: Engine,
    account_id: int,
    account_label: str,
    tracker_buttons: list[dict[str, Any]],
    time_zone: ZoneInfo,
) -> dict[str, Any]:
    total_row = _run_metadata_query(
        engine,
        """
        SELECT COUNT(*) AS total_events,
               COUNT(DISTINCT type) AS distinct_types
        FROM event
        WHERE account_id = :account_id
          AND deleted_at IS NULL
        """,
        {"account_id": account_id},
    )[0]
    event_types = _run_metadata_query(
        engine,
        """
        SELECT type, COUNT(*) AS event_count
        FROM event
        WHERE account_id = :account_id
          AND deleted_at IS NULL
        GROUP BY type
        ORDER BY event_count DESC, type ASC
        LIMIT 20
        """,
        {"account_id": account_id},
    )
    event_titles = _run_metadata_query(
        engine,
        """
        SELECT title, COUNT(*) AS event_count
        FROM event
        WHERE account_id = :account_id
          AND deleted_at IS NULL
          AND title IS NOT NULL
          AND TRIM(title) != ''
        GROUP BY title
        ORDER BY event_count DESC, title ASC
        LIMIT 20
        """,
        {"account_id": account_id},
    )
    recent_events = _run_metadata_query(
        engine,
        """
        SELECT type, title, start_time, duration, details
        FROM event
        WHERE account_id = :account_id
          AND deleted_at IS NULL
        ORDER BY start_time DESC
        LIMIT 8
        """,
        {"account_id": account_id},
    )
    now_local = datetime.now(time_zone)

    return {
        "account_label": account_label,
        "time_zone": getattr(time_zone, "key", str(time_zone)),
        "current_utc_timestamp": datetime.now(timezone.utc).isoformat(),
        "current_local_timestamp": now_local.isoformat(),
        "current_local_date": now_local.date().isoformat(),
        "total_events": int(total_row.get("total_events", 0) or 0),
        "distinct_types": int(total_row.get("distinct_types", 0) or 0),
        "tracker_buttons": [
            {
                "id": str(button.get("id", "")).strip(),
                "label": str(button.get("label", "")).strip(),
                "icon_key": str(button.get("icon_key", "")).strip(),
                "emoji_override": button.get("emoji_override"),
            }
            for button in tracker_buttons
            if str(button.get("id", "")).strip()
        ],
        "event_types": event_types,
        "event_titles": event_titles,
        "recent_events": recent_events,
        "few_shot_examples": _few_shot_sql_examples(),
        "sql_rules": {
            "table": "scoped_events",
            "read_only": True,
            "helper_functions": [
                "extract_ounces(details)",
                "user_local_date(start_time)",
                "days_ago_local(n)",
                "current_user_local_date()",
                "current_utc_timestamp()",
            ],
        },
    }


def classify_request(*, messages: list[dict[str, str]], context_snapshot: dict[str, Any]) -> ChatDecision:
    latest_user_message = next((message["content"] for message in reversed(messages) if message["role"] == "user"), "")
    lowered = latest_user_message.lower()

    if _contains_security_red_flag(lowered):
        return ChatDecision(decision="deny_security", reason="Matched a hard security deny rule.")

    if _looks_like_app_data_question(lowered, messages, context_snapshot):
        return ChatDecision(decision="allow", reason="Matched app-data question heuristics.")

    return ChatDecision(decision="deny_irrelevant", reason="Did not match the app-data question heuristics.")


def generate_sql_query(*, messages: list[dict[str, str]], context_snapshot: dict[str, Any]) -> str:
    prompt = (
        "Conversation messages:\n"
        f"{json.dumps(messages, ensure_ascii=True)}\n\n"
        "Signed-in account context:\n"
        f"{json.dumps(context_snapshot, ensure_ascii=True)}\n\n"
        "Return JSON only with fields sql and purpose."
    )
    system = (
        "Generate one SQLite read-only query to answer the latest user question.\n"
        "Rules:\n"
        "- Output JSON only.\n"
        "- The SQL must be a single SELECT or WITH query with no semicolon.\n"
        "- Query ONLY the scoped_events table.\n"
        "- scoped_events columns are: id, account_id, type, event_type, title, start_time, local_date, end_time, duration, details, is_active, google_description, calendar_event_id, calendar_synced_at, google_etag, google_updated_at, deleted_at, calendar_sync_status, calendar_sync_error, calendar_sync_queued_at.\n"
        "- Never reference raw tables like event, account, auth_session, custom_icon, or sqlite_master.\n"
        "- Never use PRAGMA, INSERT, UPDATE, DELETE, DROP, ALTER, ATTACH, DETACH, CREATE, REPLACE, or comments.\n"
        "- This is SQLite, not MySQL or Postgres.\n"
        "- Use local_date or user_local_date(start_time) and current_user_local_date() for user-local calendar-day logic.\n"
        "- For relative local-day ranges, use days_ago_local(7) instead of INTERVAL syntax.\n"
        "- Use extract_ounces(details) for bottle-ounce parsing.\n"
        "- For ounce totals when notes are missing, default each relevant event to 1 by using COALESCE(extract_ounces(details), 1).\n"
        "- Alias result columns with readable snake_case names.\n"
        "- Keep result sets small and focused.\n"
        "- If the question needs inference (for example due-next timing), return the smallest result set needed for that inference.\n"
        "- Study the few_shot_examples in the provided context and follow their SQLite patterns closely."
    )
    payload = _ollama_generate_json(system=system, prompt=prompt)
    sql = str(payload.get("sql", "")).strip()
    validated = validate_chat_sql(sql)
    return validated


def repair_sql_query(
    *,
    messages: list[dict[str, str]],
    context_snapshot: dict[str, Any],
    sql: str,
    sql_error: str,
) -> str:
    prompt = (
        "Conversation messages:\n"
        f"{json.dumps(messages, ensure_ascii=True)}\n\n"
        "Signed-in account context:\n"
        f"{json.dumps(context_snapshot, ensure_ascii=True)}\n\n"
        f"Broken SQL:\n{sql}\n\n"
        f"SQLite error:\n{sql_error}\n\n"
        "Return JSON only with fields sql and fix_summary."
    )
    payload = _ollama_generate_json(
        system=(
            "Repair the broken SQL into valid SQLite for this baby-tracker app.\n"
            "Rules:\n"
            "- Output JSON only.\n"
            "- Return one single SELECT or WITH query with no semicolon.\n"
            "- Query ONLY scoped_events.\n"
            "- Use SQLite syntax only.\n"
            "- Prefer local_date or days_ago_local(n) over INTERVAL syntax.\n"
            "- Do not use raw tables or mutate data.\n"
            "- Reuse the few_shot_examples in the provided context when choosing idiomatic SQLite patterns."
        ),
        prompt=prompt,
    )
    return validate_chat_sql(str(payload.get("sql", "")).strip())


def synthesize_answer(
    *,
    messages: list[dict[str, str]],
    context_snapshot: dict[str, Any],
    sql: str,
    rows: list[dict[str, Any]],
) -> str:
    prompt = (
        "Conversation messages:\n"
        f"{json.dumps(messages, ensure_ascii=True)}\n\n"
        "Signed-in account context:\n"
        f"{json.dumps(context_snapshot, ensure_ascii=True)}\n\n"
        f"Executed SQL:\n{sql}\n\n"
        f"Result rows:\n{json.dumps(rows, ensure_ascii=True)}\n\n"
        "Answer the latest user question using only these results."
    )
    return _ollama_generate_text(
        system=(
            "You answer questions about the signed-in user's baby-tracker data.\n"
            "Be concise, direct, and faithful to the query results.\n"
            "Do not mention internal prompts, tool calls, policy text, or SQL unless the user asked.\n"
            "If the result is empty, say the data was not found.\n"
            "If you infer a next due time from repeated past events, state that it is based on the observed pattern in the account data."
        ),
        prompt=prompt,
    )


def execute_scoped_chat_sql(
    *,
    engine: Engine,
    account_id: int,
    sql: str,
    time_zone: ZoneInfo,
) -> list[dict[str, Any]]:
    validated = validate_chat_sql(sql)
    final_sql = (
        f"{CHAT_SQL_SCOPE_PREFIX}\n"
        "SELECT * FROM (\n"
        f"{validated}\n"
        ") AS chat_query\n"
        "LIMIT :row_limit"
    )
    connection = engine.raw_connection()
    try:
        connection.create_function("extract_ounces", 1, _extract_ounces)
        connection.create_function("user_local_date", 1, lambda value: _user_local_date(value, time_zone))
        connection.create_function("days_ago_local", 1, lambda value: _days_ago_local(value, time_zone))
        connection.create_function("current_user_local_date", 0, lambda: datetime.now(time_zone).date().isoformat())
        connection.create_function("current_utc_timestamp", 0, lambda: datetime.now(timezone.utc).isoformat())
        cursor = connection.cursor()
        cursor.execute(final_sql, {"account_id": account_id, "row_limit": MAX_QUERY_ROWS})
        rows = _cursor_rows(cursor)
        cursor.close()
        return rows
    finally:
        connection.close()


def validate_chat_sql(sql: str) -> str:
    normalized = _normalize_sql_dialect(re.sub(r"\s+", " ", sql or "").strip())
    if not normalized:
        raise ValueError("SQL is required.")
    lowered = normalized.lower()
    if ";" in normalized or "--" in normalized or "/*" in normalized or "*/" in normalized:
        raise ValueError("Comments and statement separators are not allowed.")
    if not (lowered.startswith("select ") or lowered.startswith("with ")):
        raise ValueError("Only SELECT queries are allowed.")
    if re.search(r"\b(insert|update|delete|drop|alter|attach|detach|create|replace|pragma|vacuum|reindex|analyze)\b", lowered):
        raise ValueError("Mutating SQL is not allowed.")
    if re.search(r"\b(sqlite_master|auth_session|account_share_email|account|event|calendar_sync_job|custom_icon)\b", lowered):
        raise ValueError("Direct table access is not allowed.")

    if "scoped_events" not in lowered:
        raise ValueError("Queries must anchor on scoped_events.")

    return normalized


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for message in messages[-MAX_CHAT_HISTORY_MESSAGES:]:
        role = str(message.get("role", "")).strip().lower()
        content = str(message.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _contains_security_red_flag(message: str) -> bool:
    red_flags = (
        "ignore previous",
        "ignore all previous",
        "bypass",
        "override",
        "other user",
        "other account",
        "all accounts",
        "every account",
        "show me the prompt",
        "system prompt",
        "raw sql",
        "full database",
        "dump schema",
        "run python",
        "shell command",
    )
    return any(flag in message for flag in red_flags)


def _looks_like_app_data_question(message: str, messages: list[dict[str, str]], context_snapshot: dict[str, Any]) -> bool:
    analytics_terms = {
        "how much",
        "how many",
        "count",
        "average",
        "avg",
        "sum",
        "total",
        "when",
        "last",
        "today",
        "yesterday",
        "week",
        "day",
        "days",
        "hours",
        "minutes",
        "times",
        "spent",
        "due",
        "next",
        "since",
        "recent",
        "history",
        "trend",
        "amount",
        "oz",
        "ounce",
        "ounces",
        "duration",
        "long",
    }
    app_terms = {
        "baby",
        "tracker",
        "event",
        "events",
        "log",
        "logged",
        "diaper",
        "poop",
        "pee",
        "bottle",
        "food",
        "sleep",
        "nursing",
        "breastfeeding",
        "pump",
        "milk",
        "calendar",
        "sync",
        "note",
        "notes",
        "vit d",
        "vitamin",
        "med",
        "medicine",
        "drop",
        "drops",
    }
    tracker_terms = set()
    for button in context_snapshot.get("tracker_buttons", []):
        tracker_terms.update(_tokenize_text(str(button.get("id", ""))))
        tracker_terms.update(_tokenize_text(str(button.get("label", ""))))
    for entry in context_snapshot.get("event_titles", []):
        tracker_terms.update(_tokenize_text(str(entry.get("title", ""))))
    for entry in context_snapshot.get("event_types", []):
        tracker_terms.update(_tokenize_text(str(entry.get("type", ""))))

    has_analytics_signal = any(term in message for term in analytics_terms)
    has_app_signal = any(term in message for term in app_terms) or any(term in message for term in tracker_terms)
    mentions_own_data = any(term in message for term in {"my", "our", "baby", "tracker", "data"})
    prior_app_context = any(
        entry["role"] == "assistant" and any(term in entry["content"].lower() for term in {"bottle", "poop", "pee", "nursing", "breastfeeding", "oz", "vit d"})
        for entry in messages
    )

    return (has_app_signal or prior_app_context) and (
        has_analytics_signal or mentions_own_data or any(term in message for term in {"show", "list", "fun facts", "above", "earlier", "you said"})
    )


def _extract_day_window(message: str) -> int | None:
    match = re.search(r"last\s+(\d+)\s+day", message)
    if match:
        return int(match.group(1))
    return None


def _has_count_intent(message: str) -> bool:
    return any(term in message for term in {"how many", "count", "times", "how many were"})


def _has_duration_intent(message: str) -> bool:
    return any(term in message for term in {"how much time", "time spent", "spent", "duration"})


def _has_amount_intent(message: str) -> bool:
    return (
        any(term in message for term in {"oz", "ounce", "ounces", "bottle"})
        and any(term in message for term in {"eat", "ate", "bottle", "drank", "drink", "eaten"})
        and any(term in message for term in {"how much", "total", "amount", "has the baby", "how much has"})
    )


def _has_breakdown_intent(message: str) -> bool:
    return any(term in message for term in {"breakdown", "daily breakdown", "per day", "grouped", "group by day"})


def _infer_chat_subject(latest_message: str, messages: list[dict[str, str]]) -> str | None:
    explicit = _subject_from_text(latest_message)
    if explicit is not None:
        return explicit

    for entry in reversed(messages[:-1]):
        if entry["role"] != "user":
            continue
        inferred = _subject_from_text(entry["content"].lower())
        if inferred is not None:
            return inferred
    return None


def _subject_from_text(message: str) -> str | None:
    if any(term in message for term in {"poop", "diaper_poop"}):
        return "poop"
    if any(term in message for term in {"nursing", "breastfeeding"}):
        return "nursing"
    if any(term in message for term in {"bottle", "oz", "ounce", "ounces"}):
        return "bottle"
    if any(term in message for term in {"vit d", "vitamin d", "drop"}) and "next" in message:
        return "vitd"
    return None


def _infer_time_scope(latest_message: str, messages: list[dict[str, str]]) -> dict[str, int | str | None]:
    if "day before yesterday" in latest_message:
        return {"kind": "days_ago", "days": 2}
    if "day before" in latest_message:
        prior_scope = _infer_prior_time_scope(messages)
        if prior_scope["kind"] == "days_ago":
            return {"kind": "days_ago", "days": int(prior_scope["days"] or 1) + 1}
        if prior_scope["kind"] == "yesterday":
            return {"kind": "days_ago", "days": 2}
        return {"kind": "days_ago", "days": 2}
    if "yesterday" in latest_message:
        return {"kind": "yesterday", "days": None}
    if "today" in latest_message:
        return {"kind": "today", "days": None}
    if any(term in latest_message for term in {"past week", "last week", "past 7 days", "weekly"}):
        return {"kind": "last_n_days", "days": 7}
    days = _extract_day_window(latest_message)
    if days is not None:
        return {"kind": "last_n_days", "days": days}
    if any(term in latest_message for term in {"across all", "all time", "ever", "overall"}):
        return {"kind": "all_time", "days": None}

    return _infer_prior_time_scope(messages)


def _infer_prior_time_scope(messages: list[dict[str, str]]) -> dict[str, int | str | None]:
    for entry in reversed(messages[:-1]):
        if entry["role"] != "user":
            continue
        prior = entry["content"].lower()
        if "day before yesterday" in prior:
            return {"kind": "days_ago", "days": 2}
        if "day before" in prior:
            return {"kind": "days_ago", "days": 2}
        if "yesterday" in prior:
            return {"kind": "yesterday", "days": None}
        if "today" in prior:
            return {"kind": "today", "days": None}
        if any(term in prior for term in {"past week", "last week", "past 7 days", "weekly"}):
            return {"kind": "last_n_days", "days": 7}
        prior_days = _extract_day_window(prior)
        if prior_days is not None:
            return {"kind": "last_n_days", "days": prior_days}
    return {"kind": "all_time", "days": None}


def _time_scope_filter(scope: dict[str, int | str | None], *, default_days: int) -> tuple[str, str]:
    kind = scope["kind"]
    if kind == "today":
        return "local_date = current_user_local_date()", "today"
    if kind == "yesterday":
        return "local_date = days_ago_local(2)", "yesterday"
    if kind == "days_ago":
        days_ago = int(scope["days"] or 1)
        target = days_ago + 1
        if days_ago == 1:
            return "local_date = days_ago_local(2)", "yesterday"
        if days_ago == 2:
            return f"local_date = days_ago_local({target})", "the day before yesterday"
        return f"local_date = days_ago_local({target})", f"{days_ago} days ago"
    if kind == "last_n_days":
        days = int(scope["days"] or default_days or 7)
        return (
            f"local_date BETWEEN days_ago_local({days}) AND current_user_local_date()",
            f"in the last {days} day{'s' if days != 1 else ''}",
        )
    if default_days > 0:
        return (
            f"local_date BETWEEN days_ago_local({default_days}) AND current_user_local_date()",
            f"in the last {default_days} day{'s' if default_days != 1 else ''}",
        )
    return "1 = 1", "across the logged bottle events"


def _format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0 minutes"
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes or not parts:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return " ".join(parts)


def _parse_datetime_value(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _extract_latest_assistant_ounces(messages: list[dict[str, str]]) -> float | None:
    for message in reversed(messages):
        if message["role"] != "assistant":
            continue
        match = re.search(r"(\d+(?:\.\d+)?)\s*oz", message["content"].lower())
        if match:
            return float(match.group(1))
    return None


def _safe_log_identifier(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-").lower()
    return cleaned or "unknown-user"


def _write_chat_log(*, account_identifier: str, messages: list[dict[str, Any]], outcome: ChatOutcome, metadata: dict[str, Any]) -> None:
    CHAT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = CHAT_LOG_DIR / f"{timestamp}-{_safe_log_identifier(account_identifier)}.log"
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account_identifier": account_identifier,
        "messages": messages,
        "outcome": {
            "status": outcome.status,
            "reply": outcome.reply,
            "sql": outcome.sql,
        },
        "metadata": metadata,
    }
    log_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _tokenize_text(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) >= 2}


def _run_metadata_query(engine: Engine, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(sql, params)
        rows = _cursor_rows(cursor)
        cursor.close()
        return rows
    finally:
        connection.close()


def _cursor_rows(cursor) -> list[dict[str, Any]]:
    description = cursor.description or []
    columns = [column[0] for column in description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _resolve_time_zone(time_zone_name: str | None) -> ZoneInfo:
    if time_zone_name:
        try:
            return ZoneInfo(time_zone_name)
        except ZoneInfoNotFoundError:
            pass
    local_tz = datetime.now().astimezone().tzinfo
    if isinstance(local_tz, ZoneInfo):
        return local_tz
    return ZoneInfo("UTC")


def _extract_ounces(details: Any) -> float | None:
    if details is None:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*oz\b", str(details).lower())
    if not match:
        return None
    return float(match.group(1))


def _user_local_date(value: Any, time_zone: ZoneInfo) -> str | None:
    if value in {None, ""}:
        return None
    text_value = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(time_zone).date().isoformat()


def _days_ago_local(value: Any, time_zone: ZoneInfo) -> str:
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = 0
    if days <= 1:
        offset = 0
    else:
        offset = days - 1
    return datetime.now(time_zone).date().fromordinal(datetime.now(time_zone).date().toordinal() - offset).isoformat()


def _normalize_sql_dialect(sql: str) -> str:
    normalized = sql.strip()
    if not normalized:
        return normalized

    normalized = re.sub(r"\bevent_type\b", "type", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bcurdate\(\)", "current_user_local_date()", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bcurrent_date\b", "current_user_local_date()", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bnow\(\)", "current_utc_timestamp()", normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r"current_user_local_date\(\)\s*-\s*interval\s+(\d+)\s+day[s]?",
        lambda match: f"days_ago_local({match.group(1)})",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"date_sub\s*\(\s*current_user_local_date\(\)\s*,\s*interval\s+(\d+)\s+day[s]?\s*\)",
        lambda match: f"days_ago_local({match.group(1)})",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"current_user_local_date\(\)\s*-\s*days_ago_local\((\d+)\)",
        lambda match: f"days_ago_local({match.group(1)})",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\bstart_time\b(\s+between\s+(?:\(?\s*)?(?:days_ago_local\(|current_user_local_date\(|date\())",
        r"local_date\1",
        normalized,
        flags=re.IGNORECASE,
    )
    return normalized


def _ollama_smoke_test() -> None:
    _ollama_request(
        {
            "model": CHAT_OLLAMA_MODEL,
            "system": "Reply with READY.",
            "prompt": "ready?",
            "stream": False,
            "options": {"temperature": 0, "num_predict": 1},
            "keep_alive": "5m",
        },
        timeout_seconds=CHAT_OLLAMA_READY_TIMEOUT_SECONDS,
    )


def _ollama_generate_json(*, system: str, prompt: str) -> dict[str, Any]:
    payload = _ollama_request(
        {
            "model": CHAT_OLLAMA_MODEL,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "keep_alive": "5m",
        },
        timeout_seconds=CHAT_OLLAMA_REQUEST_TIMEOUT_SECONDS,
    )
    return _parse_json_object(str(payload.get("response", "")).strip())


def _ollama_generate_text(*, system: str, prompt: str) -> str:
    payload = _ollama_request(
        {
            "model": CHAT_OLLAMA_MODEL,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
            "keep_alive": "5m",
        },
        timeout_seconds=CHAT_OLLAMA_REQUEST_TIMEOUT_SECONDS,
    )
    return str(payload.get("response", "")).strip()


def _ollama_request(payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
    if CHAT_MODEL_PROVIDER != "ollama":
        raise RuntimeError("Unsupported chat provider.")
    response = httpx.post(
        f"{CHAT_OLLAMA_BASE_URL.rstrip('/')}/api/generate",
        json=payload,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response.json()


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object.")
    return parsed
