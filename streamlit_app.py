"""Streamlit dashboard tying together the railroad maintenance toolkit."""

from __future__ import annotations

import sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).parent.resolve()
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import base64
import copy
import hashlib
import io
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd
import streamlit as st
from matplotlib.ticker import FuncFormatter

from railroad_backend.services.auto_planner import run_auto_plan_from_args
from railroad_backend.services.network_editor import (
    dataframe_signature,
    default_segment_name_sequence,
    facing_options_from_config,
    network_file_digest as backend_network_file_digest,
    serialize_network_editor_state as backend_serialize_network_editor_state,
    station_choices_from_config,
)
from railroad_backend.services.schedule_service import (
    current_schedule_dataframe,
    parse_schedule_bytes,
    schedule_missing_segments,
    summarize_schedule_dataframe,
)
from railroad_frontend.state.session import (
    ACTIVE_NETWORK_PATH_KEY,
    AUTO_CONFIG_KEY,
    AUTO_SAVED_RUNS_KEY,
    MANUAL_CONFIG_KEY,
    MANUAL_PLAN_KEY,
    MANUAL_RESULT_KEY,
    MANUAL_SAVED_PLANS_KEY,
    MANUAL_WIDGET_KEYS,
    NAVIGATION_PAGE_KEY,
    NETWORK_EDITOR_FLASH_KEY,
    NETWORK_EDITOR_REFRESH_KEY,
    NETWORK_EDITOR_STATE_KEY,
    NETWORK_SELECT_LABEL_KEY,
    NETWORK_SELECT_PENDING_LABEL_KEY,
    PLAN_STORAGE_FLAG_KEY,
    SCHEDULE_WARNING_KEY,
    ensure_auto_state,
    ensure_manual_state,
    ensure_plan_storage_loaded,
    persist_plan_storage,
    store_manual_result,
    update_manual_plan,
)
from railroad_frontend.views.auto_simulation import (
    AutoSimulationCallbacks,
    AutoSimulationSessionKeys,
    render_auto_simulation_page,
)
from railroad_frontend.views.comparison import render_comparison_page
from railroad_frontend.views.manual import (
    ManualRouteCallbacks,
    ManualRouteSessionKeys,
    render_manual_route_page,
)
from railroad_frontend.views.mtbt_editor import (
    MtbtEditorCallbacks,
    render_mtbt_editor_page,
)
from railroad_frontend.views.network_editor import (
    NetworkEditorCallbacks,
    render_network_editor_page,
)
from railroad_frontend.views.schedule import render_schedule_page
from railroad_backend.domain.network_layout import automatic_layout_positions, automatic_station_layout
from src.simulator import DEFAULT_NETWORK_FILE, Simulator
from railroad_backend.domain.network_editor import (
    network_editor_segment_df,
    network_editor_station_df,
    spur_rows_from_text,
    unique_network_path,
)
from src.utils.network_loader import (
    NetworkConfig,
    list_network_files,
    load_network,
)
from src.railroad_backend.domain.schedule import (
    blank_mtbt_dataframe,
    mtbt_dataframe_from_payload,
    mtbt_payload_from_df,
    normalize_mtbt_dataframe,
)
from railroad_frontend.components.ui_components import (
    inject_custom_css,
    render_workflow_stepper,
    render_accessibility_widget,
)

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
NETWORK_DIR = DATA_DIR / "networks"
PLAN_STORAGE_FILE = DATA_DIR / "saved_plans.json"
DEFAULT_SCHEDULE = DATA_DIR / "mtbt_schedule.csv"

NETWORK_LAYOUT_SCALE = 1.0
NETWORK_LAYOUT_SCALE_MIN = 0.5
NETWORK_LAYOUT_SCALE_MAX = 3.0

LAYOUT_PREFERENCES_KEY = "_network_layout_preferences"
NETWORK_PAYLOAD_CACHE_KEY = "_network_payload_cache"
SCHEDULE_CACHE_KEY = "_schedule_cache"


def _dataframe_signature(df: pd.DataFrame) -> str:
    return dataframe_signature(df)


