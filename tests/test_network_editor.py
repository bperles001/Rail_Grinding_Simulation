from pathlib import Path

import pandas as pd
import pytest

from railroad_backend.domain import network_editor
from streamlit_app import _serialize_network_editor_state


def _base_payload():
    return {
        "name": "Sample",
        "stations": [
            {"name": "A", "can_turn": True},
            {"name": "B", "can_turn": False},
        ],
        "segments": [
            {
                "name": "A-B",
                "start": "A",
                "end": "B",
                "length_km": 1.0,
                "mtbt_threshold": 5.0,
                "move_time_days": 2,
                "maintenance_time_days": 3,
                "allowed_movements": [["A", "B"], ["B", "A"]],
            }
        ],
        "layout": {
            "mode": "table",
            "table_overrides": {"A": {"x": 1, "y": 2}},
            "scale": 2.0,
        },
    }


def test_slugify_filename_removes_invalid_chars():
    assert network_editor.slugify_filename("Some File @#") == "some_file"
    assert network_editor.slugify_filename("") == "network"


def test_unique_network_path_increments(tmp_path: Path):
    tmp_path.joinpath("network.json").write_text("{}")
    tmp_path.joinpath("network_1.json").write_text("{}")
    candidate = network_editor.unique_network_path(tmp_path, "Network")
    assert candidate.name == "network_2.json"


def test_station_dataframe_from_payload():
    df = network_editor.network_editor_station_df(_base_payload())
    assert df.columns.tolist() == ["Name", "Can turn"]
    assert df.loc[0, "Name"] == "A"
    assert bool(df.loc[0, "Can turn"]) is True


def test_segment_dataframe_from_payload():
    df = network_editor.network_editor_segment_df(_base_payload())
    assert "Allowed movements" in df.columns
    assert df.loc[0, "Move days"] == 2
    assert df.loc[0, "Curve length (km)"] == 0.0
    assert df.loc[0, "Tangent length (km)"] == 0.0
    assert df.loc[0, "Move billed days"] == 0.0
    assert df.loc[0, "Maintenance billed days"] == 0.0


def test_segment_dataframe_from_payload_with_curve_tangent_and_billed_days():
    payload = _base_payload()
    payload["segments"][0].update(
        {
            "curve_length_km": 0.6,
            "tangent_length_km": 0.4,
            "move_billed_days": 0.5,
            "maintenance_billed_days": 1.5,
        }
    )
    df = network_editor.network_editor_segment_df(payload)
    assert df.loc[0, "Curve length (km)"] == 0.6
    assert df.loc[0, "Tangent length (km)"] == 0.4
    assert df.loc[0, "Move billed days"] == 0.5
    assert df.loc[0, "Maintenance billed days"] == 1.5


def test_parse_allowed_movements_validates_format():
    with pytest.raises(ValueError):
        network_editor.parse_allowed_movements_field("bad", "A", "B")
    pairs = network_editor.parse_allowed_movements_field("A->B\nB->A", "A", "B")
    assert pairs == [["A", "B"], ["B", "A"]]


def test_parse_station_coordinates_comma_separated():
    text = "RDA, -15.55, -54.56\nTRO, -16.70, -54.67"
    parsed, messages = network_editor.parse_station_coordinates(text)
    assert parsed == {"RDA": (-15.55, -54.56), "TRO": (-16.70, -54.67)}
    assert messages == []


def test_parse_station_coordinates_tab_separated():
    text = "RDA\t-15.55\t-54.56"
    parsed, messages = network_editor.parse_station_coordinates(text)
    assert parsed == {"RDA": (-15.55, -54.56)}
    assert messages == []


def test_parse_station_coordinates_skips_blank_lines():
    text = "RDA, -15.55, -54.56\n\n   \nTRO, -16.70, -54.67"
    parsed, messages = network_editor.parse_station_coordinates(text)
    assert set(parsed) == {"RDA", "TRO"}
    assert messages == []


def test_parse_station_coordinates_reports_malformed_line():
    text = "RDA, -15.55, -54.56\nBADLINE\nTRO, -16.70, -54.67"
    parsed, messages = network_editor.parse_station_coordinates(text)
    assert set(parsed) == {"RDA", "TRO"}
    assert len(messages) == 1
    assert "Line 2" in messages[0]


