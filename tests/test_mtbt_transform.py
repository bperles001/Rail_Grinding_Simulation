from pathlib import Path

import pytest

from src.utils.mtbt_transform import get_daily_mtbt, get_initial_loads


def _write_csv(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_get_daily_mtbt_expands_months_into_days(tmp_path):
    csv_path = tmp_path / "schedule.csv"
    _write_csv(csv_path, "Segment Name,2025-01,2026-02\nSEG-1,31,56\n")
    df = get_daily_mtbt(csv_path, 2024)
    assert len(df) == 31 + 28  # 31 days in Jan 2025, 28 days in Feb 2026
    assert set(df["Segment Name"]) == {"SEG-1"}
    jan_values = df[df["Date"].str.startswith("2025-01")]
    feb_values = df[df["Date"].str.startswith("2026-02")]
    assert jan_values.iloc[0]["MTBT Value"] == pytest.approx(1.0)
    assert feb_values.iloc[0]["MTBT Value"] == pytest.approx(2.0)


def test_get_initial_loads_handles_missing_and_present_columns(tmp_path):
    csv_with_loads = tmp_path / "with_loads.csv"
    _write_csv(csv_with_loads, "Segment Name,Initial Load\nSEG-1,5.5\n")
    loads = get_initial_loads(str(csv_with_loads))
    assert loads == {"SEG-1": 5.5}

    csv_without_loads = tmp_path / "without_loads.csv"
    _write_csv(csv_without_loads, "Segment Name,2025-01\nSEG-1,10\n")
    loads_missing = get_initial_loads(str(csv_without_loads))
    assert loads_missing == {}
