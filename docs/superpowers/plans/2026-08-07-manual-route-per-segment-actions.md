# Manual Route: ação independente por segmento (Singela/LP/LD) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each passo "move" do Manual Route escolher uma ação independente (Nada/Curva/Completa) por segmento físico do trecho (Singela, Pátio Carregado-LP, Pátio Vazio-LD), em vez de uma única ação para o trecho inteiro — e trocar o bloqueio de manutenção desalinhada sem 2º KLD por uma flag de "leitura não capturada" que não impede o serviço.

**Architecture:** `Simulator.move_to()` ganha um parâmetro `segment_actions: Dict[str, str]` que, quando presente, substitui inteiramente o caminho `action`/`maintain_segments` existente (mantido intocado para o Auto Planner). O schema do passo de plano manual muda de `action`+`maintain_segments` para `segment_actions`; validação, execução e UI do Manual Route seguem essa mudança. Uma migração one-off converte o único plano salvo compatível (`"Plano - Nós"`) e descarta os incompatíveis.

**Tech Stack:** Python 3.10+, pytest, Streamlit (`streamlit.testing.v1.AppTest` para testes de UI), pandas.

## Global Constraints

- Escopo: só Manual Route. `Simulator.move_to()` deve continuar aceitando `action`/`maintain_segments` sem `segment_actions` exatamente como hoje — é o caminho usado pelo Auto Planner (`src/railroad_backend/services/auto_planner.py:286`) e não pode mudar de comportamento.
- 3 estados por segmento: `"none"`, `"curva"`, `"completa"` — sem estado "só tangente" isolado.
- Mesma duração (`maintenance_time_days`) para `curva` e `completa` — sem campo de duração diferenciado nesta rodada.
- Manutenção via `segment_actions` **sempre executa e sempre reseta o MTBT** quando o token não é `"none"`, independente de alinhamento de facing ou 2º KLD. O alinhamento vira só uma flag informativa (`kld_reading`), nunca um bloqueio, nesse caminho.
- Sem shim de compatibilidade permanente: passos de plano manual passam a exigir `segment_actions`; os campos antigos `action`/`maintain_segments` deixam de ser lidos pelo Manual Route (continuam existindo em `move_to()` só para o Auto Planner).
- Rodar a suíte completa (`pytest`) a cada task antes de dar como concluída — a suíte tem ~130 testes hoje, nenhuma regressão é aceitável.

---

### Task 1: `Simulator.move_to()` aceita `segment_actions` e grava `kld_reading`

**Files:**
- Modify: `src/simulator/core.py:288-427` (método `move_to`)
- Test: `tests/test_edge_cases.py` (usa o fixture `_write_trio_network` já existente em `tests/test_edge_cases.py:14-42`)

**Interfaces:**
- Produces: `Simulator.move_to(self, segments, next_station, action="v", duration_override=None, maintain_segments=None, segment_actions: Optional[Dict[str, str]] = None) -> Dict[str, object]` — quando `segment_actions` não é `None`, ignora `action`/`maintain_segments` para decidir o que mantém; retorna o mesmo `{"performed": bool, "duration": int}` de hoje. `self.steps[-1]` ganha a chave `"kld_reading": Dict[str, bool]` (só com os nomes dos segmentos efetivamente mantidos nesta passada; dict vazio quando `segment_actions` é `None` ou todos os tokens são `"none"`).

- [ ] **Step 1: Escrever os testes que falham**

Adicionar ao final de `tests/test_edge_cases.py`:

```python
def test_move_to_with_segment_actions_mixes_curva_and_completa(tmp_path):
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    singela, directional = segments
    singela.add_load(10.0)  # threshold 100/100 -- so "curva" nao teria zerado por acaso
    directional.add_load(10.0)  # threshold 5/20

    sim.machine.second_kld_installed = True  # elimina a variavel de alinhamento deste teste
    result = sim.move_to(
        segments, destination, action=ACTION_MOVE,
        segment_actions={"A-B": "curva", "A-B-LD": "completa"},
    )

    assert result["performed"] is True
    assert singela.load_curva == 0.0
    assert singela.load_tangente == 10.0  # so curva foi resetada
    assert directional.load_curva == 0.0
    assert directional.load_tangente == 0.0  # completa reseta os dois
    # duracao: maintenance_time_days dos dois, porque nenhum token e "none"
    assert result["duration"] == singela.maintenance_time_days + directional.maintenance_time_days
    assert sim.steps[-1]["maintained_segments"] == ["A-B", "A-B-LD"]


def test_move_to_with_segment_actions_none_skips_segment_entirely(tmp_path):
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    singela, directional = segments
    singela.add_load(10.0)
    directional.add_load(10.0)

    sim.machine.second_kld_installed = True
    result = sim.move_to(
        segments, destination, action=ACTION_MOVE,
        segment_actions={"A-B": "none", "A-B-LD": "completa"},
    )

    assert singela.load_curva == 10.0  # nao mantido, load intacto (so passou por cima)
    assert directional.load_curva == 0.0  # mantido
    # duracao: move_time_days da singela (nao mantida) + maintenance_time_days da directional
    assert result["duration"] == singela.move_time_days + directional.maintenance_time_days
    assert sim.steps[-1]["maintained_segments"] == ["A-B-LD"]


def test_move_to_with_segment_actions_always_performs_without_second_kld_misaligned(tmp_path):
    """Mudanca de comportamento central desta rodada: hoje, sem 2o KLD e
    desalinhado, a manutencao nao executa (performed=False, MTBT intacto).
    Com segment_actions, ela sempre executa -- so a leitura do KLD fica
    marcada como nao capturada."""
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]
    singela, directional = segments  # directional = A-B-LD, Vazio por sufixo
    directional.add_load(10.0)

    assert sim.machine.global_direction == "VAZIO"  # facing B via A-B-LD
    sim.machine.global_direction = "CARREGADO"  # forca desalinhamento com A-B-LD (Vazio)
    sim.machine.second_kld_installed = False

    result = sim.move_to(
        segments, destination, action=ACTION_MOVE,
        segment_actions={"A-B": "none", "A-B-LD": "completa"},
    )

    assert result["performed"] is True
    assert directional.load_curva == 0.0 and directional.load_tangente == 0.0  # MTBT reseta igual
    assert sim.steps[-1]["kld_reading"] == {"A-B-LD": False}  # sem leitura, mas o servico ocorreu


def test_move_to_with_segment_actions_records_true_when_aligned(tmp_path):
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]

    assert sim.machine.global_direction == "VAZIO"  # A-B-LD e Vazio por sufixo: alinhado
    result = sim.move_to(
        segments, destination, action=ACTION_MOVE,
        segment_actions={"A-B": "none", "A-B-LD": "completa"},
    )

    assert result["performed"] is True
    assert sim.steps[-1]["kld_reading"] == {"A-B-LD": True}


def test_move_to_with_segment_actions_rejects_unknown_segment_name(tmp_path):
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]

    with pytest.raises(ValueError, match="unknown segment"):
        sim.move_to(
            segments, destination, action=ACTION_MOVE,
            segment_actions={"NOT-A-REAL-SEGMENT": "completa"},
        )


def test_move_to_with_segment_actions_rejects_invalid_token(tmp_path):
    from src.models import ACTION_MOVE

    path = _write_trio_network(tmp_path)
    sim = Simulator(path)
    sim.init_machine("A", "B", start_year=2025)
    segments, destination = sim.get_all_moves_any_direction()[0]

    with pytest.raises(ValueError, match="must be one of"):
        sim.move_to(
            segments, destination, action=ACTION_MOVE,
            segment_actions={"A-B-LD": "tangente"},
        )
```

Confirme que `import pytest` já está no topo de `tests/test_edge_cases.py` (usado pelo `pytest.raises`); se não estiver, adicione.

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `.venv/Scripts/python.exe -m pytest tests/test_edge_cases.py -k segment_actions -v`
Expected: FAIL — `move_to() got an unexpected keyword argument 'segment_actions'` em todos os 6 testes novos.

- [ ] **Step 3: Implementar `segment_actions` em `move_to()`**

Em `src/simulator/core.py`, mudar a assinatura (linha 288) de:

