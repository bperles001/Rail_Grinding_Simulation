"""Tests for the one-off saved_plans.json migration to segment_actions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.migrate_plano_nos_segment_actions import convert_step, migrate


def test_convert_step_move_maintains_all_when_no_maintain_segments():
    step = {"mode": "move", "segments": ["ZTO-ZCZ", "ZTO-ZCZ-LD"], "destination": "ZCZ", "action": "maintain"}
    result = convert_step(step)
    assert result == {
        "mode": "move", "segments": ["ZTO-ZCZ", "ZTO-ZCZ-LD"], "destination": "ZCZ",
        "segment_actions": {"ZTO-ZCZ": "completa", "ZTO-ZCZ-LD": "completa"},
    }


def test_convert_step_move_curves_only():
    step = {"mode": "move", "segments": ["ZRC-ZBL", "ZRC-ZBL-LP", "ZRC-ZBL-LD"], "destination": "ZRC", "action": "maintain_curves"}
    result = convert_step(step)
    assert result["segment_actions"] == {"ZRC-ZBL": "curva", "ZRC-ZBL-LP": "curva", "ZRC-ZBL-LD": "curva"}


def test_convert_step_move_action_none_leaves_all_untouched():
    step = {"mode": "move", "segments": ["ZPT-ZEV-V"], "destination": "ZEV", "action": "move"}
    result = convert_step(step)
    assert result["segment_actions"] == {"ZPT-ZEV-V": "none"}


def test_convert_step_move_respects_maintain_segments_subset():
    step = {
        "mode": "move", "segments": ["TMI-TCS", "TMI-TCS-LD"], "destination": "TCS",
        "action": "maintain", "maintain_segments": ["TMI-TCS-LD"],
    }
    result = convert_step(step)
    assert result["segment_actions"] == {"TMI-TCS": "none", "TMI-TCS-LD": "completa"}
    assert "action" not in result and "maintain_segments" not in result


def test_convert_step_turn_and_wait_pass_through_unchanged():
    assert convert_step({"mode": "turn"}) == {"mode": "turn"}
    assert convert_step({"mode": "wait", "days": 15}) == {"mode": "wait", "days": 15}


def test_migrate_converts_plano_nos_and_drops_incompatible_plans():
    data = {
        "manual": {
            "Original": [{"mode": "move", "segment": "TMI-ZTO", "destination": "TMI", "action": "m"}],
            "2026-Original": [{"mode": "move", "segment": "TMI-ZTO", "destination": "TMI", "action": "m"}],
            "Plano - Nós": [
                {"mode": "move", "segments": ["ZTO-ZCZ", "ZTO-ZCZ-LD"], "destination": "ZCZ", "action": "maintain"},
                {"mode": "turn"},
            ],
        },
        "auto": {"some-run": {"config": {}, "result": {}}},
    }
    result = migrate(data)
    assert set(result["manual"].keys()) == {"Plano - Nós"}
    assert result["manual"]["Plano - Nós"][0]["segment_actions"] == {"ZTO-ZCZ": "completa", "ZTO-ZCZ-LD": "completa"}
    assert result["manual"]["Plano - Nós"][1] == {"mode": "turn"}
    assert result["auto"] == data["auto"]  # secao auto intocada
