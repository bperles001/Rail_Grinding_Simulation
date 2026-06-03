import pandas as pd
import pytest

from railroad_backend.domain.schedule import (
    blank_mtbt_dataframe,
    mtbt_dataframe_from_payload,
    mtbt_payload_from_df,
    normalize_mtbt_dataframe,
    parse_schedule_bytes,
    summarize_schedule_dataframe,
    validate_schedule_dataframe,
)


def test_parse_schedule_bytes_validates_and_returns_dataframe():
    csv_data = "Segment Name,Initial Load,2025-01\nSEG-A,5,12\n"
    df = parse_schedule_bytes(csv_data.encode("utf-8"))
    assert list(df["Segment Name"]) == ["SEG-A"]
    assert df.loc[0, "2025-01"] == 12


def test_parse_schedule_bytes_rejects_negative_values():
    csv_data = "Segment Name,2025-01\nSEG-A,-3\n"
    with pytest.raises(ValueError):
        parse_schedule_bytes(csv_data.encode("utf-8"))


def test_blank_mtbt_dataframe_populates_segments_and_columns():
    df = blank_mtbt_dataframe(["AAA", "BBB"], columns=["Segment Name", "Initial Load", "2025-01"])
    assert df["Segment Name"].tolist() == ["AAA", "BBB"]
    assert "Initial Load" in df.columns
    assert "2025-01" in df.columns


def test_mtbt_payload_round_trip_preserves_values():
    df = blank_mtbt_dataframe(["AAA"], columns=["Segment Name", "Initial Load", "2025-01"])
    df.loc[0, "Initial Load"] = 3.5
    df.loc[0, "2025-01"] = 7.25
    payload = mtbt_payload_from_df(df)
    restored = mtbt_dataframe_from_payload({"mtbt_schedule": payload})
    pd.testing.assert_frame_equal(restored, df)


def test_validate_schedule_dataframe_enforces_structure_and_values():
    df = pd.DataFrame(
        {
            "Segment Name": ["SEG-1", " seg-2 "],
            "Initial Load": [1, 2],
            "2025-01": [10, 5],
            "2025-02": [3, 7],
        }
    )
    validated = validate_schedule_dataframe(df)
    assert validated["Segment Name"].tolist() == ["SEG-1", "seg-2"]
    assert validated["2025-02"].tolist() == [3, 7]


def test_validate_schedule_dataframe_rejects_missing_columns():
    df = pd.DataFrame({"Initial Load": [1]})
    with pytest.raises(ValueError):
        validate_schedule_dataframe(df)


def test_normalize_mtbt_dataframe_handles_duplicates_and_missing_columns():
    df = pd.DataFrame(
        [["SEG", "SEG", 1.0, 5.0, "x"]],
        columns=["Segment Name", "Segment Name", "Initial Load", "2025-01", "Other"],
    )
    normalized = normalize_mtbt_dataframe(df)
    assert list(normalized.columns[:3]) == ["Segment Name", "Initial Load", "2025-01"]
    assert "Other" in normalized.columns


def test_normalize_mtbt_dataframe_orders_months_chronologically():
    df = pd.DataFrame(
        {
            "Segment Name": ["S"],
            "Initial Load": [0.0],
            "2026-02": [1],
            "2025-12": [2],
        }
    )
    normalized = normalize_mtbt_dataframe(df)
    assert normalized.columns.tolist()[2:4] == ["2025-12", "2026-02"]


def test_summarize_schedule_dataframe_orders_by_total():
    df = pd.DataFrame(
        {
            "Segment Name": ["B", "A"],
            "Initial Load": [0, 0],
            "2025-01": [1, 3],
            "2025-02": [2, 4],
        }
    )
    summary = summarize_schedule_dataframe(df)
    assert summary.iloc[0]["Segment Name"] == "A"
    assert summary.iloc[0]["Total MTBT"] == 7
