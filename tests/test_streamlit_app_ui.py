"""UI-level regression tests driven through streamlit.testing.v1.AppTest.

These exercise the real Streamlit script end-to-end (widget state, reruns,
session_state) rather than the pure backend helpers, since some bugs only
exist in how the script wires widgets together.
"""
from __future__ import annotations

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_network(path: Path) -> None:
    payload = {
        "name": "UI Test Network",
        "stations": [
            {"name": "A", "can_turn": True},
            {"name": "B", "can_turn": False},
            {"name": "C", "can_turn": False},
        ],
        "segments": [
            {
                "name": "A-B",
                "start": "A",
                "end": "B",
                "length_km": 1.0,
                "mtbt_threshold": 5.0,
                "move_time_days": 1,
                "maintenance_time_days": 1,
            },
            {
                "name": "B-C",
                "start": "B",
                "end": "C",
                "length_km": 1.0,
                "mtbt_threshold": 5.0,
                "move_time_days": 1,
                "maintenance_time_days": 1,
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _open_network_editor(tmp_path: Path) -> AppTest:
    network_path = tmp_path / "network.json"
    _write_network(network_path)

    at = AppTest.from_file(str(REPO_ROOT / "streamlit_app.py"), default_timeout=60)
    at.run()
    at.session_state["active_network_path"] = str(network_path)
    at.session_state["navigation_page"] = "Network Editor"
    at.run()
    assert not at.exception
    return at


def test_layout_table_accumulates_two_edits_before_submit(tmp_path: Path) -> None:
    """Regression test: editing a second cell used to wipe out the first
    (and the second) because the data_editor was fed a `data=` argument
    rebuilt from state the widget itself had just written to, on every
    keystroke rerun. Wrapping it in a form (matching the Stations/Segments
    editors elsewhere in this file) fixes it - edits must not be lost or
    silently dropped while the user is still editing, before Apply is
    clicked."""
    at = _open_network_editor(tmp_path)

    # First cell edit.
    at.session_state["network_layout_editor"] = {
        "edited_rows": {0: {"X": 99.0}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception

    # Second cell edit; the browser's data_editor buffer accumulates both
    # edits locally (nothing is sent to the backend yet - it's inside a form).
    at.session_state["network_layout_editor"] = {
        "edited_rows": {0: {"X": 99.0}, 1: {"Y": 77.0}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception

    widget_state = at.session_state["network_layout_editor"]
    assert widget_state["edited_rows"] == {0: {"X": 99.0}, 1: {"Y": 77.0}}, (
        "Both pending edits must still be present before Apply is clicked"
    )
    # Nothing should be committed to the network's table_overrides yet - only
    # Apply commits (unrelated: `dirty` can already be true on a fresh load
    # for other reasons, so it isn't asserted here).
    state = at.session_state["network_editor_state"]
    assert state["layout_settings"]["table_overrides"] == {}


def test_layout_table_apply_commits_all_pending_edits(tmp_path: Path) -> None:
    at = _open_network_editor(tmp_path)

    # Real form semantics: the browser sends the full accumulated grid edits
    # together with the submit click in a single round trip.
    at.session_state["network_layout_editor"] = {
        "edited_rows": {0: {"X": 99.0}, 1: {"Y": 77.0}},
        "added_rows": [],
        "deleted_rows": [],
    }
    submit_buttons = [b for b in at.button if b.label == "Apply layout changes"]
    assert len(submit_buttons) == 1
    submit_buttons[0].click().run()
    assert not at.exception

    state = at.session_state["network_editor_state"]
    overrides = state["layout_settings"]["table_overrides"]
    assert overrides["A"]["x"] == 99.0
    assert overrides["B"]["y"] == 77.0
    assert state["dirty"] is True


def test_gps_import_computes_schematic_positions_and_leaves_other_stations_untouched(
    tmp_path: Path,
) -> None:
    at = _open_network_editor(tmp_path)

    # C already has a manual override before the import - it must survive
    # untouched, since the pasted list below only covers A and B.
    state = at.session_state["network_editor_state"]
    state["layout_settings"]["table_overrides"]["C"] = {"x": 42.0, "y": 42.0}

    at.session_state["network_layout_gps_text"] = (
        "A, 0.0, 0.0\n"
        "B, 0.0, 1.0\n"  # B due east of A (longitude increases east)
    )
    import_buttons = [b for b in at.button if b.label == "Aplicar e normalizar posições"]
    assert len(import_buttons) == 1
    import_buttons[0].click().run()
    assert not at.exception

    state = at.session_state["network_editor_state"]
    overrides = state["layout_settings"]["table_overrides"]
    assert set(overrides) == {"A", "B", "C"}
    assert state["dirty"] is True

    ax, ay = overrides["A"]["x"], overrides["A"]["y"]
    bx, by = overrides["B"]["x"], overrides["B"]["y"]
    assert bx > ax  # B stays east of A
    assert overrides["C"] == {"x": 42.0, "y": 42.0}  # untouched - not in the pasted text


def test_gps_import_reports_unknown_station(tmp_path: Path) -> None:
    at = _open_network_editor(tmp_path)

    at.session_state["network_layout_gps_text"] = "NOPE, 0.0, 0.0"
    import_buttons = [b for b in at.button if b.label == "Aplicar e normalizar posições"]
    import_buttons[0].click().run()
    assert not at.exception

    warnings = [w.value for w in at.warning]
    assert any("NOPE" in w for w in warnings)
    state = at.session_state["network_editor_state"]
    assert state["layout_settings"]["table_overrides"] == {}
