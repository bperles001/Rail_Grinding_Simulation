from calendar import monthrange
from pathlib import Path
import re as _re
from typing import Any, Dict, List, Union, cast

import pandas as pd

# Cache keyed by (path, mtime_ns, size, year): the expansion is pure on the
# file content, and dashboards call it on every rerun.
_DAILY_MTBT_CACHE: Dict[Any, pd.DataFrame] = {}
_DAILY_MTBT_CACHE_MAX = 32


def _daily_cache_key(csv_path: Union[str, Path], year: int) -> Any:
    try:
        stat = Path(csv_path).stat()
    except OSError:
        return None
    return (str(csv_path), stat.st_mtime_ns, stat.st_size, int(year))


def get_daily_mtbt(csv_path: Union[str, Path], year: int) -> pd.DataFrame:
    """Expand monthly MTBT values into per-day entries.

    If the CSV columns encode a year (YYYY-MM), that takes precedence over the
    ``year`` argument; otherwise ``year`` is used as a fallback so legacy files
    without year markers still expand correctly.

    Args:
        csv_path: Path to MTBT schedule CSV file.
        year: Default year for legacy month columns without year prefix.

    Returns:
        DataFrame with columns: Segment Name, Date, MTBT Value.
    """

    cache_key = _daily_cache_key(csv_path, year)
    if cache_key is not None and cache_key in _DAILY_MTBT_CACHE:
        return _DAILY_MTBT_CACHE[cache_key].copy()

    df = pd.read_csv(csv_path)
    segments = df["Segment Name"]
    month_cols = [
        col
        for col in df.columns
        if col not in {"Segment Name", "Initial Load"} and _re.match(r"^\d{4}-\d{2}$", str(col))
    ]
    rows: List[Dict[str, Any]] = []
    for idx, segment in enumerate(segments):
        for label in month_cols:
            mtbt_month = float(cast(Any, df.at[idx, label]))
            match = _re.match(r"^(\d{4})-(\d{2})$", str(label))
            if match:
                year_val = int(match.group(1))
                month_num = int(match.group(2))
            else:
                year_val = year
                month_num = int(str(label)[-2:])
            days_in_month = monthrange(year_val, month_num)[1]
            daily_value = mtbt_month / days_in_month if days_in_month else 0.0
            for day in range(1, days_in_month + 1):
                date = f"{year_val}-{month_num:02d}-{day:02d}"
                rows.append({"Segment Name": segment, "Date": date, "MTBT Value": daily_value})
    result = pd.DataFrame(rows)
    if cache_key is not None:
        while len(_DAILY_MTBT_CACHE) >= _DAILY_MTBT_CACHE_MAX:
            _DAILY_MTBT_CACHE.pop(next(iter(_DAILY_MTBT_CACHE)))
        _DAILY_MTBT_CACHE[cache_key] = result.copy()
    return result

def get_initial_loads(csv_path: str) -> Dict[str, float]:
    """Read 'Initial Load' values from the MTBT schedule CSV if present."""

    df = pd.read_csv(csv_path)
    if "Initial Load" not in df.columns:
        return {}
    loads: Dict[str, float] = {}
    for _, row in df.iterrows():
        try:
            loads[str(row["Segment Name"])] = float(row["Initial Load"])
        except Exception:
            # If parsing fails, skip or treat as zero
            try:
                loads[str(row["Segment Name"])] = float(str(row["Initial Load"]).replace(",", "."))
            except Exception:
                loads[str(row["Segment Name"])] = 0.0
    return loads