```python
    def move_to(self, segments: Union[Segment, Sequence[Segment]], next_station: Station, action: str = "v", duration_override: Optional[int] = None, maintain_segments: Optional[Sequence[Segment]] = None) -> Dict[str, object]:
```

para:

```python
    def move_to(self, segments: Union[Segment, Sequence[Segment]], next_station: Station, action: str = "v", duration_override: Optional[int] = None, maintain_segments: Optional[Sequence[Segment]] = None, segment_actions: Optional[Dict[str, str]] = None) -> Dict[str, object]:
```

Substituir o bloco (linhas 362-372 no arquivo atual):

```python
        maintained: Tuple[Segment, ...] = ()
        performed = False
        if action in (ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES):
            component = "curva" if action == ACTION_MAINTAIN_CURVES else "both"
            maintain_set = list(maintain_segments) if maintain_segments is not None else list(segments)
            if machine.second_kld_installed or edge_dir == machine.global_direction:
                for component_seg in segments:
                    if component_seg in maintain_set:
                        machine.perform_maintenance(component_seg, component=component)
                maintained = tuple(s for s in segments if s in maintain_set)
                performed = True
```

por:

```python
        maintained: Tuple[Segment, ...] = ()
        performed = False
        kld_reading: Dict[str, bool] = {}
        if segment_actions is not None:
            valid_tokens = ("none", "curva", "completa")
            segment_names = {s.name for s in segments}
            unknown = set(segment_actions) - segment_names
            if unknown:
                raise ValueError(f"segment_actions has unknown segment name(s): {sorted(unknown)!r}")
            maintained_list = []
            for component_seg in segments:
                token = segment_actions.get(component_seg.name, "none")
                if token not in valid_tokens:
                    raise ValueError(f"segment_actions[{component_seg.name!r}] must be one of {valid_tokens!r}, got {token!r}")
                if token == "none":
                    continue
                component = "curva" if token == "curva" else "both"
                seg_edge_dir = _classify_directional_segment(component_seg, current_station.name)
                kld_reading[component_seg.name] = bool(
                    machine.second_kld_installed or seg_edge_dir == machine.global_direction
                )
                machine.perform_maintenance(component_seg, component=component)
                maintained_list.append(component_seg)
                performed = True
            maintained = tuple(maintained_list)
        elif action in (ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES):
            component = "curva" if action == ACTION_MAINTAIN_CURVES else "both"
            maintain_set = list(maintain_segments) if maintain_segments is not None else list(segments)
            if machine.second_kld_installed or edge_dir == machine.global_direction:
                for component_seg in segments:
                    if component_seg in maintain_set:
                        machine.perform_maintenance(component_seg, component=component)
                maintained = tuple(s for s in segments if s in maintain_set)
                performed = True
```

Note que `current_station` já está disponível nesse ponto do método (definido na linha 337: `current_station = self.current_station`), antes do bloco de manutenção.

Por fim, no dict retornado em `self.steps.append({...})` (linhas 394-417), adicionar a chave nova logo após `"maintained_segments"`:

```python
                "maintained_segments": [s.name for s in maintained],
                "kld_reading": kld_reading,
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `.venv/Scripts/python.exe -m pytest tests/test_edge_cases.py -k segment_actions -v`
Expected: PASS nos 6 testes novos.

- [ ] **Step 5: Rodar a suíte completa (regressão)**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS em todos os testes existentes (o caminho `action`/`maintain_segments` não mudou de comportamento).

- [ ] **Step 6: Commit**

```bash
git add src/simulator/core.py tests/test_edge_cases.py
git commit -m "feat: move_to aceita segment_actions com leitura KLD independente de alinhamento"
```

---

### Task 2: `ManualMoveOption` expõe alinhamento por segmento

**Files:**
- Modify: `src/railroad_backend/services/manual_planner.py:87-92, 231-254`
- Modify: `src/railroad_frontend/views/manual.py:453-459` (único consumidor de `maintenance_aligned`)
- Test: `tests/test_edge_cases.py:240-248`, `tests/test_integration.py:225-245`

**Interfaces:**
- Consumes: nada novo (usa `Simulator.get_possible_moves()`/`get_all_moves_any_direction()` já existentes).
- Produces: `ManualMoveOption` com campo `segment_alignment: Dict[str, bool]` no lugar de `maintenance_aligned: bool` — uma entrada por nome de segmento do trecho, `True` quando `second_kld_installed or edge_dir == global_direction` para aquele segmento especificamente.

- [ ] **Step 1: Atualizar os testes existentes que dependiam de `maintenance_aligned`**

Em `tests/test_edge_cases.py:221-237`, trocar a linha final:

```python
    assert to_b.maintenance_aligned is True
```

por:

```python
    # A-B (Singela, sem sufixo) classifica por heuristica start/end: partindo
    # de A, isso da CARREGADO -- que nao bate com o global_direction VAZIO
    # setado pelo facing inicial. A-B-LD classifica VAZIO por sufixo, que bate.
    assert to_b.segment_alignment == {"A-B": False, "A-B-LD": True}
```

Em `tests/test_integration.py:225-245`, trocar:

```python
        assert hasattr(move, "maintenance_aligned")
```

por:

```python
        assert hasattr(move, "segment_alignment")
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `.venv/Scripts/python.exe -m pytest tests/test_edge_cases.py tests/test_integration.py -k "segment_alignment or facing_agrees" -v`
Expected: FAIL — `AttributeError: 'ManualMoveOption' object has no attribute 'segment_alignment'`.

- [ ] **Step 3: Implementar `segment_alignment`**

Em `src/railroad_backend/services/manual_planner.py`, trocar o dataclass (linhas 87-92):

```python
@dataclass(frozen=True)
class ManualMoveOption:
    segments: Tuple[str, ...]
    destination: str
    maintenance_aligned: bool
```

por:

```python
@dataclass(frozen=True)
class ManualMoveOption:
    segments: Tuple[str, ...]
    destination: str
    segment_alignment: Dict[str, bool]
```

E em `list_available_moves` (linhas 231-254), trocar:

```python
def list_available_moves(sim: Simulator) -> List[ManualMoveOption]:
    """List all possible moves from current position.

    Args:
        sim: Simulator instance.

    Returns:
        List of ManualMoveOption sorted by alignment and destination.
    """
    aligned_pairs = {
        (tuple(seg.name for seg in segments), dest.name)
        for segments, dest in sim.get_possible_moves()
    }
    options: List[ManualMoveOption] = []
    seen = set()
    for segments, dest in sim.get_all_moves_any_direction():
        names = tuple(seg.name for seg in segments)
        key = (names, dest.name)
        if key in seen:
            continue
        seen.add(key)
        options.append(ManualMoveOption(segments=names, destination=dest.name, maintenance_aligned=key in aligned_pairs))
    options.sort(key=lambda item: (0 if item.maintenance_aligned else 1, item.destination))
    return options
```

por:

```python
def list_available_moves(sim: Simulator) -> List[ManualMoveOption]:
    """List all possible moves from current position.

    Args:
        sim: Simulator instance.

    Returns:
        List of ManualMoveOption sorted by alignment (mais segmentos
        alinhados primeiro) e destino.
    """
    from src.simulator.core import _classify_directional_segment

    machine = sim.machine
    current_name = sim.current_station.name if sim.current_station else ""
    options: List[ManualMoveOption] = []
    seen = set()
    for segments, dest in sim.get_all_moves_any_direction():
        names = tuple(seg.name for seg in segments)
        key = (names, dest.name)
        if key in seen:
            continue
        seen.add(key)
        segment_alignment = {}
        for seg in segments:
            edge_dir = _classify_directional_segment(seg, current_name)
            segment_alignment[seg.name] = bool(
                machine and (machine.second_kld_installed or edge_dir == machine.global_direction)
            )
        options.append(ManualMoveOption(segments=names, destination=dest.name, segment_alignment=segment_alignment))
    options.sort(
        key=lambda item: (
            0 if all(item.segment_alignment.values()) else 1,
            item.destination,
        )
    )
    return options
```

Adicionar `Dict` ao import de `typing` no topo do arquivo (linha 7): já importa `Dict` — conferir (`from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union`), nenhuma mudança necessária aí.

