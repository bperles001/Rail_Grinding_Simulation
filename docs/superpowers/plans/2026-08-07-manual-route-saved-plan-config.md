# Manual Route: plano salvo guarda a config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cada plano salvo do Manual Route passa a guardar, junto com os passos, a config com que foi construído (estação inicial, facing, anos, 2º KLD) — carregar um plano salvo aplica essa config automaticamente, em vez de rodar contra a config manual que estiver na tela.

**Architecture:** O formato de armazenamento de cada plano em `data/saved_plans.json["manual"]` muda de "lista de passos" para `{"config": {...}, "steps": [...]}`. Um bloco novo no topo da página Manual Route ("Novo plano" / "Abrir plano salvo") substitui a carga manual de config; a seção "Plan Presets" mais abaixo perde a metade de carregar (fica só Salvar/Deletar) e passa a gravar a config junto no Salvar.

**Tech Stack:** Python 3.10+, pytest, Streamlit (`streamlit.testing.v1.AppTest`).

## Global Constraints

- Só o formato novo (`{"config": ..., "steps": [...]}`) — sem fallback pro formato antigo (lista crua). Decisão explícita do Bruno: app em fase de construção, não vale adicionar complexidade de compatibilidade.
- Os 2 planos hoje salvos (`"Plano - Nós"`, `"Plano - Nós (v2 segment_actions)"`) são migrados pro formato novo usando a config real desta sessão: `start_station="ZTO"`, `facing_station="ZCZ"`, `start_year=2026`, `end_year=2027`, `second_kld=true`.
- Carregar um plano salvo substitui a config atual da tela (mesmo comportamento que já existe quando a Configuration é editada manualmente e o plano é resetado).
- Rodar a suíte completa (`pytest`) a cada task antes de dar como concluída.

---

### Task 1: `plan_storage.py` — cada plano salvo vira `{"config": ..., "steps": [...]}`

**Files:**
- Modify: `src/railroad_backend/persistence/plan_storage.py:56-77, 151-183` (`plan_storage_snapshot`, `save_manual_plan`, `load_manual_plan`, `import_manual_plan_payload`)
- Test: `tests/test_plan_storage.py` (novo arquivo — hoje não existe nenhum teste direto pra este módulo)

**Interfaces:**
- Produces: `save_manual_plan(saved_plans, name, plan, config) -> Dict[str, Any]` (ganha o parâmetro `config: Dict[str, Any]`, sem default); `load_manual_plan(saved_plans, name) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]` (muda de retorno: antes só a lista de passos, agora `(config, steps)`); `plan_storage_snapshot`/`import_manual_plan_payload` passam a esperar/produzir entradas no formato `{"config": {...}, "steps": [...]}` em vez de listas cruas.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/test_plan_storage.py`:

```python
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
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `.venv/Scripts/python.exe -m pytest tests/test_plan_storage.py -v`
Expected: FAIL — `save_manual_plan()` ainda não aceita `config` como 4º argumento posicional (`TypeError: save_manual_plan() takes 3 positional arguments but 4 were given`), e as demais falham por causa do formato antigo.

- [ ] **Step 3: Implementar a mudança de formato**

Em `src/railroad_backend/persistence/plan_storage.py`, trocar (linhas 56-77):

```python
def plan_storage_snapshot(
    manual_saved: Optional[Dict[str, Any]] = None,
    auto_saved: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build storage snapshot from manual and auto plan data.

    Args:
        manual_saved: Dictionary of manual plans.
        auto_saved: Dictionary of auto run results.

    Returns:
        Storage snapshot with manual and auto sections.
    """
    snapshot = storage_defaults()
    if isinstance(manual_saved, dict):
        snapshot["manual"] = {
            name: [dict(step) for step in steps if isinstance(step, dict)]
            for name, steps in manual_saved.items()
        }
    if isinstance(auto_saved, dict):
        snapshot["auto"] = {name: dict(entry) for name, entry in auto_saved.items() if isinstance(entry, dict)}
    return snapshot
```

por:

