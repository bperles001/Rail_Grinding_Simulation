"""Utilities for Network Editor payload validation and serialization."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

_FILENAME_SANITIZER = re.compile(r"[^0-9A-Za-z_-]+")


def slugify_filename(value: str) -> str:
    slug = _FILENAME_SANITIZER.sub("_", value or "").strip("_")
    return slug.lower() or "network"


def unique_network_path(base_dir: Path, base_label: str) -> Path:
    slug = slugify_filename(base_label)
    candidate = base_dir / f"{slug}.json"
    counter = 1
    while candidate.exists():
        candidate = base_dir / f"{slug}_{counter}.json"
        counter += 1
    return candidate


def network_editor_station_df(payload: Dict[str, Any]) -> pd.DataFrame:
    stations = payload.get("stations", []) or []
    df = pd.DataFrame(stations)
    if df.empty:
        df = pd.DataFrame(columns=["Name", "Can turn"])
    else:
        df = df.rename(columns={"name": "Name", "can_turn": "Can turn"})
        if "Name" not in df.columns:
            df["Name"] = ""
        if "Can turn" not in df.columns:
            df["Can turn"] = False
    df["Name"] = df["Name"].astype(str)
    df["Can turn"] = df["Can turn"].fillna(False).astype(bool)
    return df[["Name", "Can turn"]]


def network_editor_segment_df(payload: Dict[str, Any]) -> pd.DataFrame:
    segments = payload.get("segments", []) or []
    rows = []
    for entry in segments:
        allowed = entry.get("allowed_movements") or []
        allowed_text = "\n".join(f"{src}->{dst}" for src, dst in allowed) if allowed else ""
        rows.append(
            {
                "Name": entry.get("name", ""),
                "Start": entry.get("start", ""),
                "End": entry.get("end", ""),
                "Length (km)": entry.get("length_km", 0.0),
                "Curve length (km)": entry.get("curve_length_km", 0.0),
                "Tangent length (km)": entry.get("tangent_length_km", 0.0),
                "MTBT threshold": entry.get("mtbt_threshold", 0.0),
                "Move days": entry.get("move_time_days", 0),
                "Maintenance days": entry.get("maintenance_time_days", 0),
                "Move billed days": entry.get("move_billed_days", 0.0),
                "Maintenance billed days": entry.get("maintenance_billed_days", 0.0),
                "Allowed movements": allowed_text,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "Name",
                "Start",
                "End",
                "Length (km)",
                "Curve length (km)",
                "Tangent length (km)",
                "MTBT threshold",
                "Move days",
                "Maintenance days",
                "Move billed days",
                "Maintenance billed days",
                "Allowed movements",
            ]
        )
    for col in ("Name", "Start", "End", "Allowed movements"):
        df[col] = df[col].astype(str)
    for col in ("Length (km)", "Curve length (km)", "Tangent length (km)", "MTBT threshold", "Move billed days", "Maintenance billed days"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    for col in ("Move days", "Maintenance days"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    return df[
        [
            "Name",
            "Start",
            "End",
            "Length (km)",
            "Curve length (km)",
            "Tangent length (km)",
            "MTBT threshold",
            "Move days",
            "Maintenance days",
            "Move billed days",
            "Maintenance billed days",
            "Allowed movements",
        ]
    ]


def parse_allowed_movements_field(value: str, start: str, end: str) -> List[List[str]]:
    text = (value or "").strip()
    if not text:
        return [[start, end], [end, start]] if start and end else []
    tokens = re.split(r"[;,\n]+", text)
    movements: List[List[str]] = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        token = token.replace("→", "->")
        if "->" not in token:
            raise ValueError(f"Invalid allowed movement entry '{token}'. Use 'SRC->DST' format.")
        src, dst = [part.strip() for part in token.split("->", 1)]
        if not src or not dst:
            raise ValueError(f"Invalid allowed movement entry '{token}'.")
        movements.append([src, dst])
    if not movements and start and end:
        movements = [[start, end], [end, start]]
    return movements


def parse_spur_text(value: str) -> List[List[str]]:
    text = (value or "").strip()
    if not text:
        return []
    movements: List[List[str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = line.replace("→", "->")
        if "->" not in line:
            raise ValueError(f"Invalid spur entry '{line}'. Use 'SRC->DST' format per line.")
        src, dst = [part.strip() for part in line.split("->", 1)]
        if not src or not dst:
            raise ValueError(f"Invalid spur entry '{line}'.")
        movements.append([src, dst])
    return movements


def parse_station_coordinates(text: str) -> Tuple[Dict[str, Tuple[float, float]], List[str]]:
    """Parse pasted 'NAME, LAT, LONG' (comma- or tab-separated) lines.

    Returns (parsed, messages): parsed maps station name -> (lat, long);
    messages lists one human-readable warning per skipped/invalid line.
    Never raises - bad input becomes a message, not an exception. Duplicate
    station names: the later line wins, with a warning.
    """
    parsed: Dict[str, Tuple[float, float]] = {}
    messages: List[str] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"[,\t]+", line) if p.strip()]
        if len(parts) != 3:
            messages.append(
                f"Line {line_no}: expected 'NAME, LAT, LONG', got {len(parts)} field(s) - skipped."
            )
            continue
        name, lat_raw, lon_raw = parts
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except ValueError:
            messages.append(
                f"Line {line_no}: '{lat_raw}' / '{lon_raw}' is not numeric - skipped."
            )
            continue
        if name in parsed:
            messages.append(f"Line {line_no}: duplicate station '{name}' - using the later value.")
        parsed[name] = (lat, lon)
    return parsed, messages


def spur_rows_from_text(value: str) -> List[Dict[str, str]]:
    try:
        pairs = parse_spur_text(value)
    except ValueError:
        pairs = []
    rows = [{"Source": src, "Destination": dst} for src, dst in pairs]
    return rows or [{"Source": "", "Destination": ""}]


def spur_text_from_rows(rows: List[Dict[str, str]]) -> str:
    entries = []
    for row in rows:
        src = (row.get("Source") or "").strip()
        dst = (row.get("Destination") or "").strip()
        if src and dst:
            entries.append(f"{src}->{dst}")
    return "\n".join(entries)