- [ ] **Step 4: Atualizar o único consumidor em `manual.py`**

Em `src/railroad_frontend/views/manual.py:453-459`:

```python
            second_kld_installed = bool(getattr(getattr(sim_preview, "machine", None), "second_kld_installed", False))

            def _format_option(opt: ManualMoveOption) -> str:
                maintenance_allowed = opt.maintenance_aligned or second_kld_installed
                maintenance_note = "maintenance allowed" if maintenance_allowed else "move only"
                via = " + ".join(opt.segments)
                return f"{opt.destination} via {via} ({maintenance_note})"
```

por:

```python
            def _format_option(opt: ManualMoveOption) -> str:
                via = " + ".join(opt.segments)
                if all(opt.segment_alignment.values()):
                    note = "leitura OK"
                elif any(opt.segment_alignment.values()):
                    note = "leitura parcial"
                else:
                    note = "sem leitura KLD"
                return f"{opt.destination} via {via} ({note})"
```

(A variável `second_kld_installed` também é usada mais abaixo em `manual.py` — deixar essa outra ocorrência como está por enquanto; será revisitada na Task 6.)

- [ ] **Step 5: Rodar os testes e confirmar que passam**

Run: `.venv/Scripts/python.exe -m pytest tests/test_edge_cases.py tests/test_integration.py -v`
Expected: PASS.

- [ ] **Step 6: Rodar a suíte completa**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (nenhum outro arquivo usa `maintenance_aligned` fora do que já foi trocado — confirmado por `grep -rn maintenance_aligned src/ tests/` retornando vazio).

- [ ] **Step 7: Commit**

```bash
git add src/railroad_backend/services/manual_planner.py src/railroad_frontend/views/manual.py tests/test_edge_cases.py tests/test_integration.py
git commit -m "feat: ManualMoveOption expoe alinhamento de leitura KLD por segmento"
```

---

### Task 3: Schema `segment_actions` em validação e execução do plano manual

**Files:**
- Modify: `src/railroad_backend/domain/validation.py:67-109`
- Modify: `src/railroad_backend/services/manual_planner.py:151-191` (`_handle_move_step`)
- Test: `tests/test_validation.py:83-145`, `tests/test_integration.py:247-428`

**Interfaces:**
- Consumes: `Simulator.move_to(..., segment_actions=...)` da Task 1.
- Produces: passos "move" do plano manual usam exclusivamente `{"mode": "move", "segments"/"segment": ..., "destination": ..., "segment_actions": {nome: "none"|"curva"|"completa", ...}}`; `days_override` continua opcional. `action`/`maintain_segments` deixam de ser lidos por `validate_manual_plan_step`/`_handle_move_step`.

- [ ] **Step 1: Atualizar os testes de validação**

Em `tests/test_validation.py`, trocar (linhas 83-87):

```python
def test_validate_manual_plan_step_accepts_valid_move():
    """Plan step validation accepts valid move step."""
    step = {"mode": "move", "segment": "TRO-TMI", "destination": "TMI", "action": "v"}
    errors = validate_manual_plan_step(step, 1)
    assert errors == []
```

por:

```python
def test_validate_manual_plan_step_accepts_valid_move():
    """Plan step validation accepts valid move step."""
    step = {
        "mode": "move", "segment": "TRO-TMI", "destination": "TMI",
        "segment_actions": {"TRO-TMI": "completa"},
    }
    errors = validate_manual_plan_step(step, 1)
    assert errors == []
```

Trocar (linhas 112-118):

```python
def test_validate_manual_plan_step_rejects_move_missing_fields():
    """Plan step validation rejects move step missing required fields."""
    step = {"mode": "move", "segment": "TRO-TMI"}  # Missing destination and action
    errors = validate_manual_plan_step(step, 1)
    assert len(errors) >= 2
    assert any("destination" in e for e in errors)
    assert any("action" in e for e in errors)
```

por:

```python
def test_validate_manual_plan_step_rejects_move_missing_fields():
    """Plan step validation rejects move step missing required fields."""
    step = {"mode": "move", "segment": "TRO-TMI"}  # Missing destination and segment_actions
    errors = validate_manual_plan_step(step, 1)
    assert len(errors) >= 2
    assert any("destination" in e for e in errors)
    assert any("segment_actions" in e for e in errors)
```

Trocar (linhas 129-134):

```python
def test_validate_manual_plan_step_rejects_invalid_action():
    """Plan step validation rejects invalid action code."""
    step = {"mode": "move", "segment": "TRO-TMI", "destination": "TMI", "action": "x"}
    errors = validate_manual_plan_step(step, 1)
    assert len(errors) == 1
    assert "action" in errors[0] and "'x'" in errors[0]
```

por:

```python
def test_validate_manual_plan_step_rejects_invalid_segment_action_value():
    """Plan step validation rejects an unknown segment_actions token."""
    step = {
        "mode": "move", "segment": "TRO-TMI", "destination": "TMI",
        "segment_actions": {"TRO-TMI": "x"},
    }
    errors = validate_manual_plan_step(step, 1)
    assert len(errors) == 1
    assert "segment_actions" in errors[0] and "'x'" in errors[0]


def test_validate_manual_plan_step_rejects_segment_actions_key_mismatch():
    """Plan step validation rejects segment_actions keys that don't match segments."""
    step = {
        "mode": "move", "segment": "TRO-TMI", "destination": "TMI",
        "segment_actions": {"OTHER-SEG": "completa"},
    }
    errors = validate_manual_plan_step(step, 1)
    assert len(errors) == 1
    assert "segment_actions" in errors[0]
```

Trocar (linha 140, dentro de `test_validate_manual_plan_accepts_valid_plan`):

```python
        {"mode": "move", "segment": "TRO-TMI", "destination": "TMI", "action": "m"},
```

por:

```python
        {"mode": "move", "segment": "TRO-TMI", "destination": "TMI", "segment_actions": {"TRO-TMI": "completa"}},
```

- [ ] **Step 2: Atualizar os testes de integração (`replay_manual_plan`)**

Em `tests/test_integration.py`, aplicar estas 5 trocas:

Linha 266:
```python
    plan = [{"mode": "move", "segment": seg.name, "destination": "TMI", "action": "v", "days_override": 9}]
```
vira:
```python
    plan = [{"mode": "move", "segment": seg.name, "destination": "TMI", "segment_actions": {seg.name: "none"}, "days_override": 9}]
```

Linha 320:
```python
    plan = [{"mode": "move", "segments": ["A-B", "A-B-LD"], "destination": "B", "action": "v"}]
```
vira:
```python
    plan = [{"mode": "move", "segments": ["A-B", "A-B-LD"], "destination": "B", "segment_actions": {"A-B": "none", "A-B-LD": "none"}}]
```

Linhas 327-374 (a função inteira `test_manual_plan_move_step_with_maintain_segments_resets_only_that_leg` — renomear e trocar o corpo do plano): trocar a assinatura de

```python
def test_manual_plan_move_step_with_maintain_segments_resets_only_that_leg(tmp_path):
    import json
    from src.models import ACTION_MAINTAIN
```

por

```python
def test_manual_plan_move_step_with_segment_actions_resets_only_that_leg(tmp_path):
    import json
```

(remove o `from src.models import ACTION_MAINTAIN`, que fica sem uso) e trocar o corpo do plano (linhas 371-374):

```python
    plan = [{
        "mode": "move", "segments": ["A-B", "A-B-LD"], "destination": "B",
        "action": ACTION_MAINTAIN, "maintain_segments": ["A-B-LD"],
    }]
```

por:

```python
    plan = [{
        "mode": "move", "segments": ["A-B", "A-B-LD"], "destination": "B",
        "segment_actions": {"A-B": "none", "A-B-LD": "completa"},
    }]
```

Linha 400:
```python
    plan = [{"mode": "move", "segment": "TRO-TMI", "destination": "TMI", "action": "v"}]
```
vira:
```python
    plan = [{"mode": "move", "segment": "TRO-TMI", "destination": "TMI", "segment_actions": {"TRO-TMI": "none"}}]
```

Linha 421:
```python
        {"mode": "move", "segment": "INVALID-SEGMENT", "destination": "TMI", "action": "v"},
```
vira:
```python
        {"mode": "move", "segment": "INVALID-SEGMENT", "destination": "TMI", "segment_actions": {"INVALID-SEGMENT": "completa"}},
```

