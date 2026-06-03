"""Typed facade for schedule utilities."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from src.railroad_backend.domain.schedule import (
    MONTH_COLUMN_PATTERN,
    blank_mtbt_dataframe,
    build_daily_map,
    mtbt_dataframe_from_payload,
    mtbt_payload_from_df,
    normalize_mtbt_dataframe,
    parse_schedule_bytes,
    schedule_segment_names,
    summarize_schedule_dataframe,
    validate_schedule_dataframe,
)
from railroad_backend.services.network_editor import (
    default_segment_name_sequence,
    set_state_mtbt_df,
)

__all__ = [
    "MONTH_COLUMN_PATTERN",
    "blank_mtbt_dataframe",
    "build_daily_map",
    "mtbt_dataframe_from_payload",
    "mtbt_payload_from_df",
    "normalize_mtbt_dataframe",
    "parse_schedule_bytes",
    "schedule_segment_names",
    "summarize_schedule_dataframe",
    "validate_schedule_dataframe",
    "ensure_schedule_has_month",
    "current_schedule_dataframe",
    "schedule_missing_segments",
]


def ensure_schedule_has_month(df: pd.DataFrame) -> pd.DataFrame:
    normalized = normalize_mtbt_dataframe(df.copy(deep=True))
    month_cols = [col for col in normalized.columns if MONTH_COLUMN_PATTERN.match(str(col))]
    if month_cols:
        return normalized
    seed_year = datetime.utcnow().year
    seed_month = datetime.utcnow().month or 1
    label = f"{seed_year:04d}-{seed_month:02d}"
    normalized[label] = 0.0
    return normalize_mtbt_dataframe(normalized)


def current_schedule_dataframe(state: Dict[str, Any], default_schedule: Path) -> pd.DataFrame:
    df = state.get("mtbt_df")
    if not isinstance(df, pd.DataFrame) or df.empty:
        df = blank_mtbt_dataframe(
            default_segment_name_sequence(state),
            default_schedule=default_schedule if default_schedule.exists() else None,
        )
    normalized = ensure_schedule_has_month(df)
    set_state_mtbt_df(state, normalized)
    return normalized


def schedule_missing_segments(schedule_df: pd.DataFrame, segments: Iterable[str]) -> List[str]:
    active_segments = {str(name).strip() for name in segments if str(name).strip()}
    schedule_segments = [str(name).strip() for name in schedule_df.get("Segment Name", [])]
    missing = sorted({name for name in schedule_segments if name and name not in active_segments})
    return missing