```python
def plan_storage_snapshot(
    manual_saved: Optional[Dict[str, Any]] = None,
    auto_saved: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build storage snapshot from manual and auto plan data.

    Args:
        manual_saved: Dictionary mapping plan name to {"config": ..., "steps": [...]}.
        auto_saved: Dictionary of auto run results.

    Returns:
        Storage snapshot with manual and auto sections.
    """
    snapshot = storage_defaults()
    if isinstance(manual_saved, dict):
        snapshot["manual"] = {
            name: {
                "config": dict(entry.get("config") or {}),
                "steps": [dict(step) for step in (entry.get("steps") or []) if isinstance(step, dict)],
            }
            for name, entry in manual_saved.items()
            if isinstance(entry, dict)
        }
    if isinstance(auto_saved, dict):
        snapshot["auto"] = {name: dict(entry) for name, entry in auto_saved.items() if isinstance(entry, dict)}
    return snapshot
```

Trocar (linhas 151-165):

```python
def save_manual_plan(
    saved_plans: Optional[Dict[str, Any]],
    name: str,
    plan: List[Dict[str, Any]],
) -> Dict[str, Any]:
    new_plans = dict(saved_plans or {})
    new_plans[name] = [dict(step) for step in plan]
    return new_plans


def load_manual_plan(saved_plans: Optional[Dict[str, Any]], name: str) -> List[Dict[str, Any]]:
    plans = saved_plans or {}
    entries = plans.get(name, [])
    return [dict(step) for step in entries if isinstance(step, dict)]
```

por:

```python
def save_manual_plan(
    saved_plans: Optional[Dict[str, Any]],
    name: str,
    plan: List[Dict[str, Any]],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    new_plans = dict(saved_plans or {})
    new_plans[name] = {
        "config": dict(config),
        "steps": [dict(step) for step in plan],
    }
    return new_plans


def load_manual_plan(saved_plans: Optional[Dict[str, Any]], name: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    plans = saved_plans or {}
    entry = plans.get(name) or {}
    config = dict(entry.get("config") or {})
    steps = entry.get("steps") or []
    return config, [dict(step) for step in steps if isinstance(step, dict)]
```

Trocar (linhas 167-183):

```python
def import_manual_plan_payload(
    saved_plans: Optional[Dict[str, Any]],
    payload: Any,
) -> Tuple[Dict[str, Any], int]:
    if not isinstance(payload, dict):
        raise ValueError("Manual plan file must contain a JSON object.")
    manual_section = payload.get("manual") if "manual" in payload else payload
    if not isinstance(manual_section, dict):
        raise ValueError("Manual plan file must include a 'manual' object or be a mapping of plan names.")
    new_plans = dict(saved_plans or {})
    imported = 0
    for name, steps in manual_section.items():
        if not isinstance(name, str) or not isinstance(steps, list):
            continue
        new_plans[name] = [dict(step) for step in steps if isinstance(step, dict)]
        imported += 1
    return new_plans, imported
```

por:

```python
def import_manual_plan_payload(
    saved_plans: Optional[Dict[str, Any]],
    payload: Any,
) -> Tuple[Dict[str, Any], int]:
    if not isinstance(payload, dict):
        raise ValueError("Manual plan file must contain a JSON object.")
    manual_section = payload.get("manual") if "manual" in payload else payload
    if not isinstance(manual_section, dict):
        raise ValueError("Manual plan file must include a 'manual' object or be a mapping of plan names.")
    new_plans = dict(saved_plans or {})
    imported = 0
    for name, entry in manual_section.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        steps = entry.get("steps")
        if not isinstance(steps, list):
            continue
        new_plans[name] = {
            "config": dict(entry.get("config") or {}),
            "steps": [dict(step) for step in steps if isinstance(step, dict)],
        }
        imported += 1
    return new_plans, imported
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `.venv/Scripts/python.exe -m pytest tests/test_plan_storage.py -v`
Expected: PASS.

- [ ] **Step 5: Rodar a suíte completa**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: FAIL nos testes de `test_streamlit_app_ui.py` que ainda chamam `save_manual_plan`/`load_manual_plan` com a assinatura antiga através de `manual.py` — isso é esperado, `manual.py` ainda não foi atualizado (Tasks 3-4). Confirme que as únicas falhas são nesse arquivo.

- [ ] **Step 6: Commit**

```bash
git add src/railroad_backend/persistence/plan_storage.py tests/test_plan_storage.py
git commit -m "feat: plano salvo do manual route passa a guardar config junto com os passos"
```

---

### Task 2: Migrar os 2 planos já salvos pro formato novo

**Files:**
- Create: `scripts/migrate_saved_plans_add_config.py`
- Modify: `data/saved_plans.json` (gerado pelo script)
- Test: `tests/test_migrate_saved_plans_add_config.py`

**Interfaces:**
- Consumes: nenhuma (script standalone, só lê/escreve JSON).
- Produces: `migrate(data: Dict[str, Any]) -> Dict[str, Any]` em `scripts/migrate_saved_plans_add_config.py`, importável pelo teste.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_migrate_saved_plans_add_config.py`:

