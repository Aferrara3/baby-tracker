from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

from config import APP_PROFILE_CONFIG_PATH, REPO_ROOT

TRACKER_BUTTONS_PER_PAGE = 8
MAX_TRACKER_BUTTON_PAGES = 3


class AppProfileSymbol(BaseModel):
    key: str
    label: str
    emoji: str
    keywords: list[str] = Field(default_factory=list)


class AppProfileButton(BaseModel):
    id: str
    label: str
    icon_key: str
    color_key: str
    google_color_id: str = "1"


class AppProfileCopy(BaseModel):
    auth_badge_label: str
    auth_heading: str
    auth_subheading: str
    create_account_label: str
    register_name_placeholder: str
    settings_name_label: str
    settings_name_placeholder: str
    enable_sync_name_help: str
    header_context_with_name: str
    header_context_without_name: str


class AppProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    profile_id: str
    app_name: str
    api_title: str
    calendar_summary_prefix: str
    calendar_description_template: str
    placeholder_button_label_prefix: str = "Other"
    unknown_activity_emoji: str = "🏷️"
    unknown_activity_color_id: str = "1"
    type_aliases: dict[str, str] = Field(
        default_factory=lambda: {
            "diaper1": "diaper_pee",
            "diaper2": "diaper_poop",
            "nursing": "breastfeeding",
            "other": "help",
        }
    )
    profile_copy: AppProfileCopy = Field(alias="copy")
    symbols: list[AppProfileSymbol]
    button_templates: list[list[AppProfileButton]]


_cached_profile: Optional[AppProfile] = None
_cached_profile_path: Optional[Path] = None
_cached_profile_mtime_ns: Optional[int] = None
_cached_lucide_symbols: Optional[list[dict[str, object]]] = None
_cached_lucide_symbols_mtime_ns: Optional[int] = None


def resolve_profile_config_path() -> Path:
    configured_path = os.environ.get("APP_PROFILE_CONFIG_PATH", APP_PROFILE_CONFIG_PATH)
    candidate = Path(configured_path).expanduser()
    if not candidate.is_absolute():
        candidate = (REPO_ROOT / candidate).resolve()
    return candidate


def get_app_profile(force_reload: bool = False) -> AppProfile:
    global _cached_profile, _cached_profile_path, _cached_profile_mtime_ns

    path = resolve_profile_config_path()
    stat = path.stat()
    if (
        not force_reload
        and _cached_profile is not None
        and _cached_profile_path == path
        and _cached_profile_mtime_ns == stat.st_mtime_ns
    ):
        return _cached_profile

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    profile = AppProfile.model_validate(payload)

    if not profile.button_templates:
        raise ValueError("App profile must define at least one tracker-button page")
    if len(profile.button_templates) > MAX_TRACKER_BUTTON_PAGES:
        raise ValueError(f"App profile supports at most {MAX_TRACKER_BUTTON_PAGES} tracker-button pages")

    for page_index, page in enumerate(profile.button_templates, start=1):
        if len(page) != TRACKER_BUTTONS_PER_PAGE:
            raise ValueError(
                f"Tracker button page {page_index} must contain exactly {TRACKER_BUTTONS_PER_PAGE} buttons"
            )

    _cached_profile = profile
    _cached_profile_path = path
    _cached_profile_mtime_ns = stat.st_mtime_ns
    return profile


def _lucide_catalog_path() -> Path:
    return REPO_ROOT / "shared" / "lucide-catalog.json"


def get_lucide_catalog(force_reload: bool = False) -> list[dict[str, object]]:
    global _cached_lucide_symbols, _cached_lucide_symbols_mtime_ns

    path = _lucide_catalog_path()
    stat = path.stat()
    if (
        not force_reload
        and _cached_lucide_symbols is not None
        and _cached_lucide_symbols_mtime_ns == stat.st_mtime_ns
    ):
        return _cached_lucide_symbols

    catalog = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    normalized_catalog = [
        {
            "key": str(symbol.get("key", "")).strip(),
            "label": str(symbol.get("label", "")).strip(),
            "emoji": str(symbol.get("emoji", "🏷️")).strip() or "🏷️",
            "keywords": [str(keyword) for keyword in symbol.get("keywords", [])],
            "category": str(symbol.get("category", "general")).strip() or "general",
            "icon_kind": "lucide",
        }
        for symbol in catalog
        if str(symbol.get("key", "")).strip()
    ]

    _cached_lucide_symbols = normalized_catalog
    _cached_lucide_symbols_mtime_ns = stat.st_mtime_ns
    return normalized_catalog


def get_profile_symbols() -> list[dict[str, object]]:
    merged_symbols = {str(symbol["key"]): dict(symbol) for symbol in get_lucide_catalog()}
    for symbol in get_app_profile().symbols:
        merged_symbol = merged_symbols.get(symbol.key, {})
        merged_symbol.update(symbol.model_dump())
        merged_symbol["icon_kind"] = merged_symbol.get("icon_kind", "lucide")
        merged_symbols[symbol.key] = merged_symbol
    return list(merged_symbols.values())


def get_profile_symbol_meta() -> dict[str, dict[str, object]]:
    return {
        str(symbol["key"]): {
            "label": str(symbol["label"]),
            "emoji": str(symbol["emoji"]),
            "keywords": [str(keyword) for keyword in symbol["keywords"]],
            "category": str(symbol.get("category", "general")),
            "icon_kind": str(symbol.get("icon_kind", "lucide")),
        }
        for symbol in get_profile_symbols()
    }


def _button_response_payload(button: AppProfileButton, position: int) -> dict[str, object]:
    return {
        "id": button.id,
        "label": button.label,
        "icon_key": button.icon_key,
        "color_key": button.color_key,
        "position": position,
        "google_color_id": button.google_color_id,
    }


def get_seed_tracker_buttons() -> list[dict[str, object]]:
    first_page = get_app_profile().button_templates[0]
    return [_button_response_payload(button, index) for index, button in enumerate(first_page)]


def get_tracker_button_templates() -> list[dict[str, object]]:
    template_buttons: list[dict[str, object]] = []
    for page_index, page in enumerate(get_app_profile().button_templates):
        page_start = page_index * TRACKER_BUTTONS_PER_PAGE
        template_buttons.extend(
            _button_response_payload(button, page_start + index) for index, button in enumerate(page)
        )
    return template_buttons


def get_activity_meta() -> dict[str, tuple[str, str]]:
    symbol_meta = get_profile_symbol_meta()
    profile = get_app_profile()
    activity_meta: dict[str, tuple[str, str]] = {}
    for button in get_tracker_button_templates():
        emoji = str(symbol_meta.get(str(button["icon_key"]), {}).get("emoji", profile.unknown_activity_emoji))
        label = str(button["label"]).strip() or str(button["id"]).replace("_", " ").title()
        activity_meta[str(button["id"])] = (f"{emoji} {label}".strip(), str(button["google_color_id"]))
    return activity_meta


def public_app_config() -> dict[str, object]:
    profile = get_app_profile()
    return {
        "profile_id": profile.profile_id,
        "app_name": profile.app_name,
        "copy": profile.profile_copy.model_dump(),
        "available_symbols": get_profile_symbols(),
        "button_templates": get_tracker_button_templates(),
        "tracker_buttons_per_page": TRACKER_BUTTONS_PER_PAGE,
        "max_tracker_button_pages": MAX_TRACKER_BUTTON_PAGES,
        "placeholder_button_label_prefix": profile.placeholder_button_label_prefix,
    }
