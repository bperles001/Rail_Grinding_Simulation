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
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib
# Headless web app - never renders to a screen, only serves figures as PNG
# bytes (see _render_matplotlib_image). Force the non-interactive Agg backend
# instead of relying on matplotlib's auto-selection, which can land on a GUI
# backend (e.g. TkAgg) that isn't safe to touch outside its owning thread and
# crashes when Streamlit runs script code in a worker thread.
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import streamlit as st
from matplotlib.patches import FancyArrowPatch
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
from railroad_backend.domain.network_layout import (
    automatic_layout_positions,
    automatic_station_layout,
    build_adjacency_map,
    project_geographic_coordinates,
    schematic_layout_from_seed,
)
from src.simulator import DEFAULT_NETWORK_FILE, Simulator
from railroad_backend.domain.network_editor import (
    network_editor_segment_df,
    network_editor_station_df,
    parse_station_coordinates,
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
PLAN_STORAGE_FILE = Path(os.environ.get("MANUAL_PLAN_STORAGE_FILE") or (DATA_DIR / "saved_plans.json"))
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
                "mtbt_threshold_curva": 1000.0,
                "mtbt_threshold_tangente": 1000.0,
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
    segment_names = [segment.name for segment in _current_network_segments()]
    missing = schedule_missing_segments(schedule_df, segment_names)
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

        with st.expander("📍 Importar coordenadas GPS", expanded=False):
            st.caption(
                "Cole uma linha por estação: NOME, LATITUDE, LONGITUDE "
                "(vírgula ou tab, direto do Excel). O sistema preserva a "
                "direção real entre estações vizinhas mas normaliza o "
                "espaçamento entre elas."
            )
            gps_text = st.text_area(
                "Coordenadas GPS", key="network_layout_gps_text", height=150
            )
            if st.button("Aplicar e normalizar posições", key="network_layout_gps_apply"):
                parsed, parse_messages = parse_station_coordinates(gps_text)
                station_set = set(state["stations_df"]["Name"].astype(str).tolist())
                unknown = sorted(set(parsed) - station_set)
                usable = {name: coords for name, coords in parsed.items() if name in station_set}
                for msg in parse_messages:
                    st.warning(msg)
                if unknown:
                    st.warning(
                        f"Estação(ões) não encontrada(s) na rede, ignorada(s): {', '.join(unknown)}."
                    )
                if usable:
                    projected = project_geographic_coordinates(usable)
                    schematic = schematic_layout_from_seed(
                        build_adjacency_map(config.segments),
                        projected,
                        spacing=3.0,
                    )
                    if schematic:
                        merged_overrides = dict(overrides)
                        merged_overrides.update(
                            {name: {"x": x, "y": y} for name, (x, y) in schematic.items()}
                        )
                        prefs["table_overrides"] = merged_overrides
                        overrides = merged_overrides
                        state["dirty"] = True
                        st.session_state.pop("network_layout_editor", None)
                        st.success(f"{len(schematic)} estação(ões) reposicionada(s).")
                    else:
                        st.warning("Nenhuma estação com dados suficientes para calcular posição.")
                elif not unknown:
                    st.warning("Nenhuma coordenada válida encontrada no texto colado.")

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
        
        with st.form("network_layout_form", clear_on_submit=False):
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
            layout_submit = st.form_submit_button("Apply layout changes")
        if layout_submit:
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
        load_curva = getattr(seg, "load_curva", 0) or 0
        load_tangente = getattr(seg, "load_tangente", 0) or 0
        try:
            load_curva = float(load_curva)
            load_tangente = float(load_tangente)
        except Exception:
            pass
        rows.append({
            "Segment": seg.name,
            "Load Curva": load_curva,
            "Load Tangente": load_tangente,
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
    for col in ("Load Curva", "Load Tangente"):
        df[col] = df[col].map(lambda v: f"{v:,.2f}" if isinstance(v, (int, float)) else v)
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
    if isinstance(fig, (bytes, bytearray)):
        png_bytes = bytes(fig)
    else:
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", bbox_inches="tight")
        buffer.seek(0)
        png_bytes = buffer.getvalue()
        plt.close(fig)
    encoded = base64.b64encode(png_bytes).decode("ascii")
    st.markdown(
        f'<img src="data:image/png;base64,{encoded}" alt="{alt_text}" '
        "style='max-width:100%; height:auto; display:block; margin:auto;' />",
        unsafe_allow_html=True,
    )
    return png_bytes


def _figure_to_png(fig) -> Optional[bytes]:
    if fig is None:
        return None
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()


@st.cache_data(show_spinner=False, max_entries=16)
def _network_sketch_png_cached(path: str, digest: str, layout_json: str) -> Optional[bytes]:
    # path/digest/layout_json capture every input that affects the sketch;
    # the body reads them via the regular session helpers.
    return _figure_to_png(_network_figure())


def _network_sketch_payload():
    """Cached PNG of the network sketch; falls back to a live figure when
    there is no active network file to key the cache on."""
    file_path = _current_network_file_path()
    if file_path is None or not file_path.exists():
        return _network_figure()
    layout_json = json.dumps(
        _layout_preferences_for_path(), sort_keys=True, default=str
    )
    return _network_sketch_png_cached(
        str(file_path), _network_file_digest(file_path), layout_json
    )


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

    STATION_NODE_COLOR = "#B3DAF1"
    CAN_TURN_NODE_COLOR = "#FFB74D"
    node_colors = [
        CAN_TURN_NODE_COLOR if config.stations[name].can_turn else STATION_NODE_COLOR
        for name in graph.nodes()
    ]

    # Segments between the same station pair come in up to three flavors:
    # a bidirectional "trunk" (Singela - shared track, both directions) and
    # up to two directional ones (Carregado/"-LP" = export direction,
    # Vazio/"-LD" = import direction).
    #
    # Where all three exist, the physical layout is a shared track that
    # splits into two parallel tracks around a crossing yard and rejoins.
    # Drawn per the user's reference sketch: the trunk is one continuous
    # black line the full station-to-station distance; Carregado (green)
    # and Vazio (blue) are a flattened lens overlaid on top of it - two
    # straight risers converging near each station, a flat parallel section
    # in the middle - matching real trackwork: Linha Principal (Carregado)
    # IS the straight through-track, so it's drawn inline with no offset;
    # Linha Desviada (Vazio) is the siding, so it's the one that actually
    # bows away from the straight line and rejoins it, for a shorter,
    # centered stretch. No arrowheads on the loop (the shape plus the color
    # legend already carry the direction meaning).
    #
    # Where only Carregado+Vazio exist (no shared track, e.g. SP Sul), keep
    # the earlier smooth-arc-with-arrowhead rendering spanning the full
    # distance - already confirmed readable. Where only the trunk exists,
    # a single straight black line as before.
    TRUNK_COLOR = "#000000"
    CARREGADO_COLOR = "#2ca02c"  # green = LP / Carregado = export direction
    VAZIO_COLOR = "#1f77b4"  # blue = LD / Vazio = import direction
    PARALLEL_OFFSET_FRACTION = 0.08
    # Singela (black) is the real long-haul track; the yard where it splits
    # into Principal/Desviada is short by comparison. Keep the inline green
    # (Carregado) section the same length as the blue (Vazio) loop, both
    # spanning just the middle - not most of the segment - so black stays
    # dominant, like the real proportions.
    TRUNK_END_FRACTION = 0.35  # black portion at each end
    LOOP_START_FRACTION = 0.35  # where Vazio splits off the straight line
    LOOP_END_FRACTION = 0.65  # where Vazio rejoins the straight line
    LOOP_RISE = 0.06  # fraction of span spent rising/falling into the loop
    LOOP_OFFSET_FRACTION = 0.14

    def _segment_direction(name: str) -> str:
        if "Carregado" in name or name.endswith("-LP") or name.endswith("-C"):
            return "carregado"
        if "Vazio" in name or name.endswith("-LD") or name.endswith("-V"):
            return "vazio"
        return "trunk"

    def _draw_edge(p_from: np.ndarray, p_to: np.ndarray, *, color: str, rad: float, arrow: bool) -> None:
        patch = FancyArrowPatch(
            tuple(p_from),
            tuple(p_to),
            connectionstyle=f"arc3,rad={rad}",
            arrowstyle="-|>" if arrow else "-",
            color=color,
            linewidth=2.0,
            mutation_scale=14,
            shrinkA=10,
            shrinkB=10,
            zorder=1,
        )
        ax.add_patch(patch)

    def _draw_polyline(points: List[np.ndarray], *, color: str) -> None:
        ax.plot(
            [p[0] for p in points],
            [p[1] for p in points],
            color=color,
            linewidth=2.0,
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=2,
        )

    def _draw_siding_loop(p_start: np.ndarray, p_end: np.ndarray, *, color: str) -> None:
        span = p_end - p_start
        length = float(np.linalg.norm(span))
        if length < 1e-9:
            return
        unit = span / length
        perp = np.array([-unit[1], unit[0]]) * (LOOP_OFFSET_FRACTION * length)
        points = [
            p_start + LOOP_START_FRACTION * span,
            p_start + (LOOP_START_FRACTION + LOOP_RISE) * span + perp,
            p_start + (LOOP_END_FRACTION - LOOP_RISE) * span + perp,
            p_start + LOOP_END_FRACTION * span,
        ]
        _draw_polyline(points, color=color)

    def _draw_parallel_line(p_from: np.ndarray, p_to: np.ndarray, *, color: str, side: float) -> None:
        # Straight line offset perpendicular to the from->to direction, used
        # for station pairs with only Carregado+Vazio (no shared Singela) -
        # two straight, parallel tracks the full distance, not a curved arc.
        span = p_to - p_from
        length = float(np.linalg.norm(span))
        if length < 1e-9:
            _draw_edge(p_from, p_to, color=color, rad=0.0, arrow=True)
            return
        unit = span / length
        perp = np.array([-unit[1], unit[0]]) * (PARALLEL_OFFSET_FRACTION * length) * side
        _draw_edge(p_from + perp, p_to + perp, color=color, rad=0.0, arrow=True)

    segments_by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for segment in config.segments:
        pair_key = tuple(sorted((segment.start_station.name, segment.end_station.name)))
        segments_by_pair.setdefault(pair_key, {})[_segment_direction(segment.name)] = segment

    has_lens = False
    has_arc_fork = False
    for by_kind in segments_by_pair.values():
        trunk = by_kind.get("trunk")
        carregado = by_kind.get("carregado")
        vazio = by_kind.get("vazio")
        anchor = trunk or carregado or vazio
        if anchor is None:
            continue
        p_start = np.array(pos[anchor.start_station.name], dtype=float)
        p_end = np.array(pos[anchor.end_station.name], dtype=float)

        if trunk and carregado and vazio:
            has_lens = True
            span = p_end - p_start
            p_black_a = p_start + TRUNK_END_FRACTION * span
            p_black_b = p_start + (1 - TRUNK_END_FRACTION) * span
            _draw_polyline([p_start, p_black_a], color=TRUNK_COLOR)
            _draw_polyline([p_black_a, p_black_b], color=CARREGADO_COLOR)
            _draw_polyline([p_black_b, p_end], color=TRUNK_COLOR)
            _draw_siding_loop(p_start, p_end, color=VAZIO_COLOR)
        elif carregado and vazio:
            has_arc_fork = True
            for seg, color, side in ((carregado, CARREGADO_COLOR, 1.0), (vazio, VAZIO_COLOR, -1.0)):
                forward = seg.start_station.name == anchor.start_station.name
                seg_from, seg_to = (p_start, p_end) if forward else (p_end, p_start)
                _draw_parallel_line(seg_from, seg_to, color=color, side=side if forward else -side)
        elif trunk:
            _draw_polyline([p_start, p_end], color=TRUNK_COLOR)
        else:
            seg = carregado or vazio
            color = CARREGADO_COLOR if carregado else VAZIO_COLOR
            _draw_edge(p_start, p_end, color=color, rad=0.0, arrow=True)

    # Drawn after all segment lines so nodes and labels always render on top.
    # Node size large enough that the 3-letter station code fits inside the
    # circle instead of floating beside it (which got cluttered/hard to read
    # once segments got their own line-color coding).
    nx.draw_networkx_nodes(graph, pos, node_size=900, node_color=node_colors, ax=ax)
    for station_name, (node_x, node_y) in pos.items():
        ax.annotate(
            station_name,
            xy=(node_x, node_y),
            ha="center",
            va="center",
            fontsize=9,
            fontweight="bold",
            zorder=4,
        )

    legend_handles = []
    if any(station.can_turn for station in config.stations.values()):
        legend_handles.append(ax.scatter([], [], s=90, color=CAN_TURN_NODE_COLOR, label="Can turn"))
        legend_handles.append(ax.scatter([], [], s=90, color=STATION_NODE_COLOR, label="Regular station"))
    if has_lens or has_arc_fork:
        legend_handles.append(ax.plot([], [], color=TRUNK_COLOR, linewidth=2.0, label="Singela (both directions)")[0])
        legend_handles.append(ax.plot([], [], color=CARREGADO_COLOR, linewidth=2.0, label="Carregado / LP (export)")[0])
        legend_handles.append(ax.plot([], [], color=VAZIO_COLOR, linewidth=2.0, label="Vazio / LD (import)")[0])
    if legend_handles:
        ax.legend(handles=legend_handles, loc="upper left", fontsize=8, framealpha=0.9)

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
        network_figure_factory=_network_sketch_payload,
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
        except ValueError as exc:
            st.error(f"Schedule validation failed: {exc}")
            st.stop()

        state = _ensure_network_editor_state()
        if state and schedule_df is not None:
            # Validation + missing-segment check memoized by content: only
            # recompute when the schedule or the network actually changed.
            sched_sig = _dataframe_signature(schedule_df)
            net_digest = _network_file_digest(current_network_path)
            cached_check = st.session_state.get("_sidebar_schedule_check")
            if (
                not cached_check
                or cached_check.get("sched_sig") != sched_sig
                or cached_check.get("net_digest") != net_digest
            ):
                try:
                    _summarize_schedule(schedule_df.to_csv(index=False).encode("utf-8"))
                except ValueError as exc:
                    st.error(f"Schedule validation failed: {exc}")
                    st.stop()
                missing_segments = _update_schedule_network_warnings(schedule_df)
                st.session_state["_sidebar_schedule_check"] = {
                    "sched_sig": sched_sig,
                    "net_digest": net_digest,
                    "missing": missing_segments,
                }
            else:
                missing_segments = cached_check["missing"]
                st.session_state[SCHEDULE_WARNING_KEY] = missing_segments
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