```python
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
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate_saved_plans_add_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.migrate_saved_plans_add_config'`.

- [ ] **Step 3: Implementar o script de migração**

Criar `scripts/migrate_saved_plans_add_config.py`:

```python
"""One-off migration: envolve cada plano salvo (lista crua de passos) no
formato novo {"config": ..., "steps": [...]} (Manual Route, 2026-08-07).
Planos ja no formato novo ficam inalterados (idempotente).

Uso: python scripts/migrate_saved_plans_add_config.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

PLANS_PATH = Path(__file__).resolve().parents[1] / "data" / "saved_plans.json"

DEFAULT_CONFIG = {
    "start_station": "ZTO",
    "facing_station": "ZCZ",
    "start_year": 2026,
    "end_year": 2027,
    "second_kld": True,
}


def migrate(data: Dict[str, Any]) -> Dict[str, Any]:
    manual = data.get("manual", {})
    new_manual = {}
    for name, entry in manual.items():
        if isinstance(entry, list):
            new_manual[name] = {"config": dict(DEFAULT_CONFIG), "steps": entry}
        else:
            new_manual[name] = entry
    return {"manual": new_manual, "auto": data.get("auto", {})}


def main() -> None:
    data = json.loads(PLANS_PATH.read_text(encoding="utf-8"))
    migrated = migrate(data)
    PLANS_PATH.write_text(json.dumps(migrated, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Migrado: {list(migrated['manual'].keys())}")


if __name__ == "__main__":
    main()
```

(`scripts/__init__.py` já existe, criado na sessão anterior.)

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate_saved_plans_add_config.py -v`
Expected: PASS.

- [ ] **Step 5: Rodar o script contra o arquivo real e validar**

Run: `.venv/Scripts/python.exe scripts/migrate_saved_plans_add_config.py`

Validar que os dois planos ficaram no formato novo e que `replay_manual_plan` com a config recém-embutida continua sem erros:

Run: `.venv/Scripts/python.exe -c "
import json
from pathlib import Path
from railroad_backend.services.manual_planner import ManualPlanConfig, replay_manual_plan

root = Path('.')
data = json.loads((root / 'data' / 'saved_plans.json').read_text(encoding='utf-8'))
for name, entry in data['manual'].items():
    cfg = entry['config']
    config = ManualPlanConfig(
        csv_path=root / 'data' / 'mtbt_schedule.csv',
        start_station=cfg['start_station'], facing_station=cfg['facing_station'],
        start_year=cfg['start_year'], end_year=cfg['end_year'], second_kld=cfg['second_kld'],
        network_source=root / 'data' / 'networks' / 'network_20251223_115340.json',
    )
    result = replay_manual_plan(config, entry['steps'])
    print(name, '-> errors:', result.errors, '| steps:', len(result.simulator.steps))
