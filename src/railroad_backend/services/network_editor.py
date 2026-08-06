"""Pure helpers for the network editor state machine."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import pandas as pd

from railroad_backend.domain.network_editor import (
    parse_allowed_movements_field,
    parse_spur_text,
    spur_rows_from_text,
    spur_text_from_rows,
)
from src.railroad_backend.domain.schedule import normalize_mtbt_dataframe

if TYPE_CHECKING:
    from src.utils.network_loader import NetworkConfig

DEFAULT_STATION_FALLBACK = "Station"


def set_state_mtbt_df(state: Dict[str, Any], df: pd.DataFrame) -> None:
    """Update state with normalized MTBT dataframe and signature.

    Args:
        state: Session state dictionary.
        df: MTBT dataframe to store.
    """
    state["mtbt_df"] = normalize_mtbt_dataframe(df)
    state["_mtbt_signature"] = dataframe_signature(state["mtbt_df"])


def default_segment_name_sequence(state: Dict[str, Any]) -> List[str]:
    """Extract ordered list of segment names from state.

    Args:
        state: Session state containing segments_df.

    Returns:
        List of segment names, or empty list if none defined.
    """
    segments_df = state.get("segments_df")
    if segments_df is None or segments_df.empty:
        return []
    return [
        str(name).strip()
        for name in segments_df["Name"].astype(str).tolist()
        if str(name).strip()
    ]


def station_choices_from_config(config: "NetworkConfig") -> List[str]:
    """Get ordered station list from network config.

    Args:
        config: Network configuration.

    Returns:
        List of station names in alphabetical order.
    """
    return sorted(config.stations.keys()) or [DEFAULT_STATION_FALLBACK]


def default_start_station_from_config(config: "NetworkConfig") -> str:
    """Get default start station from network config.

    Args:
        config: Network configuration.

    Returns:
        First station name from choices.
    """
    choices = station_choices_from_config(config)
    return choices[0]


def facing_options_from_config(config: "NetworkConfig", start_station: str) -> List[str]:
    """Get list of stations adjacent to start_station.

    Args:
        config: Network configuration.
        start_station: Station name to find neighbors for.

    Returns:
        Sorted list of adjacent station names.
    """
    adjacency: Dict[str, set[str]] = {}
    for segment in config.segments:
        adjacency.setdefault(segment.start_station.name, set()).add(segment.end_station.name)
        adjacency.setdefault(segment.end_station.name, set()).add(segment.start_station.name)
    options = sorted(adjacency.get(start_station, []))
    return options if options else [start_station]


def default_facing_station_from_config(
    config: "NetworkConfig",
    start_station: Optional[str] = None,
) -> str:
    """Get default facing station from network config.

    Args:
        config: Network configuration.
        start_station: Optional start station, uses default if None.

    Returns:
        First adjacent station name.
    """
    start = start_station or default_start_station_from_config(config)
    options = facing_options_from_config(config, start)
    return options[0] if options else start


def sync_mtbt_dataframe_with_segments(state: Dict[str, Any]) -> None:
    """Synchronize MTBT dataframe rows with current segment definitions.

    Args:
        state: Session state containing segments_df and mtbt_df.
    """
    existing_df = state.get("mtbt_df")
    if existing_df is None:
        existing_df = pd.DataFrame()
    df = normalize_mtbt_dataframe(existing_df)
    segments_df = state.get("segments_df")
    if df is None or segments_df is None:
        return
    if "Segment Name" not in df.columns:
        df.insert(0, "Segment Name", "")
    df["Segment Name"] = df["Segment Name"].astype(str).str.strip()
    segment_names = default_segment_name_sequence(state)
    existing = {row["Segment Name"]: row for row in df.to_dict("records") if row.get("Segment Name")}
    columns = list(df.columns)
    records: List[Dict[str, Any]] = []
    for name in segment_names:
        record = existing.get(name)
        if not record:
            record = {col: 0.0 for col in columns if col != "Segment Name"}
            record["Segment Name"] = name
        records.append(dict(record))  # type: ignore[arg-type]
    new_df = pd.DataFrame(records, columns=columns)
    new_df = normalize_mtbt_dataframe(new_df)
    if not new_df.equals(df):
        set_state_mtbt_df(state, new_df)
        state["dirty"] = True


def month_label(year: int, month: int) -> str:
    """Format year and month into YYYY-MM string label.

    Args:
        year: Four-digit year.
        month: Month number (1-12).

    Returns:
        Formatted string like "2025-03".
    """
    return f"{int(year):04d}-{int(month):02d}"


def add_month_with_backfill(df: pd.DataFrame, year: int, month: int, default: float) -> Tuple[pd.DataFrame, List[str]]:
    """Add a month column to MTBT dataframe, backfilling earlier months if needed.

    Args:
        df: MTBT dataframe with segment names and month columns.
        year: Target year.
        month: Target month (1-12).
        default: Default MTBT value for new columns.

    Returns:
        Tuple of (updated dataframe, list of inserted month labels).
    """
    df = normalize_mtbt_dataframe(df)
    inserted: List[str] = []
    target = month_label(year, month)
    if target not in df.columns:
        df[target] = default
        inserted.append(target)
    prev_month = month - 1
    while prev_month >= 1:
        prev_label = month_label(year, prev_month)
        if prev_label in df.columns:
            break
        df[prev_label] = default
        inserted.append(prev_label)
        prev_month -= 1
    return normalize_mtbt_dataframe(df), sorted(inserted)


def network_file_digest(path: Path) -> str:
    """Compute MD5 hash of network file for change detection.

    Args:
        path: Path to network JSON file.

    Returns:
        Hex string of MD5 digest, or empty string if file not found.
    """
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return ""


_ALLOWED_DIRECTION_CHOICES = (
    "Both directions",
    "Start→End only",
)


def infer_allowed_direction_label(movements_text: str, start: str, end: str) -> str:
    start = (start or "").strip()
    end = (end or "").strip()
    if not start or not end:
        return _ALLOWED_DIRECTION_CHOICES[0]
    try:
        moves = parse_allowed_movements_field(movements_text, start, end)
    except ValueError:
        return _ALLOWED_DIRECTION_CHOICES[0]
    normalized = {(src, dst) for src, dst in moves if src and dst}
    both = {(start, end), (end, start)}
    if normalized == {(start, end)}:
        return _ALLOWED_DIRECTION_CHOICES[1]
    if normalized == both:
        return _ALLOWED_DIRECTION_CHOICES[0]
    return _ALLOWED_DIRECTION_CHOICES[0]


def allowed_movements_text_from_choice(choice: str, start: str, end: str, fallback: str) -> str:
    start = (start or "").strip()
    end = (end or "").strip()
    if not start or not end:
        return fallback
    if choice == _ALLOWED_DIRECTION_CHOICES[1]:
        pairs = [[start, end]]
    else:
        pairs = [[start, end], [end, start]]
    return "\n".join("->".join(pair) for pair in pairs)


def segment_endpoint_status(start: str, end: str, valid_names: List[str]) -> str:
    start = (start or "").strip()
    end = (end or "").strip()
    missing_parts = []
    if start and start not in valid_names:
        missing_parts.append(f"Start '{start}' missing")
    if end and end not in valid_names:
        missing_parts.append(f"End '{end}' missing")
    if not start:
        missing_parts.append("Start required")
    if not end:
        missing_parts.append("End required")
    return "; ".join(missing_parts) if missing_parts else "✔"


def dataframe_signature(df: Optional[pd.DataFrame]) -> str:
    if df is None:
        return "__none__"
    if df.empty:
        columns = list(df.columns)
        return json.dumps({"columns": columns, "data": []}, ensure_ascii=False)
    normalized = df.copy(deep=True)
    normalized = normalized.replace({pd.NA: None})
    # Convert NaN to None
    normalized = normalized.map(lambda x: None if pd.isna(x) else x)  # type: ignore[arg-type,return-value]
    snapshot = {
        "columns": list(normalized.columns),
        "data": normalized.values.tolist(),
    }
    return json.dumps(snapshot, ensure_ascii=False)


def network_editor_diff_summary(original: Dict[str, Any], updated: Dict[str, Any]) -> List[str]:
    def _station_map(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {entry.get("name"): entry for entry in payload.get("stations", []) or [] if entry.get("name")}

    def _segment_map(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {entry.get("name"): entry for entry in payload.get("segments", []) or [] if entry.get("name")}

    lines: List[str] = []
    if (original.get("name") or "").strip() != (updated.get("name") or "").strip():
        old_name = original.get("name") or "(unnamed)"
        new_name = updated.get("name") or "(unnamed)"
        lines.append(f"Renamed network: {old_name} -> {new_name}")
    orig_station_map = _station_map(original)
    new_station_map = _station_map(updated)
    added_stations = sorted(set(new_station_map) - set(orig_station_map))
    removed_stations = sorted(set(orig_station_map) - set(new_station_map))
    changed_turn = sorted(
        name
        for name in set(orig_station_map).intersection(new_station_map)
        if bool(orig_station_map[name].get("can_turn")) != bool(new_station_map[name].get("can_turn"))
    )
    if added_stations:
        lines.append(f"Added stations: {', '.join(added_stations)}")
    if removed_stations:
        lines.append(f"Removed stations: {', '.join(removed_stations)}")
    if changed_turn:
        lines.append(f"Updated turning capability: {', '.join(changed_turn)}")

    orig_segment_map = _segment_map(original)
    new_segment_map = _segment_map(updated)
    added_segments = sorted(set(new_segment_map) - set(orig_segment_map))
    removed_segments = sorted(set(orig_segment_map) - set(new_segment_map))
    changed_segments = []
    for name in set(orig_segment_map).intersection(new_segment_map):
        orig = orig_segment_map[name]
        new = new_segment_map[name]
        compare_fields = (
            "start",
            "end",
            "length_km",
            "curve_length_km",
            "tangent_length_km",
            "mtbt_threshold_curva",
            "mtbt_threshold_tangente",
            "move_time_days",
            "maintenance_time_days",
            "move_billed_days",
            "maintenance_billed_days",
            "allowed_movements",
        )
        if any(orig.get(field) != new.get(field) for field in compare_fields):
            changed_segments.append(name)
    if added_segments:
        lines.append(f"Added segments: {', '.join(added_segments)}")
    if removed_segments:
        lines.append(f"Removed segments: {', '.join(removed_segments)}")
    if changed_segments:
        lines.append(f"Modified segments: {', '.join(sorted(changed_segments))}")

    orig_schedule = original.get("mtbt_schedule") or {}
    new_schedule = updated.get("mtbt_schedule") or {}
    if orig_schedule != new_schedule:
        lines.append("Updated MTBT schedule")

    return lines


def collect_network_editor_issues(state: Dict[str, Any]) -> Dict[str, List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    display_name = str(state.get("display_name", "")).strip()
    if not display_name:
        errors.append("Provide a network display name before saving.")
    stations_df = state.get("stations_df")
    if stations_df is None or stations_df.empty:
        warnings.append("Network has no stations. Add stations before running simulations.")
        station_names: List[str] = []
    else:
        station_names = [str(name).strip() for name in stations_df["Name"].astype(str)]
        blank_rows = [idx + 1 for idx, value in enumerate(station_names) if not value]
        if blank_rows:
            errors.append(f"Station name cannot be blank (row(s) {', '.join(map(str, blank_rows))}).")
        dupes = sorted(name for name, count in pd.Series(station_names).value_counts().items() if count > 1 and name)  # type: ignore[type-var]
        if dupes:
            errors.append(f"Duplicate station name(s): {', '.join(dupes)}.")  # type: ignore[arg-type]

    station_set = set(name for name in station_names if name)
    segments_df = state.get("segments_df")
    if segments_df is None or segments_df.empty:
        warnings.append("Network has no segments. Add segments before running simulations.")
    else:
        segment_names = segments_df["Name"].astype(str).str.strip().tolist()
        blank_segments = [idx + 1 for idx, value in enumerate(segment_names) if not value]
        if blank_segments:
            errors.append(f"Segment name cannot be blank (row(s) {', '.join(map(str, blank_segments))}).")
        dup_segments = sorted(
            name for name, count in pd.Series(segment_names).value_counts().items() if count > 1 and name
        )  # type: ignore[type-var]
        if dup_segments:
            errors.append(f"Duplicate segment name(s): {', '.join(dup_segments)}.")  # type: ignore[arg-type]
        for idx, row in segments_df.iterrows():
            row_num = idx + 1
            start = str(row.get("Start", "")).strip()
            end = str(row.get("End", "")).strip()
            if not start or not end:
                errors.append(f"Segment row {row_num} must include both start and end stations.")
            else:
                unknown = [name for name in (start, end) if name not in station_set]
                if unknown:
                    errors.append(
                        f"Segment '{row.get('Name', '').strip() or f'# {row_num}'}' references unknown station(s): {', '.join(unknown)}."
                    )
            try:
                parse_allowed_movements_field(str(row.get("Allowed movements", "")), start, end)
            except ValueError as exc:
                errors.append(f"Segment '{row.get('Name', '').strip() or f'# {row_num}'}': {exc}")

    corridor_lines = [line.strip() for line in state.get("corridor_text", "").splitlines() if line.strip()]
    unknown_corridor = sorted(name for name in corridor_lines if name not in station_set)
    if unknown_corridor:
        warnings.append(f"Corridor order contains unknown station(s): {', '.join(unknown_corridor)}.")

    try:
        spur_carregado_pairs = parse_spur_text(state.get("spur_carregado_text", ""))
    except ValueError as exc:
        errors.append(f"Loaded spur list: {exc}")
    else:
        for idx, (src, dst) in enumerate(spur_carregado_pairs, start=1):
            unknown = [name for name in (src, dst) if name not in station_set]
            if unknown:
                errors.append(
                    f"Loaded spur line {idx} references unknown station(s): {', '.join(unknown)}."
                )

    try:
        spur_vazio_pairs = parse_spur_text(state.get("spur_vazio_text", ""))
    except ValueError as exc:
        errors.append(f"Empty spur list: {exc}")
    else:
        for idx, (src, dst) in enumerate(spur_vazio_pairs, start=1):
            unknown = [name for name in (src, dst) if name not in station_set]
            if unknown:
                errors.append(
                    f"Empty spur line {idx} references unknown station(s): {', '.join(unknown)}."
                )

    return {"errors": errors, "warnings": warnings}


def serialize_network_editor_state(state: Dict[str, Any]) -> Dict[str, Any]:
    payload = copy.deepcopy(state.get("raw_payload", {})) or {}
    display_name = str(state.get("display_name", "")).strip()
    if not display_name:
        raise ValueError("Provide a display name before saving the network.")
    payload["name"] = display_name
    stations_df = state["stations_df"].copy()
    segments_df = state["segments_df"].copy()
    sync_mtbt_dataframe_with_segments(state)
    stations_df["Name"] = stations_df["Name"].astype(str).str.strip()
    station_names: List[str] = []
    serialized_stations = []
    for idx, row in stations_df.iterrows():
        name = row["Name"]
        if not name:
            raise ValueError(f"Station name cannot be blank (row {idx + 1}).")
        if name in station_names:
            raise ValueError(f"Duplicate station name detected: {name}.")
        station_names.append(name)
        serialized_stations.append({
            "name": name,
            "can_turn": bool(row.get("Can turn", False)),
        })
    # Allow saving empty networks for initial setup
    # if not serialized_stations:
    #     raise ValueError("Define at least one station before saving the network.")

    serialized_segments = []
    for idx, row in segments_df.iterrows():
        name = str(row.get("Name", "")).strip()
        start = str(row.get("Start", "")).strip()
        end = str(row.get("End", "")).strip()
        if not name:
            raise ValueError(f"Segment name cannot be blank (row {idx + 1}).")
        if not start or not end:
            raise ValueError(f"Segment '{name}' must include both start and end stations.")
        if start not in station_names or end not in station_names:
            raise ValueError(f"Segment '{name}' references unknown stations ({start} -> {end}).")
        try:
            length = float(row.get("Length (km)", 0.0) or 0.0)
            curve_length = float(row.get("Curve length (km)", 0.0) or 0.0)
            tangent_length = float(row.get("Tangent length (km)", 0.0) or 0.0)
            threshold_curva = float(row.get("MTBT threshold (curva)", 0.0) or 0.0)
            threshold_tangente = float(row.get("MTBT threshold (tangente)", 0.0) or 0.0)
            move_days = int(row.get("Move days", 0) or 0)
            maint_days = int(row.get("Maintenance days", 0) or 0)
            move_billed_days = float(row.get("Move billed days", 0.0) or 0.0)
            maintenance_billed_days = float(row.get("Maintenance billed days", 0.0) or 0.0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Segment '{name}' has invalid numeric values: {exc}") from exc
        allowed = parse_allowed_movements_field(row.get("Allowed movements", ""), start, end)
        serialized_segments.append({
            "name": name,
            "start": start,
            "end": end,
            "length_km": length,
            "curve_length_km": curve_length,
            "tangent_length_km": tangent_length,
            "mtbt_threshold_curva": threshold_curva,
            "mtbt_threshold_tangente": threshold_tangente,
            "move_time_days": move_days,
            "maintenance_time_days": maint_days,
            "move_billed_days": move_billed_days,
            "maintenance_billed_days": maintenance_billed_days,
            "allowed_movements": allowed,
        })
    # Allow saving empty networks for initial setup
    # if not serialized_segments:
    #     raise ValueError("Define at least one segment before saving the network.")

    payload["stations"] = serialized_stations
    payload["segments"] = serialized_segments

    timeline_order = state.get("timeline_order")
    if isinstance(timeline_order, list):
        payload["timeline_order"] = [str(s) for s in timeline_order if s]
    else:
        payload.setdefault("timeline_order", [])

    mtbt_df = state.get("mtbt_df")
    if isinstance(mtbt_df, pd.DataFrame):
        normalized = normalize_mtbt_dataframe(mtbt_df.copy(deep=True))
        # Convert NA values to None for JSON serialization
        cleaned = normalized.replace({pd.NA: None})
        # Convert NaN to None using applymap/map
        cleaned = cleaned.map(lambda x: None if pd.isna(x) else x)  # type: ignore[arg-type,return-value]
        payload["mtbt_schedule"] = {
            "columns": list(cleaned.columns),
            "data": cleaned.values.tolist(),
        }
    return payload


__all__ = [
    "add_month_with_backfill",
    "allowed_movements_text_from_choice",
    "collect_network_editor_issues",
    "dataframe_signature",
    "default_segment_name_sequence",
    "default_start_station_from_config",
    "default_facing_station_from_config",
    "infer_allowed_direction_label",
    "month_label",
    "network_editor_diff_summary",
    "facing_options_from_config",
    "network_file_digest",
    "parse_allowed_movements_field",
    "parse_spur_text",
    "station_choices_from_config",
    "segment_endpoint_status",
    "serialize_network_editor_state",
    "set_state_mtbt_df",
    "spur_rows_from_text",
    "spur_text_from_rows",
    "sync_mtbt_dataframe_with_segments",
    "_ALLOWED_DIRECTION_CHOICES",
]
