"""Tests for manual/auto plan persistence helpers."""
import json

import pytest

from railroad_backend.persistence.plan_storage import (
    import_auto_run_payload,
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


# --- Limitacao de escopo fechada apos a campanha de fuzz de 2026-08-11:
# persistencia/import de planos nao tinha sido fuzzada com payloads
# malformados (arquivo de upload do usuario). Nenhum bug encontrado --
# as checagens isinstance() ja existentes se mostraram robustas -- mas
# fica registrado como regressao pra nao perder essa garantia depois.

@pytest.mark.parametrize("bad_payload", [None, [], "nao e objeto", 42, True])
def test_import_manual_plan_payload_rejects_non_dict_payload(bad_payload):
    with pytest.raises(ValueError, match="must contain a JSON object"):
        import_manual_plan_payload({}, bad_payload)


@pytest.mark.parametrize("bad_manual_section", [None, [], "x", 42])
def test_import_manual_plan_payload_rejects_non_dict_manual_section(bad_manual_section):
    with pytest.raises(ValueError, match="must include a 'manual' object"):
        import_manual_plan_payload({}, {"manual": bad_manual_section})


def test_import_manual_plan_payload_skips_malformed_entries_keeps_valid_ones():
    payload = {
        "manual": {
            "Valido": {"config": _CONFIG, "steps": _STEPS},
            "EntradaNaoDict": "nao e dict",
            "StepsNaoLista": {"config": _CONFIG, "steps": "nao e lista"},
            "StepsComLixo": {"config": _CONFIG, "steps": [{"mode": "turn"}, "lixo", 42, None]},
        },
        123: {"config": _CONFIG, "steps": _STEPS},  # chave nao-string
    }
    saved, imported = import_manual_plan_payload({}, payload)
    assert imported == 2
    assert set(saved.keys()) == {"Valido", "StepsComLixo"}
    assert saved["StepsComLixo"]["steps"] == [{"mode": "turn"}]  # itens nao-dict filtrados


@pytest.mark.parametrize("bad_payload", [None, [], "x", 1])
def test_import_auto_run_payload_rejects_non_dict_payload(bad_payload):
    with pytest.raises(ValueError, match="must contain a JSON object"):
        import_auto_run_payload({}, bad_payload)


def test_import_auto_run_payload_skips_entries_missing_config_or_result():
    payload = {"auto": {
        "SemConfig": {"result": {}},
        "SemResult": {"config": {}},
        "Valido": {"config": {"a": 1}, "result": {"b": 2}},
    }}
    saved, imported = import_auto_run_payload({}, payload)
    assert imported == 1
    assert set(saved.keys()) == {"Valido"}


def test_manual_plan_survives_real_json_file_roundtrip(tmp_path):
    """Simula o fluxo real: exportar (json.dumps), gravar em arquivo,
    reimportar (json.load, como o file_uploader do Streamlit faz), e
    conferir que o plano volta identico -- pega bugs de serializacao
    (chaves nao-string viram string, tuplas viram lista, etc)."""
    payload = {"manual": {"Meu Plano": {"config": _CONFIG, "steps": _STEPS}}}
    export_path = tmp_path / "export.json"
    export_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    reloaded_payload = json.loads(export_path.read_text(encoding="utf-8"))
    saved, imported = import_manual_plan_payload({}, reloaded_payload)
    assert imported == 1
    config, steps = load_manual_plan(saved, "Meu Plano")
    assert config == _CONFIG
    assert steps == _STEPS