"
```

Expected: `errors: []` pros dois planos.

- [ ] **Step 6: Rodar a suíte completa**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: mesmas falhas de antes em `test_streamlit_app_ui.py` (esperadas até a Task 4), nada novo quebrado.

- [ ] **Step 7: Commit**

```bash
git add scripts/migrate_saved_plans_add_config.py tests/test_migrate_saved_plans_add_config.py data/saved_plans.json
git commit -m "chore: migra planos salvos do manual route pro formato config+steps"
```

---

### Task 3: UI — bloco "📂 Plano" no topo da página (Novo plano / Abrir plano salvo)

**Files:**
- Modify: `src/railroad_frontend/views/manual.py:134-136` (insere bloco novo entre a leitura de `plan` e a seção "⚙️ Configuration")
- Test: `tests/test_streamlit_app_ui.py`

**Interfaces:**
- Consumes: `load_manual_plan(saved_plans, name) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]` (Task 1).
- Produces: nenhuma interface nova pra outras tasks — é o consumidor final do carregamento.

- [ ] **Step 1: Escrever os testes que falham**

Adicionar a `tests/test_streamlit_app_ui.py` (perto dos outros testes de Manual Route):

```python
def test_manual_route_new_plan_is_default_mode(tmp_path: Path) -> None:
    at = _open_manual_route(tmp_path)
    radios = [r for r in at.radio if r.label == "Plano"]
    assert radios, "esperava um radio 'Plano' no topo da pagina"
    assert radios[0].value == "Novo plano"


def test_manual_route_open_saved_plan_shows_empty_state_message(tmp_path: Path) -> None:
    at = _open_manual_route(tmp_path)
    plano_radio = [r for r in at.radio if r.label == "Plano"][0]
    plano_radio.set_value("Abrir plano salvo").run()
    captions = [c.value for c in at.caption]
    assert any("Nenhum plano salvo ainda" in c for c in captions)


def test_manual_route_load_saved_plan_applies_config_and_steps(tmp_path: Path) -> None:
    from railroad_frontend.state.session import MANUAL_CONFIG_KEY, MANUAL_PLAN_KEY, MANUAL_SAVED_PLANS_KEY

    at = _open_manual_route(tmp_path)
    loaded_config = {
        "start_station": "B", "facing_station": "C",
        "start_year": 2030, "end_year": 2031, "second_kld": True,
    }
    at.session_state[MANUAL_SAVED_PLANS_KEY] = {
        "Meu Plano": {"config": loaded_config, "steps": [{"mode": "turn"}]}
    }
    at.run()

    plano_radio = [r for r in at.radio if r.label == "Plano"][0]
    plano_radio.set_value("Abrir plano salvo").run()

    select = [s for s in at.selectbox if s.label == "Plano salvo"][0]
    select.set_value("Meu Plano").run()

    load_btn = [b for b in at.button if b.label == "📂 Carregar"][0]
    load_btn.click().run()

    assert not at.exception
    assert at.session_state[MANUAL_CONFIG_KEY] == loaded_config
    assert at.session_state[MANUAL_PLAN_KEY] == [{"mode": "turn"}]
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streamlit_app_ui.py -k "new_plan_is_default or open_saved_plan_shows_empty or load_saved_plan_applies" -v`
Expected: FAIL — não existe nenhum radio com label "Plano" hoje.

- [ ] **Step 3: Implementar o bloco no topo da página**

Em `src/railroad_frontend/views/manual.py`, entre a linha 134
(`plan: List[Dict[str, Any]] = list(state.get(session_keys.plan_key, []))`)
e a linha 136 (`render_section_header("⚙️ Configuration")`), inserir:

```python
    render_section_header("📂 Plano")
    saved_plans = state.get(session_keys.saved_plans_key, {})
    plan_mode = st.radio(
        "Plano",
        ("Novo plano", "Abrir plano salvo"),
        horizontal=True,
        label_visibility="collapsed",
        key="manual_plan_mode",
    )
    if plan_mode == "Abrir plano salvo":
        if saved_plans:
            saved_names = sorted(saved_plans.keys())
            open_selected = st.selectbox("Plano salvo", saved_names, key="manual_open_plan_select")
            if st.button("📂 Carregar", type="primary", key="manual_open_plan_button"):
                loaded_config, loaded_steps = load_manual_plan(saved_plans, open_selected)
                state[session_keys.config_key] = loaded_config
                callbacks.update_manual_plan(loaded_steps)
                st.toast(f"✓ Plano '{open_selected}' carregado (config + passos)", icon="📂")
                callbacks.force_rerun()
        else:
            st.caption("Nenhum plano salvo ainda.")