- [ ] **Step 3: Rodar os testes e confirmar que falham**

Run: `.venv/Scripts/python.exe -m pytest tests/test_validation.py tests/test_integration.py -v`
Expected: FAIL — os testes de validação recém-editados falham porque `validate_manual_plan_step` ainda exige `action`; os de integração falham porque `_handle_move_step` ainda espera `action`/`maintain_segments` e vai tratar os passos como "move" sem manutenção nenhuma (asserts de `days`/`load_curva`/`kld_reading` batem errado) ou `validate_manual_plan` rejeita os planos por causa da checagem antiga de `action`.

- [ ] **Step 4: Implementar a mudança em `validate_manual_plan_step`**

Em `src/railroad_backend/domain/validation.py`, trocar o bloco `if mode == "move":` (linhas 87-95):

```python
    if mode == "move":
        if "segment" not in step and "segments" not in step:
            errors.append(f"Step {step_idx}: 'move' mode requires a 'segment' or 'segments' field")
        if "destination" not in step:
            errors.append(f"Step {step_idx}: 'move' mode requires 'destination' field")
        if "action" not in step:
            errors.append(f"Step {step_idx}: 'move' mode requires 'action' field")
        elif step["action"] not in ("v", "m", "move", "maintain", "maintain_curves"):
            errors.append(f"Step {step_idx}: action must be 'move'/'v', 'maintain'/'m', or 'maintain_curves', got '{step['action']}'")
```

por:

```python
    if mode == "move":
        segment_names = step.get("segments")
        if segment_names is None and "segment" in step:
            segment_names = [step["segment"]]
        if segment_names is None:
            errors.append(f"Step {step_idx}: 'move' mode requires a 'segment' or 'segments' field")

        if "destination" not in step:
            errors.append(f"Step {step_idx}: 'move' mode requires 'destination' field")

        segment_actions = step.get("segment_actions")
        valid_tokens = ("none", "curva", "completa")
        if not isinstance(segment_actions, dict):
            errors.append(f"Step {step_idx}: 'move' mode requires a 'segment_actions' mapping (one of {valid_tokens} per segment name)")
        elif segment_names is not None:
            expected = set(segment_names)
            actual = set(segment_actions.keys())
            if actual != expected:
                errors.append(
                    f"Step {step_idx}: 'segment_actions' keys {sorted(actual)} must match segment names {sorted(expected)}"
                )
            invalid = {name: token for name, token in segment_actions.items() if token not in valid_tokens}
            if invalid:
                errors.append(
                    f"Step {step_idx}: 'segment_actions' values must be one of {valid_tokens}, got {invalid!r}"
                )
```

- [ ] **Step 5: Implementar a mudança em `_handle_move_step`**

Em `src/railroad_backend/services/manual_planner.py`, trocar (linhas 151-191):

```python
def _handle_move_step(simulator: Simulator, step: Dict[str, Any], step_idx: int) -> Optional[str]:
    """Execute a move or maintenance step.

    Args:
        simulator: Active simulator instance.
        step: Step definition with segment and destination.
        step_idx: Current step index for error messages.

    Returns:
        Error message if step failed, None if successful.
    """
    dest_name = step.get("destination")  # Changed from next_station
    segment_names = step.get("segments")
    if segment_names is None and "segment" in step:
        segment_names = [step["segment"]]  # plans saved before the corridor change
    if not dest_name or not segment_names:
        return f"Step {step_idx}: incomplete move definition."

    destination = simulator.stations.get(dest_name)
    if destination is None:
        return f"Step {step_idx}: destination {dest_name} is unknown."

    segments = _find_segments_for_move(simulator, segment_names, dest_name)
    if segments is None:
        current = simulator.current_station.name if simulator.current_station else "unknown"
        return f"Step {step_idx}: segment(s) {segment_names} cannot reach {dest_name} from {current}."

    action_code = step.get("action", ACTION_MOVE)
    duration_override = step.get("days_override")
    maintain_segment_names = step.get("maintain_segments")
    maintain_segments = (
        tuple(s for s in segments if s.name in maintain_segment_names)
        if maintain_segment_names is not None
        else None
    )
    try:
        simulator.move_to(segments, destination, action=action_code, duration_override=duration_override, maintain_segments=maintain_segments)
    except (RuntimeError, TypeError, ValueError) as exc:
        logger.warning("Manual plan step %d failed: %s", step_idx, exc)
        return f"Step {step_idx}: failed to execute ({exc})."
    return None
```

por:

```python
def _handle_move_step(simulator: Simulator, step: Dict[str, Any], step_idx: int) -> Optional[str]:
    """Execute a move step using per-segment segment_actions.

    Args:
        simulator: Active simulator instance.
        step: Step definition with segment(s), destination and segment_actions.
        step_idx: Current step index for error messages.

    Returns:
        Error message if step failed, None if successful.
    """
    dest_name = step.get("destination")
    segment_names = step.get("segments")
    if segment_names is None and "segment" in step:
        segment_names = [step["segment"]]  # plans saved before the corridor change
    if not dest_name or not segment_names:
        return f"Step {step_idx}: incomplete move definition."

    destination = simulator.stations.get(dest_name)
    if destination is None:
        return f"Step {step_idx}: destination {dest_name} is unknown."

    segments = _find_segments_for_move(simulator, segment_names, dest_name)
    if segments is None:
        current = simulator.current_station.name if simulator.current_station else "unknown"
        return f"Step {step_idx}: segment(s) {segment_names} cannot reach {dest_name} from {current}."

    segment_actions = step.get("segment_actions")
    if not isinstance(segment_actions, dict):
        return f"Step {step_idx}: 'move' step requires a 'segment_actions' mapping."

    duration_override = step.get("days_override")
    try:
        simulator.move_to(
            segments, destination, action=ACTION_MOVE,
            duration_override=duration_override, segment_actions=segment_actions,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        logger.warning("Manual plan step %d failed: %s", step_idx, exc)
        return f"Step {step_idx}: failed to execute ({exc})."
    return None
```

- [ ] **Step 6: Rodar os testes e confirmar que passam**

Run: `.venv/Scripts/python.exe -m pytest tests/test_validation.py tests/test_integration.py -v`
Expected: PASS.

- [ ] **Step 7: Rodar a suíte completa**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. `test_streamlit_app_ui.py` ainda vai quebrar nesse ponto (Task 5 cuida disso) — se quebrar aqui, é esperado; confirme que as únicas falhas restantes são em `test_streamlit_app_ui.py::test_manual_plan_dataframe_*`.

- [ ] **Step 8: Commit**

```bash
git add src/railroad_backend/domain/validation.py src/railroad_backend/services/manual_planner.py tests/test_validation.py tests/test_integration.py
git commit -m "feat: schema de plano manual passa a exigir segment_actions em vez de action/maintain_segments"
```

---

### Task 4: `_manual_plan_dataframe` mostra resumo de ações por segmento

**Files:**
- Modify: `src/railroad_frontend/views/manual.py:564-621` (`_manual_plan_dataframe`)
- Test: `tests/test_streamlit_app_ui.py:173-200`

**Interfaces:**
- Consumes: `step["segment_actions"]` (produzido pela Task 3).
- Produces: `_segment_role_label(name: str) -> str` e `_segment_actions_summary(segment_actions: Dict[str, str]) -> str`, novas funções módulo-nível em `manual.py`, usadas pela coluna "Action" do DataFrame.

- [ ] **Step 1: Atualizar os testes existentes**

Em `tests/test_streamlit_app_ui.py`, trocar (linhas 173-188):

```python
def test_manual_plan_dataframe_shows_segment_base_days_for_traverse() -> None:
    a = Station("A")
    b = Station("B")
    seg = Segment(name="A-B", start_station=a, end_station=b, length=1.0, move_time_days=3, maintenance_time_days=6)

    plan = [{"mode": "move", "segment": "A-B", "destination": "B", "action": "v"}]
    df = _manual_plan_dataframe(plan, {}, [seg])
    assert df.loc[0, "Days"] == 3

    plan_maint = [{"mode": "move", "segment": "A-B", "destination": "B", "action": "m"}]
    df_maint = _manual_plan_dataframe(plan_maint, {}, [seg])
    assert df_maint.loc[0, "Days"] == 6

    plan_override = [{"mode": "move", "segment": "A-B", "destination": "B", "action": "v", "days_override": 9}]
    df_override = _manual_plan_dataframe(plan_override, {}, [seg])
    assert df_override.loc[0, "Days"] == 9
```

