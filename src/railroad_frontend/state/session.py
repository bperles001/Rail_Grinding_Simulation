"""Shared Streamlit session helpers used across the dashboard."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import streamlit as st

from railroad_backend.persistence.plan_storage import load_plan_storage, persist_plan_sections
from railroad_backend.services.auto_planner import auto_defaults
from railroad_backend.services.manual_planner import manual_defaults

ACTIVE_NETWORK_PATH_KEY = "active_network_path"
NETWORK_EDITOR_STATE_KEY = "network_editor_state"
NETWORK_EDITOR_FLASH_KEY = "network_editor_flash"
NETWORK_EDITOR_REFRESH_KEY = "network_editor_refresh_notice"
NETWORK_SELECT_LABEL_KEY = "network_select_label"
NETWORK_SELECT_PENDING_LABEL_KEY = "network_select_pending_label"
SCHEDULE_WARNING_KEY = "schedule_warning_segments"
NAVIGATION_PAGE_KEY = "navigation_page"

MANUAL_CONFIG_KEY = "manual_plan_config"
MANUAL_PLAN_KEY = "manual_plan_steps"
MANUAL_RESULT_KEY = "manual_plan_result"
MANUAL_SAVED_PLANS_KEY = "manual_saved_plans"
MANUAL_WIDGET_KEYS: Dict[str, str] = {
    "start_station": "manual_start_station",
    "facing_station": "manual_facing_station",
    "start_year": "manual_start_year",
    "end_year": "manual_end_year",
    "second_kld": "manual_second_kld",
}

AUTO_CONFIG_KEY = "auto_sim_config"
AUTO_SAVED_RUNS_KEY = "auto_saved_runs"

PLAN_STORAGE_FLAG_KEY = "_plan_storage_loaded"


def persist_plan_storage(
    storage_path: Path,
    *,
    manual_key: str,
    auto_key: str,
) -> None:
    """Write manual/auto plan sections back to disk."""
    manual_plans = st.session_state.get(manual_key, {})
    auto_runs = st.session_state.get(auto_key, {})
    persist_plan_sections(storage_path, manual_plans, auto_runs)


def ensure_plan_storage_loaded(
    storage_path: Path,
    *,
    manual_key: str,
    auto_key: str,
    flag_key: str = PLAN_STORAGE_FLAG_KEY,
) -> None:
    """Lazy-load plan storage so views can depend on it."""
    if st.session_state.get(flag_key):
        return
    storage = load_plan_storage(storage_path)
    st.session_state.setdefault(manual_key, storage.get("manual", {}))
    st.session_state.setdefault(auto_key, storage.get("auto", {}))
    st.session_state[flag_key] = True


def ensure_manual_state(
    *,
    config_key: str,
    plan_key: str,
    result_key: str,
    saved_plans_key: str,
    widget_keys: Mapping[str, str],
    network_config_provider: Callable[[], Any],
    station_choices_provider: Callable[[], Sequence[str]],
    facing_options_provider: Callable[[str], Sequence[str]],
) -> Dict[str, Any]:
    """Populate manual planner defaults (config, widgets, caches)."""
    if config_key not in st.session_state:
        st.session_state[config_key] = manual_defaults(network_config_provider())
    st.session_state.setdefault(plan_key, [])
    st.session_state.setdefault(result_key, None)
    st.session_state.setdefault(saved_plans_key, {})
    config = st.session_state[config_key]

    widget_defaults = {
        widget_keys["start_station"]: config["start_station"],
        widget_keys["facing_station"]: config["facing_station"],
        widget_keys["start_year"]: config["start_year"],
        widget_keys["end_year"]: config["end_year"],
        widget_keys["second_kld"]: config["second_kld"],
    }
    for key, value in widget_defaults.items():
        st.session_state.setdefault(key, value)

    station_choices = list(station_choices_provider()) or [config["start_station"]]
    start_widget = widget_keys["start_station"]
    facing_widget = widget_keys["facing_station"]
    start_value = st.session_state[start_widget]
    if start_value not in station_choices:
        start_value = station_choices[0]
        st.session_state[start_widget] = start_value

    facing_choices = list(facing_options_provider(start_value)) or [start_value]
    if st.session_state[facing_widget] not in facing_choices:
        st.session_state[facing_widget] = facing_choices[0]

    return config


def ensure_auto_state(
    *,
    config_key: str,
    saved_runs_key: str,
    network_config_provider: Callable[[], Any],
) -> Dict[str, Any]:
    """Populate auto planner defaults (config + saved runs)."""
    if config_key not in st.session_state:
        st.session_state[config_key] = auto_defaults(network_config_provider())
    st.session_state.setdefault(saved_runs_key, {})
    return st.session_state[config_key]


def update_manual_plan(plan_key: str, result_key: str, new_plan: List[Dict[str, Any]]) -> None:
    """Replace the manual plan and clear cached results."""
    st.session_state[plan_key] = [dict(step) for step in new_plan]
    st.session_state[result_key] = None


def store_manual_result(
    *,
    result_key: str,
    plan_key: str,
    segment_status_builder: Callable[[Optional[Any]], List[Dict[str, Any]]],
    simulator: Optional[Any],
) -> None:
    """Persist the latest manual simulation snapshot."""
    if simulator is None:
        st.session_state[result_key] = None
        return
    st.session_state[result_key] = {
        "steps": [dict(step) for step in getattr(simulator, "steps", [])],
        "movement_days_total": getattr(simulator, "movement_days_total", 0),
        "maintenance_days_total": getattr(simulator, "maintenance_days_total", 0),
        "idle_days_total": getattr(simulator, "idle_days_total", 0),
        "maintenance_count": getattr(simulator, "maintenance_count", 0),
        "plan": [dict(step) for step in st.session_state.get(plan_key, [])],
        "segment_status": segment_status_builder(simulator),
    }


__all__ = [
    "ACTIVE_NETWORK_PATH_KEY",
    "AUTO_CONFIG_KEY",
    "AUTO_SAVED_RUNS_KEY",
    "MANUAL_CONFIG_KEY",
    "MANUAL_PLAN_KEY",
    "MANUAL_RESULT_KEY",
    "MANUAL_SAVED_PLANS_KEY",
    "MANUAL_WIDGET_KEYS",
    "NAVIGATION_PAGE_KEY",
    "NETWORK_EDITOR_FLASH_KEY",
    "NETWORK_EDITOR_REFRESH_KEY",
    "NETWORK_EDITOR_STATE_KEY",
    "NETWORK_SELECT_LABEL_KEY",
    "NETWORK_SELECT_PENDING_LABEL_KEY",
    "SCHEDULE_WARNING_KEY",
    "PLAN_STORAGE_FLAG_KEY",
    "ensure_plan_storage_loaded",
    "persist_plan_storage",
    "ensure_manual_state",
    "ensure_auto_state",
    "update_manual_plan",
    "store_manual_result",
]
