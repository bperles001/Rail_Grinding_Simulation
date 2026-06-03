"""Shared helpers for MTBT schedule validation and preprocessing."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from src.utils.mtbt_transform import get_daily_mtbt

MONTH_COLUMN_PATTERN = re.compile(r"^\d{4}-\d{2}$")


def _month_sort_key(label: str) -> tuple[int, int, str]:
    try:
        year_str, month_str = str(label).split("-", 1)
        return (int(year_str), int(month_str), str(label))
    except (ValueError, TypeError):
        return (0, 0, str(label))


def default_mtbt_columns(default_schedule: Optional[Path] = None) -> List[str]:
    """Infer MTBT column order, falling back to sensible defaults."""
    columns: List[str] = []
    if default_schedule and default_schedule.exists():
        try:
            df = pd.read_csv(default_schedule, nrows=0)
            columns = list(df.columns)
        except Exception:
            columns = []
    if "Segment Name" not in columns:
        if not columns:
            columns = ["Segment Name", "Initial Load"]
        else:
            columns = ["Segment Name"] + [col for col in columns if col != "Segment Name"]
    return columns or ["Segment Name", "Initial Load"]


def normalize_mtbt_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure MTBT sheets contain predictable columns and data types."""
    df = df.copy(deep=True)
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated(keep="last")].copy()
    if "Segment Name" not in df.columns:
        df.insert(0, "Segment Name", "")
    df["Segment Name"] = df["Segment Name"].astype(str).str.strip()
    if "Initial Load" not in df.columns:
        df.insert(1, "Initial Load", 0.0)
    df["Initial Load"] = pd.to_numeric(df["Initial Load"], errors="coerce").fillna(0.0)
    month_cols = sorted(
        (col for col in df.columns if MONTH_COLUMN_PATTERN.match(str(col))),
        key=_month_sort_key,
    )
    base_cols = ["Segment Name", "Initial Load"]
    extras = [col for col in df.columns if col not in set(base_cols + month_cols)]
    return df[base_cols + month_cols + extras]


def blank_mtbt_dataframe(
    segment_names: Sequence[str],
    *,
    default_schedule: Optional[Path] = None,
    columns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Create an empty MTBT dataframe scaffold for the provided segments."""
    resolved_columns = list(columns) if columns is not None else default_mtbt_columns(default_schedule)
    rows = []
    for name in segment_names:
        name = str(name).strip()
        if not name:
            continue
        record: Dict[str, Any] = {col: 0.0 for col in resolved_columns if col != "Segment Name"}
        record["Segment Name"] = name
        rows.append(record)
    df = pd.DataFrame(rows, columns=resolved_columns)
    if df.empty:
        df = pd.DataFrame(columns=resolved_columns)
    return normalize_mtbt_dataframe(df)


def mtbt_dataframe_from_payload(
    payload: Dict[str, Any],
    *,
    default_schedule: Optional[Path] = None,
    segments_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Convert a persisted MTBT payload back into a normalized dataframe."""
    schedule = payload.get("mtbt_schedule") or {}
    columns = schedule.get("columns") or []
    data = schedule.get("data") or []
    df: pd.DataFrame
    if columns and isinstance(data, list):
        try:
            df = pd.DataFrame(data, columns=columns)
        except Exception:
            df = pd.DataFrame(columns=columns)
    else:
        segment_names: List[str] = []
        if segments_df is not None and not segments_df.empty:
            segment_names = [str(name).strip() for name in segments_df["Name"].astype(str).tolist() if name]
        df = blank_mtbt_dataframe(segment_names, default_schedule=default_schedule)
    return normalize_mtbt_dataframe(df)


def mtbt_payload_from_df(df: pd.DataFrame) -> Dict[str, Any]:
    """Serialize an MTBT dataframe into the JSON payload structure."""
    normalized = normalize_mtbt_dataframe(df)
    normalized = normalized.replace({pd.NA: None})

    def _python_value(value: Any) -> Any:
        return value if pd.notna(value) else None

    rows = [[_python_value(val) for val in row] for row in normalized.to_numpy(dtype=object)]
    return {
        "columns": list(normalized.columns),
        "data": rows,
    }


def schedule_segment_names(schedule_df: pd.DataFrame) -> List[str]:
    """Return sorted unique segment names from a schedule dataframe."""
    return sorted(schedule_df["Segment Name"].astype(str).str.strip().unique())


def validate_schedule_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure a schedule dataframe has numeric MTBT columns and valid segment names."""
    if "Segment Name" not in df.columns:
        raise ValueError("Schedule must include a 'Segment Name' column.")
    df = df.copy()
    dup_mask = df.columns.duplicated(keep="last")
    if dup_mask.any():
        df = df.loc[:, ~dup_mask].copy()

    def _series_for(column: str) -> pd.Series:
        series = df[column]
        if isinstance(series, pd.DataFrame):
            series = series.iloc[:, -1]
        return series

    segment_series = _series_for("Segment Name").astype(str).str.strip()
    df["Segment Name"] = segment_series
    if segment_series.eq("").any():
        raise ValueError("Schedule contains blank segment names.")

    month_columns = sorted(
        (col for col in df.columns if MONTH_COLUMN_PATTERN.match(str(col))),
        key=_month_sort_key,
    )
    if not month_columns:
        raise ValueError("Schedule must include at least one YYYY-MM column of MTBT values.")

    def _coerce_positive(series: pd.Series, label: str) -> pd.Series:
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.isna().any():
            raise ValueError(f"Column '{label}' must contain only numeric values.")
        if (numeric < 0).any():
            raise ValueError(f"Column '{label}' cannot contain negative values.")
        return numeric

    for col in month_columns:
        df[col] = _coerce_positive(_series_for(col), col)

    if "Initial Load" in df.columns:
        df["Initial Load"] = _coerce_positive(_series_for("Initial Load"), "Initial Load")

    return df


def parse_schedule_bytes(raw_bytes: bytes) -> pd.DataFrame:
    """Load schedule CSV bytes and validate the resulting dataframe."""
    df = pd.read_csv(io.BytesIO(raw_bytes))
    return validate_schedule_dataframe(df)


def summarize_schedule_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Produce a per-segment MTBT total summary from a validated dataframe."""
    month_cols = sorted(
        (col for col in df.columns if MONTH_COLUMN_PATTERN.match(str(col))),
        key=_month_sort_key,
    )
    if not month_cols:
        month_cols = [
            col
            for col in df.columns
            if col not in {"Segment Name", "Initial Load"}
        ]
    summary = df.copy()
    summary["Total MTBT"] = summary[month_cols].sum(axis=1)
    summary = summary[["Segment Name", "Total MTBT", "Initial Load"]].fillna(0)
    return summary.sort_values("Total MTBT", ascending=False)


def build_daily_map(csv_path: Path, start_year: int, end_year: int) -> Dict[str, Dict[str, float]]:
    """Expand a schedule CSV into a date-indexed MTBT lookup per segment."""
    daily_map: Dict[str, Dict[str, float]] = {}
    for year in range(start_year, end_year + 1):
        df_year = get_daily_mtbt(csv_path, year)
        for seg_name, grp in df_year.groupby("Segment Name"):
            seg_map = daily_map.setdefault(str(seg_name), {})
            for date_str, value in zip(grp["Date"].astype(str), grp["MTBT Value"], strict=False):
                seg_map[str(date_str)] = float(value)
    return daily_map