por:

```python
def test_manual_plan_dataframe_shows_segment_base_days_for_traverse() -> None:
    a = Station("A")
    b = Station("B")
    seg = Segment(name="A-B", start_station=a, end_station=b, length=1.0, move_time_days=3, maintenance_time_days=6)

    plan = [{"mode": "move", "segment": "A-B", "destination": "B", "segment_actions": {"A-B": "none"}}]
    df = _manual_plan_dataframe(plan, {}, [seg])
    assert df.loc[0, "Days"] == 3

    plan_maint = [{"mode": "move", "segment": "A-B", "destination": "B", "segment_actions": {"A-B": "completa"}}]
    df_maint = _manual_plan_dataframe(plan_maint, {}, [seg])
    assert df_maint.loc[0, "Days"] == 6
    assert df_maint.loc[0, "Action"] == "Singela: Completa"

    plan_override = [{"mode": "move", "segment": "A-B", "destination": "B", "segment_actions": {"A-B": "none"}, "days_override": 9}]
    df_override = _manual_plan_dataframe(plan_override, {}, [seg])
    assert df_override.loc[0, "Days"] == 9
```

Trocar (linhas 191-200):

```python
def test_manual_plan_dataframe_shows_joined_segment_names_for_corridor_step() -> None:
    a = Station("A")
    b = Station("B")
    singela = Segment(name="A-B", start_station=a, end_station=b, length=10.0, move_time_days=2, maintenance_time_days=3)
    directional = Segment(name="A-B-LD", start_station=a, end_station=b, length=1.0, move_time_days=1, maintenance_time_days=1)

    plan = [{"mode": "move", "segments": ["A-B", "A-B-LD"], "destination": "B", "action": "v"}]
    df = _manual_plan_dataframe(plan, {}, [singela, directional])
    assert df.loc[0, "Segment"] == "A-B + A-B-LD"
    assert df.loc[0, "Days"] == 3  # 2 (Singela) + 1 (directional)
```

por:

```python
def test_manual_plan_dataframe_shows_joined_segment_names_for_corridor_step() -> None:
    a = Station("A")
    b = Station("B")
    singela = Segment(name="A-B", start_station=a, end_station=b, length=10.0, move_time_days=2, maintenance_time_days=3)
    directional = Segment(name="A-B-LD", start_station=a, end_station=b, length=1.0, move_time_days=1, maintenance_time_days=1)

    plan = [{
        "mode": "move", "segments": ["A-B", "A-B-LD"], "destination": "B",
        "segment_actions": {"A-B": "curva", "A-B-LD": "completa"},
    }]
    df = _manual_plan_dataframe(plan, {}, [singela, directional])
    assert df.loc[0, "Segment"] == "A-B + A-B-LD"
    assert df.loc[0, "Days"] == 4  # maintenance_time_days dos dois: 3 (Singela) + 1 (Patio Vazio)
    assert df.loc[0, "Action"] == "Singela: Curva · Pátio Vazio (LD): Completa"


def test_segment_role_label_classifies_by_suffix() -> None:
    from railroad_frontend.views.manual import _segment_role_label

    assert _segment_role_label("A-B") == "Singela"
    assert _segment_role_label("A-B-LP") == "Pátio Carregado (LP)"
    assert _segment_role_label("A-B-C") == "Pátio Carregado (LP)"
    assert _segment_role_label("A-B-LD") == "Pátio Vazio (LD)"
    assert _segment_role_label("A-B-V") == "Pátio Vazio (LD)"
```

Confirme o import de `_manual_plan_dataframe` no topo de `tests/test_streamlit_app_ui.py` — se ele já importa de `railroad_frontend.views.manual`, o import extra dentro do teste novo (`from railroad_frontend.views.manual import _segment_role_label`) é só para deixar o teste autocontido; pode substituir por um import no topo do arquivo se preferir seguir o padrão do resto do arquivo.

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streamlit_app_ui.py -k manual_plan_dataframe -v`
Expected: FAIL.

- [ ] **Step 3: Implementar `_segment_role_label`, `_segment_actions_summary` e reescrever `_manual_plan_dataframe`**

Em `src/railroad_frontend/views/manual.py`, adicionar antes de `_manual_plan_dataframe` (linha 564):

```python
_ACTION_LABELS = {"none": "Nada", "curva": "Curva", "completa": "Completa"}


def _segment_role_label(name: str) -> str:
    if name.endswith(("-LP", "-C")):
        return "Pátio Carregado (LP)"
    if name.endswith(("-LD", "-V")):
        return "Pátio Vazio (LD)"
    return "Singela"


def _segment_actions_summary(segment_actions: Mapping[str, str]) -> str:
    parts = [
        f"{_segment_role_label(name)}: {_ACTION_LABELS.get(token, token)}"
        for name, token in segment_actions.items()
    ]
    return " · ".join(parts) if parts else "—"
```

Trocar o corpo do `else:` (passo "move") dentro de `_manual_plan_dataframe` (linhas 592-620):

```python
        else:
            aligned = step.get("aligned")
            if aligned:
                capability = "Maintenance allowed"
            elif second_kld:
                capability = "Maintenance allowed (2nd KLD)"
            else:
                capability = "Move only"
            _act = step.get("action")
            is_maintenance = _act in ("m", "maintain", "maintain_curves")
            step_segment_names = step.get("segments") or ([step["segment"]] if "segment" in step else [])
            step_seg_objs = [segments_by_name[name] for name in step_segment_names if name in segments_by_name]
            base_days = sum(
                (seg_obj.maintenance_time_days if is_maintenance else seg_obj.move_time_days)
                for seg_obj in step_seg_objs
            ) if step_seg_objs else None
            rows.append({
                "Step": idx,
                "Type": "Traverse",
                "Segment": " + ".join(step_segment_names),
                "Destination": step.get("destination", ""),
                "Action": (
                    "Maintenance" if _act in ("m", "maintain")
                    else "Curves only" if _act == "maintain_curves"
                    else "Move"
                ),
                "Days": step.get("days_override", base_days),
                "Capability": capability,
            })
```

por:

```python
        else:
            segment_actions = step.get("segment_actions", {})
            step_segment_names = step.get("segments") or ([step["segment"]] if "segment" in step else [])
            step_seg_objs = [segments_by_name[name] for name in step_segment_names if name in segments_by_name]
            base_days = sum(
                (
                    seg_obj.maintenance_time_days
                    if segment_actions.get(seg_obj.name, "none") != "none"
                    else seg_obj.move_time_days
                )
                for seg_obj in step_seg_objs
            ) if step_seg_objs else None
            rows.append({
                "Step": idx,
                "Type": "Traverse",
                "Segment": " + ".join(step_segment_names),
                "Destination": step.get("destination", ""),
                "Action": _segment_actions_summary(segment_actions),
                "Days": step.get("days_override", base_days),
                "Capability": "—",
            })
```

A variável `second_kld = bool(config.get("second_kld", False))` (linha 567, início da função) fica sem uso nesse trecho — pode ser removida da função inteira já que não é mais lida em nenhum lugar dela; confira com `grep -n "second_kld" src/railroad_frontend/views/manual.py` que a única outra ocorrência da variável local `second_kld` (não a chave de config) era essa.

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streamlit_app_ui.py -v`
Expected: PASS.

