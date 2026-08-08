"""Tests for manual/auto plan persistence helpers."""
from railroad_backend.persistence.plan_storage import (
    import_manual_plan_payload,
    load_manual_plan,
    plan_storage_snapshot,
    save_manual_plan,
)

_CONFIG = {
    "start_station": "ZTO", "facing_station": "ZCZ",
    "start_year": 2026, "end_year": 2027, "second_kld": True,
}
_STEPS = [{"mode": "turn"}, {"mode": "wait", "days": 3}]


def test_save_manual_plan_stores_config_and_steps():
    saved = save_manual_plan({}, "Meu Plano", _STEPS, _CONFIG)
    assert saved == {"Meu Plano": {"config": _CONFIG, "steps": _STEPS}}


def test_save_manual_plan_preserves_other_entries():
    existing = {"Outro": {"config": {"start_station": "X"}, "steps": [{"mode": "turn"}]}}
    saved = save_manual_plan(existing, "Meu Plano", _STEPS, _CONFIG)
    assert set(saved.keys()) == {"Outro", "Meu Plano"}
    assert saved["Outro"] == existing["Outro"]


def test_load_manual_plan_returns_config_and_steps_tuple():
    saved = save_manual_plan({}, "Meu Plano", _STEPS, _CONFIG)
    config, steps = load_manual_plan(saved, "Meu Plano")
    assert config == _CONFIG
    assert steps == _STEPS


def test_load_manual_plan_missing_name_returns_empty():
    config, steps = load_manual_plan({}, "Nao Existe")
    assert config == {}
    assert steps == []


def test_plan_storage_snapshot_normalizes_manual_entries():
    manual_saved = {"Meu Plano": {"config": _CONFIG, "steps": _STEPS}}
    snapshot = plan_storage_snapshot(manual_saved=manual_saved)
    assert snapshot["manual"] == {"Meu Plano": {"config": _CONFIG, "steps": _STEPS}}


def test_plan_storage_snapshot_skips_non_dict_manual_entries():
    manual_saved = {"Valido": {"config": _CONFIG, "steps": _STEPS}, "Invalido": "nao e dict"}
    snapshot = plan_storage_snapshot(manual_saved=manual_saved)
    assert set(snapshot["manual"].keys()) == {"Valido"}


def test_import_manual_plan_payload_accepts_new_format():
    payload = {"manual": {"Importado": {"config": _CONFIG, "steps": _STEPS}}}
    saved, imported = import_manual_plan_payload({}, payload)
    assert imported == 1
    assert saved["Importado"] == {"config": _CONFIG, "steps": _STEPS}


def test_import_manual_plan_payload_skips_entry_without_steps_list():
    payload = {"manual": {"SemSteps": {"config": _CONFIG}}}
    saved, imported = import_manual_plan_payload({}, payload)
    assert imported == 0
    assert saved == {}