```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streamlit_app_ui.py -k "new_plan_is_default or open_saved_plan_shows_empty or load_saved_plan_applies" -v`
Expected: PASS.

- [ ] **Step 5: Rodar a suíte completa**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: as falhas remanescentes em `test_streamlit_app_ui.py` devem ser só as ligadas ao botão "📂 Load plan" antigo da seção Plan Presets (Task 4 remove esse botão) — confirme que não sobrou nada além disso.

- [ ] **Step 6: Commit**

```bash
git add src/railroad_frontend/views/manual.py tests/test_streamlit_app_ui.py
git commit -m "feat: bloco Novo plano/Abrir plano salvo no topo do Manual Route aplica config junto"
```

---

### Task 4: UI — "Plan Presets" perde o carregar duplicado, Salvar grava a config

**Files:**
- Modify: `src/railroad_frontend/views/manual.py:314-355` (seção "💾 Plan Presets")
- Test: `tests/test_streamlit_app_ui.py`

**Interfaces:**
- Consumes: `save_manual_plan(saved_plans, name, plan, config)` (Task 1).
- Produces: nenhuma interface nova.

- [ ] **Step 1: Escrever os testes que falham**

Adicionar a `tests/test_streamlit_app_ui.py`:

```python
def test_manual_route_plan_presets_has_no_load_button(tmp_path: Path) -> None:
    at = _open_manual_route(tmp_path)
    assert not [b for b in at.button if b.label == "📂 Load plan"]


def test_manual_route_save_plan_includes_current_config(tmp_path: Path) -> None:
    from railroad_frontend.state.session import MANUAL_SAVED_PLANS_KEY

    at = _open_manual_route(tmp_path)
    wait_btn = [b for b in at.button if b.label == "Add idle period"][0]
    wait_btn.click().run()

    name_input = [t for t in at.text_input if t.label == "Save current plan as"][0]
    name_input.set_value("Teste Save").run()
    save_btn = [b for b in at.button if b.label == "💾 Save plan"][0]
    save_btn.click().run()

    assert not at.exception
    saved = at.session_state[MANUAL_SAVED_PLANS_KEY]
    assert "Teste Save" in saved
    assert set(saved["Teste Save"].keys()) == {"config", "steps"}
    assert saved["Teste Save"]["steps"] == [{"mode": "wait", "days": 3}]
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streamlit_app_ui.py -k "plan_presets_has_no_load or save_plan_includes_current_config" -v`
Expected: FAIL — o botão "📂 Load plan" ainda existe; `save_manual_plan` ainda é chamado sem `config` (`TypeError`).

- [ ] **Step 3: Simplificar a seção "Plan Presets"**

Em `src/railroad_frontend/views/manual.py`, trocar (linhas 314-355):

```python
    render_section_header("💾 Plan Presets", subtitle=True)
    saved_plans = state.get(session_keys.saved_plans_key, {})
    save_col, load_col = st.columns([2, 3])
    with save_col:
        save_name = st.text_input("Save current plan as", key="manual_save_name")
        disabled = not plan
        if st.button("💾 Save plan", disabled=disabled, type="primary", use_container_width=True):
            name = save_name.strip()
            if not name:
                st.warning("Please provide a name before saving the plan. Enter a descriptive name in the input field above.")
            else:
                saved = save_manual_plan(saved_plans, name, plan)
                state[session_keys.saved_plans_key] = saved
                callbacks.persist_plan_storage()
                st.toast(f"✓ Saved plan '{name}'", icon="💾")
    with load_col:
        if saved_plans:
            saved_names = sorted(saved_plans.keys())
            selected_plan = st.selectbox(
                "Saved plans",
                saved_names,
                key="manual_load_select",
            )
            col_load, col_delete = st.columns(2)
            with col_load:
                if st.button("📂 Load plan", use_container_width=True, type="primary"):
                    loaded_plan = load_manual_plan(saved_plans, selected_plan)
                    callbacks.update_manual_plan(loaded_plan)
                    plan = loaded_plan
                    st.toast(f"✓ Loaded plan '{selected_plan}'", icon="📂")
                    callbacks.force_rerun()
            with col_delete:
                st.markdown('<div class="button-danger">', unsafe_allow_html=True)
                if st.button("🗑️ Delete", use_container_width=True, key="delete_plan_btn"):
                    saved_plans.pop(selected_plan, None)
                    state[session_keys.saved_plans_key] = saved_plans
                    callbacks.persist_plan_storage()
                    st.toast(f"✓ Deleted plan '{selected_plan}'", icon="🗑️")
                    callbacks.force_rerun()
                st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.caption("No saved plans yet.")
```