- [ ] **Step 5: Rodar a suíte completa**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/railroad_frontend/views/manual.py tests/test_streamlit_app_ui.py
git commit -m "feat: tabela do plano manual mostra resumo de acao por segmento"
```

---

### Task 5: Tabela de passos — coluna "Action" vira somente-leitura

**Files:**
- Modify: `src/railroad_frontend/views/manual.py:214-306` (bloco do editor de passos)

**Interfaces:**
- Consumes: `_segment_actions_summary` (Task 4).
- Produces: nenhuma interface nova — só remove a capacidade de editar `action`/`days_override` de ação inline; "Days" continua editável.

- [ ] **Step 1: Remover a edição de Action do `data_editor` e do handler de submit**

Em `src/railroad_frontend/views/manual.py`, dentro de `render_manual_route_page`, trocar o bloco (linhas 225-264):

```python
        from src.models import ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES, ACTION_MOVE
        _ACTION_OPTIONS = ["Move", "Maintenance", "Curves only", "—"]
        _ACTION_MAP = {
            "Move": ACTION_MOVE,
            "Maintenance": ACTION_MAINTAIN,
            "Curves only": ACTION_MAINTAIN_CURVES,
        }
        st.caption("Edit **Action** or **Days**, then click Apply to save changes.")
        # Wrapped in a form (matches the Network Editor's Stations/Segments/Layout
        # tables): a bare data_editor reruns on every keystroke and rebuilds its
        # own `data=` baseline from the state the previous keystroke just wrote,
        # which makes Streamlit discard the edit buffer (same bug fixed for the
        # layout table on 2026-08-04). Gating behind an explicit submit avoids it.
        with st.form("plan_step_editor_form", clear_on_submit=False):
            edited_df = st.data_editor(
                plan_df,
                key="plan_step_editor",
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                column_config={
                    "Step": st.column_config.NumberColumn(disabled=True),
                    "Type": st.column_config.TextColumn(disabled=True),
                    "Segment": st.column_config.TextColumn(disabled=True),
                    "Destination": st.column_config.TextColumn(disabled=True),
                    "Action": st.column_config.SelectboxColumn(
                        "Action",
                        options=_ACTION_OPTIONS,
                        required=True,
                    ),
                    "Days": st.column_config.NumberColumn(
                        "Days",
                        min_value=1,
                        max_value=365,
                        step=1,
                    ),
                    "Capability": st.column_config.TextColumn(disabled=True),
                },
            )
            step_changes_submitted = st.form_submit_button("Apply step changes")

        if step_changes_submitted:
            _segments_by_name = {seg.name: seg for seg in callbacks.network_segments_provider()}
            _new_plan = list(plan)
            _changed = False
            for _i, _row in edited_df.iterrows():
                _step = _new_plan[_i]
                _mode = _step.get("mode")
                if _mode == "move":
                    _new_code = _ACTION_MAP.get(str(_row.get("Action", "Move")), ACTION_MOVE)
                    if _new_code != _step.get("action"):
                        _step = {**_step, "action": _new_code}
                        _new_plan[_i] = _step
                        _changed = True
                    _is_maintenance = _step.get("action") in ("m", "maintain", "maintain_curves")
                    _step_segment_names = _step.get("segments") or ([_step["segment"]] if "segment" in _step else [])
                    _step_seg_objs = [_segments_by_name[name] for name in _step_segment_names if name in _segments_by_name]
                    _base_days = sum(
                        (o.maintenance_time_days if _is_maintenance else o.move_time_days) for o in _step_seg_objs
                    ) if _step_seg_objs else None
                    try:
                        _edited_days = int(_row.get("Days")) if _row.get("Days") is not None else _base_days
                    except (TypeError, ValueError):
                        _edited_days = _base_days
                    if _edited_days is not None and _edited_days != _base_days:
                        if _step.get("days_override") != _edited_days:
                            _new_plan[_i] = {**_step, "days_override": _edited_days}
                            _changed = True
                    elif "days_override" in _step:
                        _new_plan[_i] = {k: v for k, v in _step.items() if k != "days_override"}
                        _changed = True
                elif _mode == "wait":
                    try:
                        _new_days = max(1, min(365, int(_row.get("Days") or _step.get("days", 1))))
                    except (TypeError, ValueError):
                        _new_days = _step.get("days", 1)
                    if _new_days != _step.get("days"):
                        _new_plan[_i] = {**_step, "days": _new_days}
                        _changed = True
            if _changed:
                callbacks.update_manual_plan(_new_plan)
            callbacks.force_rerun()
```

por:

```python
        st.caption(
            "**Action** é somente leitura — pra mudar a ação de um passo, remova-o "
            "e recrie pelo formulário abaixo. Edite **Days** e clique Apply pra salvar."
        )
        # Wrapped in a form (matches the Network Editor's Stations/Segments/Layout
        # tables): a bare data_editor reruns on every keystroke and rebuilds its
        # own `data=` baseline from the state the previous keystroke just wrote,
        # which makes Streamlit discard the edit buffer (same bug fixed for the
        # layout table on 2026-08-04). Gating behind an explicit submit avoids it.
        with st.form("plan_step_editor_form", clear_on_submit=False):
            edited_df = st.data_editor(
                plan_df,
                key="plan_step_editor",
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                column_config={
                    "Step": st.column_config.NumberColumn(disabled=True),
                    "Type": st.column_config.TextColumn(disabled=True),
                    "Segment": st.column_config.TextColumn(disabled=True),
                    "Destination": st.column_config.TextColumn(disabled=True),
                    "Action": st.column_config.TextColumn(disabled=True),
                    "Days": st.column_config.NumberColumn(
                        "Days",
                        min_value=1,
                        max_value=365,
                        step=1,
                    ),
                    "Capability": st.column_config.TextColumn(disabled=True),
                },
            )
            step_changes_submitted = st.form_submit_button("Apply step changes")

        if step_changes_submitted:
            _segments_by_name = {seg.name: seg for seg in callbacks.network_segments_provider()}
            _new_plan = list(plan)
            _changed = False
            for _i, _row in edited_df.iterrows():
                _step = _new_plan[_i]
                _mode = _step.get("mode")
                if _mode == "move":
                    _step_segment_names = _step.get("segments") or ([_step["segment"]] if "segment" in _step else [])
                    _step_seg_objs = [_segments_by_name[name] for name in _step_segment_names if name in _segments_by_name]
                    _segment_actions = _step.get("segment_actions", {})
                    _base_days = sum(
                        (o.maintenance_time_days if _segment_actions.get(o.name, "none") != "none" else o.move_time_days)
                        for o in _step_seg_objs
                    ) if _step_seg_objs else None
                    try:
                        _edited_days = int(_row.get("Days")) if _row.get("Days") is not None else _base_days
                    except (TypeError, ValueError):
                        _edited_days = _base_days
                    if _edited_days is not None and _edited_days != _base_days:
                        if _step.get("days_override") != _edited_days:
                            _new_plan[_i] = {**_step, "days_override": _edited_days}
                            _changed = True
                    elif "days_override" in _step:
                        _new_plan[_i] = {k: v for k, v in _step.items() if k != "days_override"}
                        _changed = True
                elif _mode == "wait":
                    try:
                        _new_days = max(1, min(365, int(_row.get("Days") or _step.get("days", 1))))
                    except (TypeError, ValueError):
                        _new_days = _step.get("days", 1)
                    if _new_days != _step.get("days"):
                        _new_plan[_i] = {**_step, "days": _new_days}
                        _changed = True
            if _changed:
                callbacks.update_manual_plan(_new_plan)
            callbacks.force_rerun()
```

- [ ] **Step 2: Rodar a suíte completa e checar manualmente no app**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

Run local (não é teste automatizado, é checagem visual rápida): `.venv/Scripts/python.exe run_streamlit.py`, abrir Manual Route, confirmar que a coluna Action aparece como texto (não dropdown) e que editar só Days ainda funciona.

- [ ] **Step 3: Commit**

```bash
git add src/railroad_frontend/views/manual.py
git commit -m "feat: coluna Action da tabela de passos vira somente-leitura"
```

---

### Task 6: Formulário "Add next step" — um radio por segmento com aviso de leitura

**Files:**
- Modify: `src/railroad_frontend/views/manual.py:445-505`
- Test: `tests/test_streamlit_app_ui.py` (novo teste via `AppTest`)

**Interfaces:**
- Consumes: `ManualMoveOption.segment_alignment` (Task 2), `_segment_role_label` (Task 4).
- Produces: passo `{"mode": "move", "segments": [...], "destination": ..., "segment_actions": {...}}` adicionado ao plano ao submeter.

- [ ] **Step 1: Escrever o teste de UI que falha**

Localizar em `tests/test_streamlit_app_ui.py` a função helper que abre a página de Manual Route (padrão usado por `_open_network_editor` para o Network Editor — procurar com `grep -n "def _open" tests/test_streamlit_app_ui.py`; se não existir uma equivalente para Manual Route, criar seguindo o mesmo padrão: instanciar `AppTest.from_file` apontando pro entrypoint do Streamlit e navegar até a página). Adicionar:

```python
def test_manual_route_add_move_form_has_one_radio_per_segment(tmp_path: Path) -> None:
    at = _open_manual_route(tmp_path)  # mesma convenção de _open_network_editor

    radios = [r for r in at.radio if r.label.startswith(("Singela", "Pátio"))]
    assert len(radios) >= 1  # ao menos 1 segmento na primeira opcao de movimento disponivel
    for r in radios:
        assert set(r.options) == {"Nada", "Só curva", "Completa"}