def test_parse_station_coordinates_reports_non_numeric():
    text = "RDA, abc, -54.56"
    parsed, messages = network_editor.parse_station_coordinates(text)
    assert parsed == {}
    assert len(messages) == 1
    assert "Line 1" in messages[0]


def test_parse_station_coordinates_reports_duplicate_and_keeps_last():
    text = "RDA, -15.55, -54.56\nRDA, -15.99, -54.99"
    parsed, messages = network_editor.parse_station_coordinates(text)
    assert parsed == {"RDA": (-15.99, -54.99)}
    assert len(messages) == 1
    assert "duplicate" in messages[0].lower()


def test_parse_spur_text_round_trip():
    text = "A->B\nB->C"
    rows = network_editor.spur_rows_from_text(text)
    assert rows == [{"Source": "A", "Destination": "B"}, {"Source": "B", "Destination": "C"}]
    assert network_editor.spur_text_from_rows(rows) == text


def _sample_state():
    return {
        "raw_payload": {},
        "display_name": "Sample",
        "stations_df": pd.DataFrame({"Name": ["A", "B"], "Can turn": [True, False]}),
        "segments_df": pd.DataFrame(
            {
                "Name": ["A-B"],
                "Start": ["A"],
                "End": ["B"],
                "Length (km)": [1.5],
                "MTBT threshold": [5.0],
                "Move days": [2],
                "Maintenance days": [3],
                "Allowed movements": ["A->B\nB->A"],
            }
        ),
        "mtbt_df": pd.DataFrame(
            {
                "Segment Name": ["A-B"],
                "Initial Load": [5],
                "2025-01": [10],
            }
        ),
    }


def test_serialize_network_editor_state(monkeypatch):
    state = _sample_state()

    monkeypatch.setattr(
        "streamlit_app._layout_payload_for_state",
        lambda _state: {"mode": "table", "table_overrides": {}, "scale": 1.0},
    )

    payload = _serialize_network_editor_state(state)
    assert payload["name"] == "Sample"
    assert payload["stations"][0] == {"name": "A", "can_turn": True}
    assert payload["segments"][0]["allowed_movements"] == [["A", "B"], ["B", "A"]]
    # segments_df in this fixture predates the curve/tangent/billed-days columns; must default cleanly.
    assert payload["segments"][0]["curve_length_km"] == 0.0
    assert payload["segments"][0]["tangent_length_km"] == 0.0
    assert payload["segments"][0]["move_billed_days"] == 0.0
    assert payload["segments"][0]["maintenance_billed_days"] == 0.0
    # direction_model no longer exists
    assert "direction_model" not in payload
    assert payload["layout"]["mode"] == "table"
    columns = payload["mtbt_schedule"]["columns"]
    assert columns[:3] == ["Segment Name", "Initial Load", "2025-01"]


def test_serialize_network_editor_state_includes_curve_tangent_and_billed_days(monkeypatch):
    state = _sample_state()
    state["segments_df"]["Curve length (km)"] = [0.9]
    state["segments_df"]["Tangent length (km)"] = [0.6]
    state["segments_df"]["Move billed days"] = [1.5]
    state["segments_df"]["Maintenance billed days"] = [2.5]

    monkeypatch.setattr(
        "streamlit_app._layout_payload_for_state",
        lambda _state: {"mode": "table", "table_overrides": {}, "scale": 1.0},
    )

    payload = _serialize_network_editor_state(state)
    segment = payload["segments"][0]
    assert segment["curve_length_km"] == 0.9
    assert segment["tangent_length_km"] == 0.6
    assert segment["move_billed_days"] == 1.5
    assert segment["maintenance_billed_days"] == 2.5


def test_serialize_network_editor_state_requires_display_name(monkeypatch):
    state = _sample_state()
    state["display_name"] = ""
    monkeypatch.setattr("streamlit_app._layout_payload_for_state", lambda _state: {})
    with pytest.raises(ValueError):
        _serialize_network_editor_state(state)