por:

```python
    render_section_header("💾 Plan Presets", subtitle=True)
    saved_plans = state.get(session_keys.saved_plans_key, {})
    save_col, delete_col = st.columns([2, 3])
    with save_col:
        save_name = st.text_input("Save current plan as", key="manual_save_name")
        disabled = not plan
        if st.button("💾 Save plan", disabled=disabled, type="primary", use_container_width=True):
            name = save_name.strip()
            if not name:
                st.warning("Please provide a name before saving the plan. Enter a descriptive name in the input field above.")
            else:
                saved = save_manual_plan(saved_plans, name, plan, config)
                state[session_keys.saved_plans_key] = saved
                callbacks.persist_plan_storage()
                st.toast(f"✓ Saved plan '{name}'", icon="💾")
    with delete_col:
        if saved_plans:
            saved_names = sorted(saved_plans.keys())
            selected_plan = st.selectbox(
                "Saved plans",
                saved_names,
                key="manual_load_select",
            )
            st.markdown('<div class="button-danger">', unsafe_allow_html=True)
            if st.button("🗑️ Delete", use_container_width=True, key="delete_plan_btn"):
                saved_plans.pop(selected_plan, None)
                state[session_keys.saved_plans_key] = saved_plans
                callbacks.persist_plan_storage()
                st.toast(f"✓ Deleted plan '{selected_plan}'", icon="🗑️")
                callbacks.force_rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.caption("No saved plans yet.")
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streamlit_app_ui.py -v`
Expected: PASS em todos.

- [ ] **Step 5: Rodar a suíte completa**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS em tudo.

- [ ] **Step 6: Commit**

```bash
git add src/railroad_frontend/views/manual.py tests/test_streamlit_app_ui.py
git commit -m "feat: Plan Presets salva a config junto e perde o carregar duplicado"
```

---

### Task 5: CHANGELOG e verificação final

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Adicionar entrada no CHANGELOG**

Em `CHANGELOG.md`, dentro de `## [Unreleased]` → `### Added` (já existe essa subseção, criada na rodada anterior), adicionar mais um item:

```markdown
- Manual Route: cada plano salvo agora guarda também a configuração com
  que foi construído (estação inicial, facing, anos, 2º KLD), não só os
  passos. Um bloco novo no topo da página ("Novo plano"/"Abrir plano
  salvo") aplica essa configuração automaticamente ao carregar — corrige
  o erro que ocorria ao carregar um plano salvo enquanto a tela estava
  configurada para outra estação/direção. Formato de armazenamento muda
  de lista de passos para `{"config": ..., "steps": [...]}`; os 2 planos
  já salvos foram migrados.
```

- [ ] **Step 2: Rodar a suíte completa uma última vez**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, sem nenhum teste pulado/falho.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: registra no changelog a config junto com o plano salvo no manual route"
```

---

## Depois de terminar

Registrar a sessão em `E:\Projetos\SecondBrain\projetos\simulador-esmerilhamento\decisoes.md` (arquivos tocados, testes finais, bug original relatado e confirmação de que sumiu) e uma linha em `E:\Projetos\SecondBrain\log.md`.