```

Se `_open_manual_route` não existir ainda, criar (seguindo o padrão de `_open_network_editor` já presente no arquivo — inicializar sessão com uma rede+CSV mínimos e navegar pra página "Manual Route" antes do primeiro `.run()`).

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streamlit_app_ui.py -k add_move_form -v`
Expected: FAIL — ainda existe só 1 radio ("Action") no formulário atual, não um por segmento.

- [ ] **Step 3: Reescrever o formulário "Add next step"**

Em `src/railroad_frontend/views/manual.py`, trocar (linhas 445-505):

```python
    st.markdown("### Add next step")
    if preview_errors:
        st.info("Resolve the plan issues above before adding more steps.")
    else:
        move_options = list_available_moves(sim_preview)
        if not move_options:
            st.warning("No moves are available from the current station. Consider adding a turn, waiting, or clearing the plan.")
        else:
            second_kld_installed = bool(getattr(getattr(sim_preview, "machine", None), "second_kld_installed", False))

            def _format_option(opt: ManualMoveOption) -> str:
                via = " + ".join(opt.segments)
                if all(opt.segment_alignment.values()):
                    note = "leitura OK"
                elif any(opt.segment_alignment.values()):
                    note = "leitura parcial"
                else:
                    note = "sem leitura KLD"
                return f"{opt.destination} via {via} ({note})"

            with st.form("manual_move_form", clear_on_submit=True):
                selected_option = st.selectbox("Next station", move_options, format_func=_format_option)
                action_choice = st.radio(
                    "Action",
                    ("Move", "Maintenance", "Curves only"),
                    horizontal=True,
                )
                # Widgets inside st.form don't rerun the script on change (only
                # on submit), so this can't be conditioned on action_choice's
                # in-progress value -- that would still reflect the *previous*
                # submission, and the picker would never exist yet for the
                # very click that first switches away from "Move". Always
                # show it whenever the corridor has 2 segments; whether it's
                # used depends only on the action actually submitted, below.
                maintain_choice = None
                if len(selected_option.segments) == 2:
                    singela_name, directional_name = selected_option.segments
                    maintain_choice = st.radio(
                        "Manutenção (se a ação for Manutenção ou Só curvas)",
                        ("Ambos", f"Só a Singela ({singela_name})", f"Só o pátio ({directional_name})"),
                        horizontal=True,
                        help="Se a Singela já foi feita numa passada anterior, escolha só o pátio (ou vice-versa). Ignorado se a ação for Move.",
                    )
                submitted_move = st.form_submit_button("Add move")
            if submitted_move:
                from src.models import ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES, ACTION_MOVE
                action_code = (
                    ACTION_MAINTAIN if action_choice == "Maintenance"
                    else ACTION_MAINTAIN_CURVES if action_choice == "Curves only"
                    else ACTION_MOVE
                )
                new_step = {
                    "mode": "move",
                    "segments": list(selected_option.segments),
                    "destination": selected_option.destination,
                    "action": action_code,
                }
                if action_code != ACTION_MOVE and maintain_choice and maintain_choice != "Ambos":
                    singela_name, directional_name = selected_option.segments
                    chosen_name = singela_name if maintain_choice.startswith("Só a Singela") else directional_name
                    new_step["maintain_segments"] = [chosen_name]
                new_plan = plan + [new_step]
                callbacks.update_manual_plan(new_plan)
                plan = new_plan
                callbacks.force_rerun()
```

por:

```python
    st.markdown("### Add next step")
    if preview_errors:
        st.info("Resolve the plan issues above before adding more steps.")
    else:
        move_options = list_available_moves(sim_preview)
        if not move_options:
            st.warning("No moves are available from the current station. Consider adding a turn, waiting, or clearing the plan.")
        else:
            def _format_option(opt: ManualMoveOption) -> str:
                via = " + ".join(opt.segments)
                if all(opt.segment_alignment.values()):
                    note = "leitura OK"
                elif any(opt.segment_alignment.values()):
                    note = "leitura parcial"
                else:
                    note = "sem leitura KLD"
                return f"{opt.destination} via {via} ({note})"

            _ACTION_TOKENS = {"Nada": "none", "Só curva": "curva", "Completa": "completa"}

            with st.form("manual_move_form", clear_on_submit=True):
                selected_option = st.selectbox("Next station", move_options, format_func=_format_option)
                segment_choices: Dict[str, str] = {}
                for seg_name in selected_option.segments:
                    aligned = selected_option.segment_alignment.get(seg_name, False)
                    warning = "" if aligned else " — ⚠ sem leitura KLD se manutenido"
                    choice = st.radio(
                        f"{_segment_role_label(seg_name)} ({seg_name}){warning}",
                        ("Nada", "Só curva", "Completa"),
                        horizontal=True,
                        key=f"manual_move_action_{seg_name}",
                    )
                    segment_choices[seg_name] = choice
                submitted_move = st.form_submit_button("Add move")
            if submitted_move:
                new_step = {
                    "mode": "move",
                    "segments": list(selected_option.segments),
                    "destination": selected_option.destination,
                    "segment_actions": {
                        seg_name: _ACTION_TOKENS[choice] for seg_name, choice in segment_choices.items()
                    },
                }
                new_plan = plan + [new_step]
                callbacks.update_manual_plan(new_plan)
                plan = new_plan
                callbacks.force_rerun()
```

Adicionar `Dict` ao import de `typing` no topo de `manual.py` se ainda não estiver lá (linha 7 já importa `Dict`, conferir).

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streamlit_app_ui.py -k add_move_form -v`
Expected: PASS.

- [ ] **Step 5: Rodar a suíte completa**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Checagem visual no app**

Run local: `.venv/Scripts/python.exe run_streamlit.py`, abrir Manual Route, adicionar um passo num trecho com Singela+pátio, conferir que aparecem 2 radios (Singela / Pátio) e o aviso "sem leitura KLD" quando aplicável.

- [ ] **Step 7: Commit**

```bash
git add src/railroad_frontend/views/manual.py tests/test_streamlit_app_ui.py
git commit -m "feat: formulario Add next step pede acao por segmento com aviso de leitura KLD"
```

---

### Task 7: Tabela de resultados ganha coluna "Leitura KLD"

**Files:**
- Modify: `src/railroad_frontend/views/manual.py:537-561`
- Test: `tests/test_streamlit_app_ui.py` (novo teste unitário de uma função helper extraída)

**Interfaces:**
- Consumes: `manual_result["steps"][i]["kld_reading"]` (produzido pela Task 1).
- Produces: `_kld_reading_label(step: Dict[str, Any]) -> str`, nova função módulo-nível em `manual.py`.

- [ ] **Step 1: Escrever o teste que falha**

Adicionar a `tests/test_streamlit_app_ui.py`:

```python
def test_kld_reading_label_summarizes_step() -> None:
    from railroad_frontend.views.manual import _kld_reading_label

    assert _kld_reading_label({"kld_reading": {}}) == "—"
    assert _kld_reading_label({"kld_reading": {"A-B": True}}) == "OK"
    assert _kld_reading_label({"kld_reading": {"A-B": True, "A-B-LD": False}}) == "⚠ sem leitura"
    assert _kld_reading_label({"kld_reading": {"A-B": False}}) == "⚠ sem leitura"
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streamlit_app_ui.py -k kld_reading_label -v`
Expected: FAIL — `ImportError: cannot import name '_kld_reading_label'`.

- [ ] **Step 3: Implementar `_kld_reading_label` e usar na tabela de resultados**

Em `src/railroad_frontend/views/manual.py`, adicionar perto de `_segment_actions_summary` (Task 4):

```python
def _kld_reading_label(step: Dict[str, Any]) -> str:
    kld_reading = step.get("kld_reading") or {}
    if not kld_reading:
        return "—"
    return "OK" if all(kld_reading.values()) else "⚠ sem leitura"
