"""Tests for the one-off saved_plans.json migration that adds config."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.migrate_saved_plans_add_config import DEFAULT_CONFIG, migrate


def test_migrate_wraps_raw_list_entries_with_default_config():
    data = {
        "manual": {
            "Plano - Nós": [{"mode": "turn"}],
            "Plano - Nós (v2 segment_actions)": [{"mode": "wait", "days": 3}],
        },
        "auto": {"some-run": {"config": {}, "result": {}}},
    }
    result = migrate(data)
    assert result["manual"]["Plano - Nós"] == {"config": DEFAULT_CONFIG, "steps": [{"mode": "turn"}]}
    assert result["manual"]["Plano - Nós (v2 segment_actions)"] == {
        "config": DEFAULT_CONFIG, "steps": [{"mode": "wait", "days": 3}],
    }
    assert result["auto"] == data["auto"]


def test_migrate_leaves_already_migrated_entries_untouched():
    entry = {"config": {"start_station": "X"}, "steps": [{"mode": "turn"}]}
    data = {"manual": {"Plano - Nós": entry}, "auto": {}}
    result = migrate(data)
    assert result["manual"]["Plano - Nós"] == entry


def test_migrate_default_config_matches_current_session():
    assert DEFAULT_CONFIG == {
        "start_station": "ZTO", "facing_station": "ZCZ",
        "start_year": 2026, "end_year": 2027, "second_kld": True,
    }