def _load_network_payload(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {
            "name": path.stem,
            "stations": [],
            "segments": [],
            "direction_model": {},
            "layout": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _cached_network_payload(path: str, digest: str) -> Dict[str, Any]:
    cache: Dict[str, Dict[str, Any]] = st.session_state.setdefault(NETWORK_PAYLOAD_CACHE_KEY, {})
    entry = cache.get(path)
    if entry and entry.get("digest") == digest:
        return copy.deepcopy(entry["payload"])
    payload = _load_network_payload(Path(path))
    cache[path] = {"digest": digest, "payload": copy.deepcopy(payload)}
    st.session_state[NETWORK_PAYLOAD_CACHE_KEY] = cache
    return payload


def _network_file_digest(path: Path) -> str:
    return backend_network_file_digest(path)


def _ensure_active_network_path() -> str | None:
    """Return the active network path, or None if no network is selected yet."""
    stored = st.session_state.get(ACTIVE_NETWORK_PATH_KEY)
    if stored and Path(stored).exists():
        return stored
    # Don't auto-select - let user choose
    return None


def _current_network_file_path() -> Path | None:
    path_str = _ensure_active_network_path()
    return Path(path_str) if path_str else None


def _current_network_config() -> NetworkConfig:
    return load_network(_current_network_file_path())


def _current_network_segments() -> Sequence[Any]:
    return _current_network_config().segments


def _network_segments() -> Sequence[Any]:
    return _current_network_segments()


def _station_choices_or_default() -> Sequence[str]:
    config = _current_network_config()
    return station_choices_from_config(config)


def _facing_options(start_station: str) -> Sequence[str]:
    config = _current_network_config()
    return facing_options_from_config(config, start_station)


def _layout_preferences_for_path() -> Dict[str, Any]:
    path = str(_current_network_file_path())
    prefs: Dict[str, Dict[str, Any]] = st.session_state.setdefault(LAYOUT_PREFERENCES_KEY, {})
    entry = prefs.get(path)
    if entry:
        return entry
    payload = _load_network_payload(Path(path))
    layout = payload.get("layout") or {}
    entry = {
        "mode": str(layout.get("mode", "table")) or "table",
        "table_overrides": copy.deepcopy(layout.get("table_overrides", {})) or {},
        "scale": float(layout.get("scale", NETWORK_LAYOUT_SCALE) or NETWORK_LAYOUT_SCALE),
    }
    prefs[path] = entry
    return entry


def _layout_preferences_update(state: Dict[str, Any]) -> None:
    prefs: Dict[str, Dict[str, Any]] = st.session_state.setdefault(LAYOUT_PREFERENCES_KEY, {})
    path = str(_current_network_file_path())
    prefs[path] = copy.deepcopy(state.get("layout_settings") or {})
    st.session_state[LAYOUT_PREFERENCES_KEY] = prefs


def _layout_payload_for_state(state: Dict[str, Any]) -> Dict[str, Any]:
    prefs = state.get("layout_settings") or _layout_preferences_for_state(state)
    return {
        "mode": str(prefs.get("mode", "table") or "table"),
        "table_overrides": copy.deepcopy(prefs.get("table_overrides", {}) or {}),
        "scale": float(prefs.get("scale", NETWORK_LAYOUT_SCALE) or NETWORK_LAYOUT_SCALE),
    }


def _serialize_network_editor_state(state: Dict[str, Any]) -> Dict[str, Any]:
    payload = backend_serialize_network_editor_state(state)
    payload["layout"] = _layout_payload_for_state(state)
    return payload


def run_auto_plan(
    schedule_path: Path,
    *,
    start_station: str,
    facing_station: str,
    start_year: int,
    end_year: int,
    steps: int,
    second_kld: bool,
    network_path: Optional[Path] = None,
) -> Simulator:
    """Convenience wrapper for tests and CLI usage."""
    result = run_auto_plan_from_args(
        schedule_path,
        start_station=start_station,
        facing_station=facing_station,
        start_year=start_year,
        end_year=end_year,
        steps=steps,
        second_kld=second_kld,
        network_source=network_path or DEFAULT_NETWORK_FILE,
    )
    return result.simulator


def _build_mtbt_dataframe_from_payload(
    payload: Dict[str, Any],
    segments_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build MTBT dataframe from network payload or create blank template."""
    mtbt_payload = payload.get("mtbt_schedule") or {}
    if mtbt_payload:
        # Pass the full payload since mtbt_dataframe_from_payload expects to extract mtbt_schedule itself
        return normalize_mtbt_dataframe(mtbt_dataframe_from_payload(payload))
    else:
        return blank_mtbt_dataframe(
            default_segment_name_sequence({"segments_df": segments_df}),
            default_schedule=DEFAULT_SCHEDULE if DEFAULT_SCHEDULE.exists() else None,
        )


def _build_layout_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract layout settings from network payload."""
    layout_entry = payload.get("layout") or {}
    return {
        "mode": str(layout_entry.get("mode", "table")) or "table",
        "table_overrides": copy.deepcopy(layout_entry.get("table_overrides", {})) or {},
        "scale": float(layout_entry.get("scale", NETWORK_LAYOUT_SCALE) or NETWORK_LAYOUT_SCALE),
    }


def _ensure_network_editor_state() -> Dict[str, Any] | None:
    path = _current_network_file_path()
    if not path:
        return None
    digest = _network_file_digest(path)
    state = st.session_state.get(NETWORK_EDITOR_STATE_KEY)
    if state and state.get("path") == str(path) and state.get("digest") == digest:
        return state

    # Load network data
    payload = _cached_network_payload(str(path), digest)
    stations_df = network_editor_station_df(payload)
    segments_df = network_editor_segment_df(payload)
    mtbt_df = _build_mtbt_dataframe_from_payload(payload, segments_df)

    # Build state dictionary
    raw_order = payload.get("timeline_order")
    timeline_order: List[str] = [str(s) for s in raw_order if s] if isinstance(raw_order, list) else []
    state = {
        "path": str(path),
        "digest": digest,
        "raw_payload": copy.deepcopy(payload),
        "display_name": payload.get("name") or path.stem,
        "stations_df": stations_df,
        "segments_df": segments_df,
        "mtbt_df": normalize_mtbt_dataframe(mtbt_df.copy(deep=True)),
        "dirty": False,
        "_stations_signature": _dataframe_signature(stations_df),
        "_segments_signature": _dataframe_signature(segments_df),
        "layout_settings": _build_layout_settings(payload),
        "timeline_order": timeline_order,
    }

    _layout_preferences_update(state)
    st.session_state[NETWORK_EDITOR_STATE_KEY] = state
    return state


def _layout_preferences_for_state(state: Dict[str, Any]) -> Dict[str, Any]:
    prefs = state.get("layout_settings")
    if prefs is None:
        prefs = copy.deepcopy(_layout_preferences_for_path())
        state["layout_settings"] = prefs
    return prefs


def _table_layout_positions(config: NetworkConfig) -> Dict[str, Tuple[float, float]]:
    prefs = _layout_preferences_for_path()
    if prefs.get("mode", "table") != "table":
        return {}
    overrides = prefs.get("table_overrides", {}) or {}
    positions: Dict[str, Tuple[float, float]] = {}
    for station in config.stations.values():
        coords = overrides.get(station.name)
        if not coords:
            continue
        try:
            positions[station.name] = (float(coords.get("x", 0.0)), float(coords.get("y", 0.0)))
        except (TypeError, ValueError):
            continue
    return positions


def _current_schedule_dataframe() -> pd.DataFrame | None:
    state = _ensure_network_editor_state()
    if not state:
        return None
    return current_schedule_dataframe(state, DEFAULT_SCHEDULE)


def _current_schedule_bytes() -> bytes:
    return _current_schedule_dataframe().to_csv(index=False).encode("utf-8")


def _current_schedule_path() -> Path:
    return _persist_schedule(_current_schedule_bytes())


def _network_file_mapping() -> Dict[str, str]:
    raw_mapping = list_network_files(NETWORK_DIR)
    if not raw_mapping:
        fallback = _create_blank_network_file("New Network")
        return {"New Network": str(fallback)}

    entries: Dict[str, str] = {}
    collision_counters: Dict[str, int] = {}
    sorted_items = sorted(
        raw_mapping.items(),
        key=lambda item: (str(item[0]).lower(), str(item[1])),
    )
    for _label_hint, path_obj in sorted_items:
        path = Path(path_obj)
        # Use lazy loading - only parse network if needed for label
        try:
            # Try to get label from cache first to avoid re-parsing
            config = load_network(path)
            label = (config.name or path.stem).strip()
        except Exception:
            label = path.stem
        if not label:
            label = path.stem
        base_label = label
        suffix = collision_counters.get(base_label, 0)
        # Optimize collision detection
        if base_label in entries:
            while label in entries:
                suffix += 1
                label = f"{base_label} ({suffix})"
            collision_counters[base_label] = suffix
        entries[label] = str(path)
    if not entries:
        fallback = _create_blank_network_file("New Network")
        entries["New Network"] = str(fallback)
    return entries


def _write_network_payload(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _create_blank_network_file(
    display_name: str,
    slug_hint: Optional[str] = None,
    *,
    include_sample: bool = True,
) -> Path:
    slug_source = slug_hint or display_name
    target = unique_network_path(NETWORK_DIR, slug_source)
    stations: List[Dict[str, Any]] = []
    segments: List[Dict[str, Any]] = []
    if include_sample:
        stations = [
            {"name": "AAA", "can_turn": True},
            {"name": "BBB", "can_turn": True},
        ]
        segments = [
            {
                "name": "AAA-BBB",
                "start": "AAA",
                "end": "BBB",
                "length_km": 10.0,
                "mtbt_threshold": 1000.0,
                "move_time_days": 2,
                "maintenance_time_days": 5,
                "allowed_movements": [["AAA", "BBB"], ["BBB", "AAA"]],
            }
        ]
    payload = {
        "name": display_name,
        "stations": stations,
        "segments": segments,
        "mtbt_schedule": mtbt_payload_from_df(
            blank_mtbt_dataframe(
                [segment["name"] for segment in segments],
                default_schedule=DEFAULT_SCHEDULE if DEFAULT_SCHEDULE.exists() else None,
            )
        ),
        "layout": {
            "mode": "table",
            "table_overrides": {},
            "scale": NETWORK_LAYOUT_SCALE,
        },
    }
    _write_network_payload(target, payload)
    return target


def _duplicate_active_network_file(display_name: str, slug_hint: Optional[str] = None) -> Path:
    state = _ensure_network_editor_state()
    payload = copy.deepcopy(state.get("raw_payload", {})) or _load_network_payload(_current_network_file_path())
    payload["name"] = display_name
    path = unique_network_path(NETWORK_DIR, slug_hint or display_name)
    _write_network_payload(path, payload)
    return path


def _import_uploaded_network(raw_bytes: bytes, display_name: str, slug_hint: Optional[str]) -> Path:
    payload = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Uploaded JSON must be an object")
    payload["name"] = display_name
    path = unique_network_path(NETWORK_DIR, slug_hint or display_name)
    _write_network_payload(path, payload)
    return path


def _delete_network_file(path: Path) -> None:
    if path.exists():
        path.unlink()


def _set_network_editor_flash(message: str, *, level: str = "info") -> None:
    st.session_state[NETWORK_EDITOR_FLASH_KEY] = {"message": message, "level": level}


def _consume_network_editor_flash() -> None:
    flash = st.session_state.pop(NETWORK_EDITOR_FLASH_KEY, None)
    if not flash:
        return
    message = flash.get("message", "")
    level = flash.get("level", "info")
    renderer = {
        "success": st.success,
        "warning": st.warning,
        "error": st.error,
        "info": st.info,
    }.get(level, st.info)
    renderer(message)


def _schedule_network_editor_refresh(message: str) -> None:
    st.session_state[NETWORK_EDITOR_REFRESH_KEY] = message


def _consume_network_editor_refresh_notice() -> None:
    notice = st.session_state.pop(NETWORK_EDITOR_REFRESH_KEY, None)
    if notice:
        st.info(notice)


def _clear_network_editor_widgets() -> None:
    for key in (
        "network_station_editor",
        "network_segment_editor",
        "network_corridor_editor",
        "network_spur_carregado_editor",
        "network_spur_vazio_editor",
        "network_layout_editor",
    ):
        st.session_state.pop(key, None)


def _apply_network_change(path: str, *, label_hint: Optional[str] = None) -> None:
    st.session_state[ACTIVE_NETWORK_PATH_KEY] = str(path)
    st.session_state.pop(NETWORK_EDITOR_STATE_KEY, None)
    st.session_state.pop(SCHEDULE_WARNING_KEY, None)
    if label_hint:
        st.session_state[NETWORK_SELECT_PENDING_LABEL_KEY] = label_hint
    _force_rerun()


def _render_schedule_network_alert() -> None:
    state = _ensure_network_editor_state()
    missing = st.session_state.get(SCHEDULE_WARNING_KEY) or []
    display_name = state.get("display_name") or Path(state.get("path", "")).stem
    file_name = Path(state.get("path", "")).name
    if missing:
        st.warning(
            f"{len(missing)} segment(s) in the MTBT schedule are missing from '{display_name}'.",
        )


def _update_schedule_network_warnings(schedule_df: pd.DataFrame) -> List[str]:
    missing = schedule_missing_segments(schedule_df, _current_network_segments())
    st.session_state[SCHEDULE_WARNING_KEY] = missing
    return missing


def _render_network_layout_controls(state: Dict[str, Any]) -> None:
    prefs = _layout_preferences_for_state(state)
    config = _current_network_config()
    mode_col, scale_col = st.columns([2, 1])
    mode = mode_col.selectbox(
        "Layout mode",
        options=["table", "auto"],
        index=0 if prefs.get("mode", "table") == "table" else 1,
    )
    if mode != prefs.get("mode"):
        prefs["mode"] = mode
        state["dirty"] = True
    scale = scale_col.slider(
        "Sketch scale",
        min_value=NETWORK_LAYOUT_SCALE_MIN,
        max_value=NETWORK_LAYOUT_SCALE_MAX,
        value=float(prefs.get("scale", NETWORK_LAYOUT_SCALE)),
        step=0.1,
    )
    if abs(scale - float(prefs.get("scale", NETWORK_LAYOUT_SCALE))) > 1e-6:
        prefs["scale"] = scale
        state["dirty"] = True
    if mode == "table":
        overrides = prefs.get("table_overrides", {}) or {}
        rows = []
        auto_defaults = automatic_station_layout(config)
        station_names = state["stations_df"]["Name"].astype(str).tolist()
        for idx, name in enumerate(station_names):
            coords = overrides.get(name)
            if not coords and auto_defaults:
                coords = auto_defaults.get(name)
            if not coords:
                coords = {"x": float(idx), "y": 0.0}
            rows.append({"Station": name, "X": float(coords.get("x", 0.0)), "Y": float(coords.get("y", 0.0))})
        
        editor_df = st.data_editor(
            pd.DataFrame(rows),
            key="network_layout_editor",
            hide_index=True,
            use_container_width=True,
            column_config={
                "Station": st.column_config.TextColumn("Station", disabled=True),
                "X": st.column_config.NumberColumn("X", step=0.5),
                "Y": st.column_config.NumberColumn("Y", step=0.5),
            },
        )
        new_overrides: Dict[str, Dict[str, float]] = {}
        for _, row in editor_df.iterrows():
            name = str(row.get("Station", "")).strip()
            if not name:
                continue
            new_overrides[name] = {"x": float(row.get("X", 0.0)), "y": float(row.get("Y", 0.0))}
        if new_overrides != overrides:
            prefs["table_overrides"] = new_overrides
            state["dirty"] = True
        if st.button("Reset layout overrides", key="network_layout_reset", disabled=not overrides):
            prefs["table_overrides"] = {}
            state["dirty"] = True
            st.session_state.pop("network_layout_editor", None)
    else:
        st.caption("Automatic layout uses graph heuristics; table overrides are ignored.")
    state["layout_settings"] = copy.deepcopy(prefs)


def _persist_plan_storage() -> None:
    persist_plan_storage(
        PLAN_STORAGE_FILE,
        manual_key=MANUAL_SAVED_PLANS_KEY,
        auto_key=AUTO_SAVED_RUNS_KEY,
    )


def _ensure_plan_storage_loaded() -> None:
    ensure_plan_storage_loaded(
        PLAN_STORAGE_FILE,
        manual_key=MANUAL_SAVED_PLANS_KEY,
        auto_key=AUTO_SAVED_RUNS_KEY,
        flag_key=PLAN_STORAGE_FLAG_KEY,
    )

@st.cache_data(show_spinner=False)
def _parse_schedule(raw_bytes: bytes) -> pd.DataFrame:
    return parse_schedule_bytes(raw_bytes)


@st.cache_data(show_spinner=False)
def _summarize_schedule(raw_bytes: bytes) -> pd.DataFrame:
    df = _parse_schedule(raw_bytes)
    return summarize_schedule_dataframe(df)


def _persist_schedule(raw_bytes: bytes) -> Path:
    """Cache uploaded schedules on disk so numpy/pandas readers can consume them."""
    digest = hashlib.md5(raw_bytes).hexdigest()
    cache: Dict[str, str] = st.session_state.get(SCHEDULE_CACHE_KEY, {})
    cached_path = cache.get(digest)
    if cached_path and Path(cached_path).exists():
        return Path(cached_path)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(raw_bytes)
        tmp.flush()
        cache[digest] = tmp.name
        st.session_state[SCHEDULE_CACHE_KEY] = cache
        return Path(tmp.name)



def _segment_status_rows(sim: Optional[Simulator]) -> List[Dict[str, Any]]:
    if sim is None:
        return []
    last_maintenance: Dict[str, str] = {}
    for seg_name, date_str, _ in getattr(sim, "maintenance_log", []) or []:
        if date_str:
            last_maintenance[seg_name] = date_str
    rows: List[Dict[str, Any]] = []
    for seg in getattr(sim, "segments", []) or []:
        load_value = getattr(seg, "load", 0) or 0
        try:
            load_value = float(load_value)
        except Exception:
            pass
        rows.append({
            "Segment": seg.name,
            "Load": load_value,
            "Last Maintenance": last_maintenance.get(seg.name, "—"),
        })
    rows.sort(key=lambda item: item["Segment"])
    return rows


def _render_segment_status_table(rows: List[Dict[str, Any]], *, title: str) -> None:
    st.markdown(f"### {title}")
    if not rows:
        st.info("No segment metrics available yet.")
        return
    df = pd.DataFrame(rows)
    df["Load"] = df["Load"].map(lambda v: f"{v:,.2f}" if isinstance(v, (int, float)) else v)
    st.dataframe(df, use_container_width=True, hide_index=True)


def _ensure_manual_state() -> Dict[str, Any]:
    _ensure_plan_storage_loaded()
    return ensure_manual_state(
        config_key=MANUAL_CONFIG_KEY,
        plan_key=MANUAL_PLAN_KEY,
        result_key=MANUAL_RESULT_KEY,
        saved_plans_key=MANUAL_SAVED_PLANS_KEY,
        widget_keys=MANUAL_WIDGET_KEYS,
        network_config_provider=_current_network_config,
        station_choices_provider=_station_choices_or_default,
        facing_options_provider=_facing_options,
    )


def _ensure_auto_state() -> Dict[str, Any]:
    _ensure_plan_storage_loaded()
    return ensure_auto_state(
        config_key=AUTO_CONFIG_KEY,
        saved_runs_key=AUTO_SAVED_RUNS_KEY,
        network_config_provider=_current_network_config,
    )




def _update_manual_plan(new_plan: List[Dict[str, Any]]) -> None:
    update_manual_plan(MANUAL_PLAN_KEY, MANUAL_RESULT_KEY, new_plan)


def _force_rerun() -> None:
    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()


def _store_manual_result(sim: Optional[Simulator]) -> None:
    store_manual_result(
        result_key=MANUAL_RESULT_KEY,
        plan_key=MANUAL_PLAN_KEY,
        segment_status_builder=_segment_status_rows,
        simulator=sim,
    )


def _manual_config_changed() -> None:
    station_choices = _station_choices_or_default()
    default_start = station_choices[0]
    start_station = st.session_state.get(MANUAL_WIDGET_KEYS["start_station"], default_start)
    if start_station not in station_choices:
        start_station = default_start
        st.session_state[MANUAL_WIDGET_KEYS["start_station"]] = start_station
    facing_choices = _facing_options(start_station) or [start_station]
    facing_station = st.session_state.get(MANUAL_WIDGET_KEYS["facing_station"], facing_choices[0])
    if facing_station not in facing_choices:
        facing_station = facing_choices[0]
        st.session_state[MANUAL_WIDGET_KEYS["facing_station"]] = facing_station
    start_year = int(st.session_state.get(MANUAL_WIDGET_KEYS["start_year"], 2025))
    end_year = int(st.session_state.get(MANUAL_WIDGET_KEYS["end_year"], start_year))
    if end_year < start_year:
        end_year = start_year
        st.session_state[MANUAL_WIDGET_KEYS["end_year"]] = end_year
    second_kld = bool(st.session_state.get(MANUAL_WIDGET_KEYS["second_kld"], False))
    st.session_state[MANUAL_CONFIG_KEY] = {
        "start_station": start_station,
        "facing_station": facing_station,
        "start_year": start_year,
        "end_year": end_year,
        "second_kld": second_kld,
    }
    _update_manual_plan([])
    _force_rerun()




def _current_timeline_order() -> List[str]:
    state = st.session_state.get(NETWORK_EDITOR_STATE_KEY)
    if state and isinstance(state.get("timeline_order"), list):
        return list(state["timeline_order"])
    return _current_network_config().timeline_order


def _render_comparison() -> None:
    render_comparison_page(
        manual_result=st.session_state.get(MANUAL_RESULT_KEY),
        auto_result=st.session_state.get("_auto_result"),
        render_schedule_network_alert=_render_schedule_network_alert,
        segments=_network_segments(),
        timeline_order=_current_timeline_order() or None,
    )


def _render_manual_route() -> None:
    _ensure_manual_state()
    schedule_path = _persist_schedule(_current_schedule_bytes())
    callbacks = ManualRouteCallbacks(
        render_schedule_network_alert=_render_schedule_network_alert,
        station_choices_provider=_station_choices_or_default,
        facing_options_provider=_facing_options,
        manual_config_changed=_manual_config_changed,
        update_manual_plan=_update_manual_plan,
        force_rerun=_force_rerun,
        persist_plan_storage=_persist_plan_storage,
        store_manual_result=_store_manual_result,
        network_segments_provider=_network_segments,
        timeline_order_provider=_current_timeline_order,
        render_segment_status_table=_render_segment_status_table,
    )
    session_keys = ManualRouteSessionKeys(
        config_key=MANUAL_CONFIG_KEY,
        plan_key=MANUAL_PLAN_KEY,
        result_key=MANUAL_RESULT_KEY,
        saved_plans_key=MANUAL_SAVED_PLANS_KEY,
        widget_keys=MANUAL_WIDGET_KEYS,
    )
    render_manual_route_page(
        schedule_path=schedule_path,
        network_file_path=_current_network_file_path(),
        callbacks=callbacks,
        session_keys=session_keys,
    )


def _render_matplotlib_image(fig, *, alt_text: str = "Visualization") -> Optional[bytes]:
    if fig is None:
        st.info("Unable to generate the requested figure.")
        return None
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    buffer.seek(0)
    png_bytes = buffer.getvalue()
    encoded = base64.b64encode(png_bytes).decode("ascii")
    st.markdown(
        f'<img src="data:image/png;base64,{encoded}" alt="{alt_text}" '
        "style='max-width:100%; height:auto; display:block; margin:auto;' />",
        unsafe_allow_html=True,
    )
    plt.close(fig)
    return png_bytes


def _network_figure():
    config = _current_network_config()
    layout_entry = _layout_preferences_for_path()
    try:
        scale_factor = float(layout_entry.get("scale", NETWORK_LAYOUT_SCALE))
    except (TypeError, ValueError):
        scale_factor = NETWORK_LAYOUT_SCALE
    scale_factor = min(max(scale_factor, NETWORK_LAYOUT_SCALE_MIN), NETWORK_LAYOUT_SCALE_MAX)
    fig_size = max(4.0, 6.0 * scale_factor)
    fig, ax = plt.subplots(figsize=(fig_size, fig_size))
    graph = nx.MultiDiGraph()
    for station in config.stations.values():
        graph.add_node(station.name)
    for segment in config.segments:
        graph.add_edge(
            segment.start_station.name,
            segment.end_station.name,
            key=segment.name,
            label=segment.name,
        )
    if graph.number_of_nodes() == 0:
        ax.text(0.5, 0.5, "No stations configured", ha="center", va="center")
        ax.set_axis_off()
        fig.tight_layout()
        return fig
    pos = _table_layout_positions(config)
    if not pos:
        pos = automatic_layout_positions(graph)

    coords = list(pos.values())
    xs = [coord[0] for coord in coords] or [0.0]
    ys = [coord[1] for coord in coords] or [0.0]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    pad_x = max(0.5, (max_x - min_x) * 0.15 or 0.5)
    pad_y = max(0.5, (max_y - min_y) * 0.15 or 0.5)
    ax.set_xlim(min_x - pad_x, max_x + pad_x)
    ax.set_ylim(min_y - pad_y, max_y + pad_y)
    ax.set_axisbelow(True)
    ax.set_aspect("equal", adjustable="box")

    def _axis_ticks(low: float, high: float) -> List[float]:
        span = max(high - low, 1e-6)
        if span <= 10:
            step = 1
        elif span <= 20:
            step = 2
        else:
            step = max(1, math.ceil(span / 10))
        start = math.floor(low)
        end = math.ceil(high)
        ticks: list[float] = [float(x) for x in range(start, end + 1, step)] or [0.0]
        if len(ticks) > 15:
            step = max(step, math.ceil((end - start) / 15) or 1)
            ticks = [float(x) for x in range(start, end + 1, step)] or [0.0]
        return ticks

    xtick_vals = [float(val) for val in _axis_ticks(min_x - pad_x, max_x + pad_x)]
    ytick_vals = [float(val) for val in _axis_ticks(min_y - pad_y, max_y + pad_y)]

    def _format_tick(value: float) -> str:
        if abs(value - round(value)) <= 1e-6:
            return f"{int(round(value))}"
        return f"{value:.1f}"

    ax.set_xticks(xtick_vals)
    ax.set_yticks(ytick_vals)
    tick_formatter = FuncFormatter(lambda value, _pos: _format_tick(value))
    ax.xaxis.set_major_formatter(tick_formatter)
    ax.yaxis.set_major_formatter(tick_formatter)
    ax.tick_params(
        axis="both",
        which="major",
        labelsize=9,
        colors="#303030",
        bottom=True,
        left=True,
        top=True,
        right=True,
        labelbottom=True,
        labelleft=True,
        labeltop=True,
        labelright=True,
    )
    ax.set_xlabel("X position")
    ax.set_ylabel("Y position")
    ax.grid(True, which="major", color="#D0D0D0", linewidth=0.6, linestyle="-", alpha=0.85)
    ax.axhline(0, color="#B0B0B0", linewidth=0.6, zorder=0)
    ax.axvline(0, color="#B0B0B0", linewidth=0.6, zorder=0)

    nx.draw_networkx_nodes(graph, pos, node_size=700, node_color="#B3DAF1", ax=ax)
    nx.draw_networkx_labels(graph, pos, font_size=10, ax=ax)
    for segment in config.segments:
        u = segment.start_station.name
        v = segment.end_station.name
        if "Carregado" in segment.name:
            color = "#1f77b4"
            rad = 0.35
        elif "Vazio" in segment.name:
            color = "#2ca02c"
            rad = -0.35
        else:
            color = "#7f7f7f"
            rad = 0.0
        nx.draw_networkx_edges(
            graph,
            pos,
            edgelist=[(u, v)],
            connectionstyle=f"arc3,rad={rad}",
            edge_color=color,
            arrows=True,
            ax=ax,
        )
    fig.tight_layout()
    return fig

def _render_schedule_view(schedule_df: pd.DataFrame, summary: pd.DataFrame) -> None:
    render_schedule_page(
        schedule_df,
        summary,
        render_schedule_network_alert=_render_schedule_network_alert,
    )


def _render_mtbt_editor() -> None:
    callbacks = MtbtEditorCallbacks(
        state_key=NETWORK_EDITOR_STATE_KEY,
        ensure_state=_ensure_network_editor_state,
        render_schedule_network_alert=_render_schedule_network_alert,
        force_rerun=_force_rerun,
        current_network_file_path=_current_network_file_path,
        parse_schedule_bytes=_parse_schedule,
    )
    render_mtbt_editor_page(
        default_schedule=DEFAULT_SCHEDULE,
        callbacks=callbacks,
    )


def _render_network_editor() -> None:
    callbacks = NetworkEditorCallbacks(
        state_key=NETWORK_EDITOR_STATE_KEY,
        ensure_state=_ensure_network_editor_state,
        current_config=_current_network_config,
        current_path=_current_network_file_path,
        render_schedule_network_alert=_render_schedule_network_alert,
        consume_flash=_consume_network_editor_flash,
        consume_refresh_notice=_consume_network_editor_refresh_notice,
        schedule_refresh_notice=_schedule_network_editor_refresh,
        dataframe_signature=_dataframe_signature,
        serialize_state=_serialize_network_editor_state,
        write_network_payload=_write_network_payload,
        network_file_digest=_network_file_digest,
        set_flash=_set_network_editor_flash,
        apply_network_change=_apply_network_change,
        clear_widgets=_clear_network_editor_widgets,
        force_rerun=_force_rerun,
        render_network_layout_controls=_render_network_layout_controls,
        network_figure_factory=_network_figure,
        render_matplotlib_image=_render_matplotlib_image,
        create_blank_network_file=_create_blank_network_file,
        duplicate_active_network_file=_duplicate_active_network_file,
        import_uploaded_network=_import_uploaded_network,
        delete_network_file=_delete_network_file,
        network_file_candidates=lambda: list(_network_file_mapping().values()),
    )
    render_network_editor_page(callbacks=callbacks)

def _render_network_selector() -> None:
    mapping = _network_file_mapping()
    current_path = _ensure_active_network_path()
    
    # Set up options with a placeholder for "no selection"
    placeholder_label = "-- Select a network --"
    options = [placeholder_label] + list(mapping.keys())
    
    if current_path:
        path_to_label = {path: label for label, path in mapping.items()}
        default_label = path_to_label.get(current_path, placeholder_label)
    else:
        default_label = placeholder_label
    
    pending_label = st.session_state.pop(NETWORK_SELECT_PENDING_LABEL_KEY, None)
    st.session_state.setdefault(NETWORK_SELECT_LABEL_KEY, default_label)
    if pending_label is not None:
        st.session_state[NETWORK_SELECT_LABEL_KEY] = pending_label
    if st.session_state[NETWORK_SELECT_LABEL_KEY] not in options:
        st.session_state[NETWORK_SELECT_LABEL_KEY] = default_label
    
    # Network selector with quick create button
    col_select, col_create = st.columns([3, 1])
    with col_select:
        selected_label = st.selectbox("Select Network", options, key=NETWORK_SELECT_LABEL_KEY, label_visibility="visible")
    with col_create:
        st.write("")  # Spacing to align with selectbox
        if st.button("➕", help="Create new network", use_container_width=True):
            # Create a new blank network and switch to it
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            new_name = f"Network_{timestamp}"
            new_path = _create_blank_network_file(new_name, include_sample=False)
            _apply_network_change(new_path, label_hint=new_name)
            st.session_state[NAVIGATION_PAGE_KEY] = "Network Editor"
            _force_rerun()
    
    # Only apply network change if a real network is selected (not placeholder)
    if selected_label != placeholder_label:
        selected_path = mapping[selected_label]
        st.caption(f"📁 {Path(selected_path).name}")
        if selected_path != current_path:
            _apply_network_change(selected_path, label_hint=selected_label)
    else:
        st.caption("👆 Please select a network to get started")

def _render_auto_simulation() -> None:
    callbacks = AutoSimulationCallbacks(
        render_schedule_network_alert=_render_schedule_network_alert,
        schedule_path_provider=_current_schedule_path,
        ensure_auto_state=_ensure_auto_state,
        station_choices_provider=_station_choices_or_default,
        facing_options_provider=_facing_options,
        network_file_path_provider=_current_network_file_path,
        network_segments_provider=_network_segments,
        timeline_order_provider=_current_timeline_order,
        segment_status_builder=_segment_status_rows,
        render_segment_status_table=_render_segment_status_table,
        persist_plan_storage=_persist_plan_storage,
        force_rerun=_force_rerun,
    )
    session_keys = AutoSimulationSessionKeys(
        config_key=AUTO_CONFIG_KEY,
        result_key="_auto_result",
        saved_runs_key=AUTO_SAVED_RUNS_KEY,
    )
    render_auto_simulation_page(callbacks=callbacks, session_keys=session_keys)

def main() -> None:
    st.set_page_config(page_title="Railroad Maintenance Dashboard", layout="wide")
    
    # Inject custom CSS for enhanced visuals
    inject_custom_css()
    
    st.title("🚂 Railroad Maintenance Simulator")
    
    # Quick Start Guide - always visible
    with st.expander("🚀 Quick Start Guide", expanded=False):
        st.markdown("""
        1. **Select an existing network** from the dropdown in the sidebar
        2. **Or create a new network** by clicking the ➕ button
        3. Configure your network in the **Network Editor**
        4. Set up maintenance schedules in the **MTBT Editor**
        5. Run **Auto Simulation** or create **Manual Routes**
        6. **Compare** different scenarios
        """)
    
    # Workflow stepper showing the typical usage flow - moved to main area
    workflow_steps = [
        ("network", "Configure Network"),
        ("schedule", "Set MTBT"),
        ("simulate", "Run Simulation"),
        ("analyze", "Analyze Results"),
    ]
    
    # ============================================
    # ORGANIZED SIDEBAR WITH CLEAR SECTIONS
    # ============================================
    
    # Section 1: Navigation
    st.sidebar.markdown("### 📍 Navigation")
    pages = (
        "Network Editor",
        "MTBT Editor",
        "Auto Simulation",
        "Manual Route",
        "Comparison",
    )
    st.session_state.setdefault(NAVIGATION_PAGE_KEY, pages[0])
    if st.session_state[NAVIGATION_PAGE_KEY] not in pages:
        st.session_state[NAVIGATION_PAGE_KEY] = pages[0]
    page = st.sidebar.radio("Go to", pages, key=NAVIGATION_PAGE_KEY, label_visibility="collapsed")
    
    st.sidebar.divider()
    
    # Section 2: Active Network Configuration (always expanded)
    st.sidebar.markdown("### ⚙️ Active Network")
    _render_network_selector()
    
    # Add navigation buttons as part of network workflow
    col1, col2 = st.sidebar.columns(2)
    
    def _navigate_to_network_editor():
        st.session_state[NAVIGATION_PAGE_KEY] = "Network Editor"
    
    def _navigate_to_mtbt_editor():
        st.session_state[NAVIGATION_PAGE_KEY] = "MTBT Editor"
    
    with col1:
        st.button(
            "📝 Edit Network",
            use_container_width=True,
            on_click=_navigate_to_network_editor,
            help="Configure stations and segments"
        )
    
    with col2:
        st.button(
            "📅 Edit Schedule",
            use_container_width=True,
            on_click=_navigate_to_mtbt_editor,
            help="Manage MTBT schedule"
        )
    
    st.sidebar.divider()
    
    # Section 3: Status & Warnings (only if network is selected)
    current_network_path = _current_network_file_path()
    if current_network_path:
        try:
            schedule_df = _current_schedule_dataframe()
            if schedule_df is not None:
                raw_bytes = schedule_df.to_csv(index=False).encode("utf-8")
                summary_df = _summarize_schedule(raw_bytes)
        except ValueError as exc:
            st.error(f"Schedule validation failed: {exc}")
            st.stop()
        
        state = _ensure_network_editor_state()
        if state and schedule_df is not None:
            missing_segments = _update_schedule_network_warnings(schedule_df)
        else:
            missing_segments = []
    else:
        schedule_df = None
        state = None
        missing_segments = []
    
    if current_network_path and state:
        with st.sidebar.expander("📊 Status", expanded=False):
            st.caption("**Active Network:**")
            st.caption(f"{state.get('display_name') or Path(state.get('path', '')).name}")
            st.caption(f"📁 `{Path(state.get('path', '')).name}`")
            
            st.caption("**MTBT Schedule:**")
            st.caption(f"Linked to: {state.get('display_name') or Path(state.get('path', '')).name}")
            
            if missing_segments:
                st.warning(
                    f"⚠️ {len(missing_segments)} segment(s) in schedule are missing from network",
                    icon="⚠️"
                )
            else:
                st.success("✅ Schedule & network aligned", icon="✅")
    
    st.sidebar.divider()
    
    # Section 4: Quick Stats (only show if network is selected)
    if current_network_path:
        config = _current_network_config()
        with st.sidebar.expander("📈 Quick Stats", expanded=False):
            st.metric("Stations", len(config.stations))
            st.metric("Segments", len(config.segments))
            if schedule_df is not None:
                st.metric("Scheduled Segments", len(schedule_df))
    
    st.sidebar.divider()
    
    # Section 5: Accessibility Options
    with st.sidebar.expander("♿ Accessibility", expanded=False):
        render_accessibility_widget()
    
    # Check if a network is selected
    current_network_path = _current_network_file_path()
    if not current_network_path:
        # No network selected - show welcome message
        st.caption("👈 Please select a network from the sidebar to get started, or create a new one using the ➕ button.")
        return  # Stop rendering the rest of the page
    
    # Show workflow stepper in main area below title
    page_to_step = {
        "Network Editor": 0,
        "MTBT Editor": 1,
        "Auto Simulation": 2,
        "Manual Route": 2,
        "Comparison": 3,
    }
    current_step = page_to_step.get(page, 0)
    render_workflow_stepper(workflow_steps, current_step)
    
    if page == "Network Editor":
        _render_network_editor()
    elif page == "MTBT Editor":
        _render_mtbt_editor()
    elif page == "Auto Simulation":
        _render_auto_simulation()
    elif page == "Manual Route":
        _render_manual_route()
    elif page == "Comparison":
        _render_comparison()
    else:  # pragma: no cover - fallback safeguard
        _render_network_editor()


if __name__ == "__main__":
    main()