```

Em `render_manual_route_page`, trocar o bloco (linhas 547-549):

```python
        steps_df = pd.DataFrame(manual_result.get("steps", []))
        if not steps_df.empty:
            st.dataframe(steps_df, use_container_width=True)
```

por:

```python
        result_steps = manual_result.get("steps", [])
        steps_df = pd.DataFrame(result_steps)
        if not steps_df.empty:
            steps_df["Leitura KLD"] = [_kld_reading_label(s) for s in result_steps]
            st.dataframe(steps_df, use_container_width=True)
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streamlit_app_ui.py -k kld_reading_label -v`
Expected: PASS.

- [ ] **Step 5: Rodar a suíte completa**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/railroad_frontend/views/manual.py tests/test_streamlit_app_ui.py
git commit -m "feat: tabela de resultados do manual route mostra leitura de KLD por passo"
```

---

### Task 8: Migrar `data/saved_plans.json`

**Files:**
- Create: `scripts/migrate_plano_nos_segment_actions.py`
- Modify: `data/saved_plans.json` (gerado pelo script)
- Test: `tests/test_migrate_plano_nos_segment_actions.py`

**Interfaces:**
- Produces: `convert_step(step: Dict[str, Any]) -> Dict[str, Any]` (converte um passo `move` do formato antigo pro novo; passa `turn`/`wait` sem alteração) e `migrate(data: Dict[str, Any]) -> Dict[str, Any]` (aplica `convert_step` em `"Plano - Nós"`, remove `"Original"` e `"2026-Original"`), ambos em `scripts/migrate_plano_nos_segment_actions.py`, importáveis pelo teste.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_migrate_plano_nos_segment_actions.py`:

```python
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
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate_plano_nos_segment_actions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts'`.

- [ ] **Step 3: Implementar o script de migração**

Criar `scripts/__init__.py` vazio (pra virar pacote importável) e `scripts/migrate_plano_nos_segment_actions.py`:

```python
"""One-off migration: converte o plano salvo 'Plano - Nós' de action/
maintain_segments para segment_actions (Manual Route, 2026-08-07) e remove
os planos incompativeis com a rede atual ('Original', '2026-Original').

Uso: python scripts/migrate_plano_nos_segment_actions.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

PLANS_PATH = Path(__file__).resolve().parents[1] / "data" / "saved_plans.json"
KEEP_PLAN_NAME = "Plano - Nós"

_ACTION_TOKEN = {"maintain": "completa", "m": "completa", "maintain_curves": "curva"}


def convert_step(step: Dict[str, Any]) -> Dict[str, Any]:
    """Converte um passo do formato antigo (action/maintain_segments) pro
    novo (segment_actions). Passos turn/wait voltam inalterados."""
    if step.get("mode") != "move":
        return dict(step)

    segment_names = step.get("segments")
    if segment_names is None and "segment" in step:
        segment_names = [step["segment"]]
    segment_names = list(segment_names or [])

    action = step.get("action", "move")
    token = _ACTION_TOKEN.get(action, "none")
    maintain_segments = step.get("maintain_segments")

    if token == "none":
        segment_actions = {name: "none" for name in segment_names}
    elif maintain_segments is not None:
        segment_actions = {
            name: (token if name in maintain_segments else "none")
            for name in segment_names
        }
    else:
        segment_actions = {name: token for name in segment_names}

    new_step = {k: v for k, v in step.items() if k not in ("action", "maintain_segments")}
    new_step["segment_actions"] = segment_actions
    return new_step


def migrate(data: Dict[str, Any]) -> Dict[str, Any]:
    """Aplica convert_step só no plano compativel com a rede atual; descarta
    os demais planos manuais. A secao 'auto' nao e tocada."""
    manual = data.get("manual", {})
    kept = manual.get(KEEP_PLAN_NAME)
    new_manual = {}
    if kept is not None:
        new_manual[KEEP_PLAN_NAME] = [convert_step(step) for step in kept]
    return {"manual": new_manual, "auto": data.get("auto", {})}


def main() -> None:
    data = json.loads(PLANS_PATH.read_text(encoding="utf-8"))
    migrated = migrate(data)
    PLANS_PATH.write_text(json.dumps(migrated, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Migrado: {list(migrated['manual'].keys())}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate_plano_nos_segment_actions.py -v`
Expected: PASS.

- [ ] **Step 5: Rodar o script contra o arquivo real e validar o resultado**

Run: `.venv/Scripts/python.exe scripts/migrate_plano_nos_segment_actions.py`

Depois, validar manualmente que o plano migrado ainda reproduz a simulação da sessão de brainstorming (a mesma rota ZTO→...→ZTO): carregar `data/saved_plans.json["manual"]["Plano - Nós"]` e rodar via `replay_manual_plan` com `network_source=data/networks/network_20251223_115340.json`, conferir `result.errors == []`.

Run: `.venv/Scripts/python.exe -c "
import json
from pathlib import Path
from railroad_backend.services.manual_planner import ManualPlanConfig, replay_manual_plan

root = Path('.')
data = json.loads((root / 'data' / 'saved_plans.json').read_text(encoding='utf-8'))
plan = data['manual']['Plano - Nós']
csv_path = root / 'data' / 'mtbt_schedule.csv'  # confira o nome real do CSV de trafego usado no projeto
config = ManualPlanConfig(
    csv_path=csv_path, start_station='ZTO', facing_station='ZCZ',
    start_year=2026, end_year=2027, second_kld=True,
    network_source=root / 'data' / 'networks' / 'network_20251223_115340.json',
)
result = replay_manual_plan(config, plan)
print('errors:', result.errors)
"
```

Se o nome/caminho real do CSV de tráfego for diferente, ajuste antes de rodar (conferir com `ls data/*.csv` ou como o Streamlit app resolve `schedule_path` em `streamlit_app.py`).

Expected: `errors: []`.

- [ ] **Step 6: Rodar a suíte completa**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/__init__.py scripts/migrate_plano_nos_segment_actions.py tests/test_migrate_plano_nos_segment_actions.py data/saved_plans.json
git commit -m "chore: migra Plano - Nos para segment_actions e descarta planos salvos incompativeis"
```

---

### Task 9: CHANGELOG e verificação final

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Adicionar entrada no CHANGELOG**

Em `CHANGELOG.md`, dentro de `## [Unreleased]`, adicionar sob uma seção `### Added` (criar se não existir, logo antes de `### Fixed`):

```markdown
### Added
- Manual Route: cada passo "move" agora escolhe uma ação independente
  (Nada/Só curva/Completa) por segmento físico do trecho (Singela, Pátio
  Carregado-LP, Pátio Vazio-LD) em vez de uma única ação pro trecho
  inteiro — permite, por exemplo, curva só na Singela e manutenção
  completa no pátio no mesmo passo. Manutenção via `segment_actions`
  sempre executa e reseta o MTBT, mesmo desalinhada com o facing sem 2º
  KLD; o alinhamento vira uma flag informativa ("Leitura KLD") na tabela
  de resultados em vez de bloquear o serviço. Escopo só Manual Route — o
  Auto Planner não muda.
```

- [ ] **Step 2: Rodar a suíte completa uma última vez**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, sem nenhum teste pulado/falho.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: registra no changelog a acao independente por segmento no manual route"
```

---

## Depois de terminar

Registrar a sessão em `E:\Projetos\SecondBrain\projetos\simulador-esmerilhamento\decisoes.md` (arquivos tocados, testes finais, e se o plano migrado bateu com a simulação da rota real) e uma linha em `E:\Projetos\SecondBrain\log.md`, seguindo o padrão já usado nas entradas de 2026-08-07 anteriores desta mesma sessão.
