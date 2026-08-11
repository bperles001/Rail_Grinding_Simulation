# Timeline por SB (par de estações) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Colapsar as linhas do timeline do simulador de uma por segmento físico (Singela/LP/LD, até 3 por corredor) para uma por SB (par de estações), codificando o ramal usado (Principal/Carregado x Desviada/Vazio) por cor e a extensão do serviço (só curva x completa) por letra no rótulo.

**Architecture:** Mudança concentrada em duas camadas existentes: `src/simulator/timeline.py` (converte `steps` do simulador em linhas de timeline — ganha a lógica de colapso de chave e cálculo de direção) e `src/utils/timeline_generator.py` (desenha as barras — ganha a paleta nova por `(status, direction)` e o rótulo combinado letra+número). Nenhuma mudança no motor (`src/simulator/core.py`) nem nos callers (`manual.py`/`auto_simulation.py`/`comparison.py`), que já passam dados por essas duas funções sem conhecer o formato interno.

**Tech Stack:** Python, pandas, matplotlib, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-10-timeline-por-sb-design.md`.
- SB = par de estações, obtido removendo o sufixo direcional `-LP`/`-LD`/`-C`/`-V` do nome do segmento mais específico do passo (`step["segment"]`).
- Cor por ramal só se aplica quando há manutenção (`status in ("maintenance", "maintenance_curves")`); usa `step["maintained_segments"]`, não `step["segments"]` (segmentos com token `none` não entram na decisão de cor).
- Direção: `"vazio"` se algum nome mantido termina em `-LD`/`-V`; senão `"carregado"` (default — cobre LP/C e Singela pura); `None` quando não há manutenção (inclui `move`).
- Paleta: Principal/Carregado `#3B82F6` · Desviada/Vazio `#22C55E` · Movimento `#F97316` · Espera `#F2C744` (inalterado) · Giro `#777777` (inalterado).
- Rótulo combinado: `f"{letra} {mtbt_before:.0f}"` — `"A"` para `maintenance`, `"C"` para `maintenance_curves`, sem letra quando não aplicável.
- Número de MTBT no rótulo continua sendo o "pior caso" (`_worst_case_mtbt`, já implementado) — não mexer nessa lógica.
- Fora de escopo: visualização de MTBT acumulado por trecho (ideia futura separada do Bruno); qualquer mudança em `core.py`, `manual.py`, `auto_simulation.py`, `comparison.py`.

---

### Task 1: Colapsar linhas por SB e calcular direção em `src/simulator/timeline.py`

**Files:**
- Modify: `src/simulator/timeline.py` (arquivo inteiro tem 147 linhas — ver conteúdo atual abaixo)
- Test: `tests/test_basic.py`

**Interfaces:**
- Consumes: nenhuma interface nova de fora — só os campos já existentes no step dict do simulador (`step["segment"]`, `step["segments"]`, `step["maintained_segments"]`, `step["action"]`, `step["mtbt_before_curva"]`, `step["mtbt_before_tangente"]`) e `Segment.mtbt_threshold_curva`/`mtbt_threshold_tangente`.
- Produces: `prepare_timeline_rows(report_data, segments=None, timeline_order=None) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, str]]` — mesma assinatura pública de hoje. Cada linha do primeiro elemento da tupla ganha uma chave nova `"direction"` (`"carregado"` | `"vazio"` | `None`). `row["step"]` agora é a chave SB (par de estações sem sufixo), não mais o nome bruto/joined do(s) segmento(s). `TimelineGenerator` (Task 2) consome `row["direction"]` e `row["status"]`.

Conteúdo atual completo de `src/simulator/timeline.py` (pra referência exata do diff):

```python
"""Timeline data preparation for visualization."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.models import Segment


def _ratio(before: Any, threshold: Any) -> Optional[float]:
    if isinstance(before, (int, float)) and isinstance(threshold, (int, float)) and threshold:
        return before / threshold
    return None


def _worst_case_mtbt(
    before_curva: Any, before_tangente: Any,
    threshold_curva: Optional[float], threshold_tangente: Optional[float],
) -> Tuple[Any, Optional[float]]:
    """Pick the curva/tangente pair with the higher load/threshold ratio --
    same "pior caso" rule already used to color the timeline bar (see
    decisoes.md 2026-08-06). Falls back to the raw max value when neither
    side has a usable threshold."""
    ratio_curva = _ratio(before_curva, threshold_curva)
    ratio_tangente = _ratio(before_tangente, threshold_tangente)
    if ratio_curva is None and ratio_tangente is None:
        candidates = [v for v in (before_curva, before_tangente) if isinstance(v, (int, float))]
        return (max(candidates), None) if candidates else (None, None)
    if ratio_tangente is None or (ratio_curva is not None and ratio_curva >= ratio_tangente):
        return before_curva, threshold_curva
    return before_tangente, threshold_tangente


def _create_timeline_row(
    action: str,
    label: str,
    step: Dict[str, Any],
    segment_thresholds: Dict[str, Tuple[Optional[float], Optional[float]]],
) -> Optional[Dict[str, Any]]:
    """Create a timeline row dictionary for a given action.

    Args:
        action: Action type (move, maintenance, wait, turn).
        label: Segment or step label.
        step: Raw simulation step data.
        segment_thresholds: Map of segment names to (threshold_curva, threshold_tangente).

    Returns:
        Timeline row dict, or None if action not recognized.
    """
    threshold_curva, threshold_tangente = segment_thresholds.get(label, (None, None))
    base_row = {
        "step": label,
        "start_time": step.get("start"),
        "end_time": step.get("end"),
    }

    if action in ("move", "maintenance", "maintenance_curves"):
        base_row["status"] = action
        mtbt_before, mtbt_threshold = _worst_case_mtbt(
            step.get("mtbt_before_curva"), step.get("mtbt_before_tangente"),
            threshold_curva, threshold_tangente,
        )
        base_row["mtbt_before"] = mtbt_before
        base_row["mtbt_threshold"] = mtbt_threshold
        return base_row
    elif action == "wait":
        base_row["status"] = "wait"
        base_row["mtbt_before"] = None
        base_row["mtbt_threshold"] = None
        return base_row
    elif action == "turn":
        base_row["status"] = "turn"
        base_row["mtbt_before"] = None
        base_row["mtbt_threshold"] = None
        return base_row
    return None


def prepare_timeline_rows(
    report_data: Sequence[Dict[str, Any]],
    segments: Optional[Sequence[Segment]] = None,
    timeline_order: Optional[Sequence[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, str]]:
    """Convert simulator report data into timeline rows, order, and aliases.

    Args:
        report_data: Sequence of step dictionaries from simulator.
        segments: Optional segment objects to extract MTBT thresholds.

    Returns:
        Tuple of (timeline_rows, y_order, alias_map) for visualization.
    """

    def _base_label(seg_name: str) -> str:
        return seg_name

    # Cache segment thresholds once to avoid repeated getattr calls
    segment_thresholds: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    if segments:
        segment_thresholds = {
            _base_label(seg_obj.name): (
                getattr(seg_obj, "mtbt_threshold_curva", None),
                getattr(seg_obj, "mtbt_threshold_tangente", None),
            )
            for seg_obj in segments
        }

    timeline_rows: List[Dict[str, Any]] = []
    last_step_label: Optional[str] = None
    for step in report_data:
        step_segments = step.get("segments") or ([step["segment"]] if step.get("segment") else [])
        seg = " + ".join(step_segments) if step_segments else step.get("segment", "")
        action = step.get("action", "move")
        if action in ("move", "maintenance", "maintenance_curves"):
            label = _base_label(seg)
            last_step_label = label
            row = _create_timeline_row(action, label, step, segment_thresholds)
            if row:
                timeline_rows.append(row)
        elif action == "wait":
            label = _base_label(seg or last_step_label or "Idle")
            last_step_label = label
            row = _create_timeline_row(action, label, step, segment_thresholds)
            if row:
                timeline_rows.append(row)
        elif action == "turn" and last_step_label:
            row = _create_timeline_row(action, last_step_label, step, segment_thresholds)
            if row:
                timeline_rows.append(row)

    # Build y_order: prefer explicit timeline_order, fall back to segment list order
    y_order: List[str] = []
    if timeline_order:
        all_labels = {row["step"] for row in timeline_rows}
        seg_names = [_base_label(seg) for seg in segments] if segments else []
        ordered = [name for name in timeline_order if name in all_labels or name in seg_names]
        extras = [name for name in seg_names if name not in ordered]
        y_order = ordered + extras
    elif segments:
        y_order = [_base_label(seg) for seg in segments]
    alias_map: Dict[str, str] = {}
    return timeline_rows, y_order, alias_map


__all__ = ["prepare_timeline_rows"]
```

- [ ] **Step 1: Write the failing tests**

Adicionar em `tests/test_basic.py`, substituindo o teste existente
`test_prepare_timeline_rows_labels_corridor_step_with_both_segments` (que
hoje espera o nome joined `"A-B + A-B-LD"` — vira obsoleto com o colapso
por SB) e acrescentando os testes novos de direção/dedupe:

```python
def test_prepare_timeline_rows_collapses_corridor_step_to_sb_key():
    """Regressao do redesenho: a linha de um passo com Singela+ramal (ex.
    segments=["A-B", "A-B-LD"]) deve ser rotulada pelo par de estacoes (SB),
    nao mais pelo nome joined dos segmentos -- e' isso que colapsa Singela/
    LP/LD numa linha so no timeline."""
    report = [{
        "segment": "A-B-LD", "segments": ["A-B", "A-B-LD"], "action": "move",
        "maintained_segments": [],
        "mtbt_before_curva": 1.0, "mtbt_before_tangente": 1.0,
        "start": "2026-01-01", "end": "2026-01-04",
    }]
    rows, _y_order, _alias = prepare_timeline_rows(report, segments=None, timeline_order=None)
    assert rows[0]["step"] == "A-B"


def test_prepare_timeline_rows_direction_vazio_when_ld_maintained():
    report = [{
        "segment": "A-B-LD", "segments": ["A-B", "A-B-LD"], "action": "maintenance",
        "maintained_segments": ["A-B", "A-B-LD"],
        "mtbt_before_curva": 1.0, "mtbt_before_tangente": 1.0,
        "start": "2026-01-01", "end": "2026-01-04",
    }]
    rows, _y_order, _alias = prepare_timeline_rows(report, segments=None, timeline_order=None)
    assert rows[0]["direction"] == "vazio"


def test_prepare_timeline_rows_direction_carregado_when_only_singela_maintained():
    report = [{
        "segment": "A-B", "segments": ["A-B"], "action": "maintenance",
        "maintained_segments": ["A-B"],
        "mtbt_before_curva": 1.0, "mtbt_before_tangente": 1.0,
        "start": "2026-01-01", "end": "2026-01-02",
    }]
    rows, _y_order, _alias = prepare_timeline_rows(report, segments=None, timeline_order=None)
    assert rows[0]["direction"] == "carregado"


def test_prepare_timeline_rows_direction_carregado_when_lp_maintained():
    report = [{
        "segment": "A-B-LP", "segments": ["A-B", "A-B-LP"], "action": "maintenance_curves",
        "maintained_segments": ["A-B-LP"],
        "mtbt_before_curva": 1.0, "mtbt_before_tangente": 1.0,
        "start": "2026-01-01", "end": "2026-01-02",
    }]
    rows, _y_order, _alias = prepare_timeline_rows(report, segments=None, timeline_order=None)
    assert rows[0]["direction"] == "carregado"


def test_prepare_timeline_rows_direction_none_when_no_maintenance():
    report = [{
        "segment": "A-B-LD", "segments": ["A-B", "A-B-LD"], "action": "move",
        "maintained_segments": [],
        "mtbt_before_curva": 1.0, "mtbt_before_tangente": 1.0,
        "start": "2026-01-01", "end": "2026-01-04",
    }]
    rows, _y_order, _alias = prepare_timeline_rows(report, segments=None, timeline_order=None)
    assert rows[0]["direction"] is None


def test_prepare_timeline_rows_y_order_dedupes_by_sb_key():
    """timeline_order/segments podem trazer "A-B", "A-B-LP", "A-B-LD" como
    3 entradas -- o y_order final deve ter "A-B" uma vez so, na posicao da
    primeira ocorrencia."""
    sta_a = Station("A")
    sta_b = Station("B")
    seg_singela = Segment("A-B", sta_a, sta_b)
    seg_lp = Segment("A-B-LP", sta_b, sta_a)
    seg_ld = Segment("A-B-LD", sta_a, sta_b)
    rows, y_order, _alias = prepare_timeline_rows(
        [], segments=[seg_singela, seg_lp, seg_ld], timeline_order=None,
    )
    assert y_order == ["A-B"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_basic.py -k "prepare_timeline_rows" -v`
Expected: `test_prepare_timeline_rows_collapses_corridor_step_to_sb_key`,
`test_prepare_timeline_rows_direction_vazio_when_ld_maintained`,
`test_prepare_timeline_rows_direction_carregado_when_only_singela_maintained`,
`test_prepare_timeline_rows_direction_carregado_when_lp_maintained`,
`test_prepare_timeline_rows_direction_none_when_no_maintenance` e
`test_prepare_timeline_rows_y_order_dedupes_by_sb_key` FALHAM (`KeyError:
'direction'` ou `AssertionError` no `step`/`y_order`). O teste antigo
`test_prepare_timeline_rows_labels_corridor_step_with_both_segments` já
deve ter sido removido/substituído neste mesmo passo — se ainda existir,
apague-o agora (ele encapsula o comportamento antigo que este plano
substitui).

- [ ] **Step 3: Implementar `_sb_key`, `_direction_role`, `_dedupe_sb_keys` e integrar em `prepare_timeline_rows`/`_create_timeline_row`**

Substituir o conteúdo de `src/simulator/timeline.py` por:

```python
"""Timeline data preparation for visualization."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.models import Segment

_DIRECTIONAL_SUFFIXES = ("-LP", "-LD", "-C", "-V")


def _sb_key(segment_name: str) -> str:
    """Estacao-par (SB) de um segmento: remove o sufixo direcional final
    (-LP/-LD/-C/-V), se houver. Singela/LP/LD do mesmo corredor sempre
    compartilham o mesmo par-base, entao isso colapsa as 3 linhas de hoje
    numa so por SB."""
    for suffix in _DIRECTIONAL_SUFFIXES:
        if segment_name.endswith(suffix):
            return segment_name[: -len(suffix)]
    return segment_name


def _dedupe_sb_keys(names: Iterable[str]) -> List[str]:
    seen: set = set()
    result: List[str] = []
    for name in names:
        key = _sb_key(name)
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _direction_role(maintained_names: Sequence[str]) -> Optional[str]:
    """"vazio" se algum segmento mantido no passo e' Desviada (-LD/-V);
    "carregado" se algo foi mantido mas nao e' Desviada (cobre -LP/-C e
    Singela pura, sem sufixo); None se nao houve manutencao nesse passo."""
    if not maintained_names:
        return None
    if any(name.endswith(("-LD", "-V")) for name in maintained_names):
        return "vazio"
    return "carregado"


def _ratio(before: Any, threshold: Any) -> Optional[float]:
    if isinstance(before, (int, float)) and isinstance(threshold, (int, float)) and threshold:
        return before / threshold
    return None


def _worst_case_mtbt(
    before_curva: Any, before_tangente: Any,
    threshold_curva: Optional[float], threshold_tangente: Optional[float],
) -> Tuple[Any, Optional[float]]:
    """Pick the curva/tangente pair with the higher load/threshold ratio --
    same "pior caso" rule already used to color the timeline bar (see
    decisoes.md 2026-08-06). Falls back to the raw max value when neither
    side has a usable threshold."""
    ratio_curva = _ratio(before_curva, threshold_curva)
    ratio_tangente = _ratio(before_tangente, threshold_tangente)
    if ratio_curva is None and ratio_tangente is None:
        candidates = [v for v in (before_curva, before_tangente) if isinstance(v, (int, float))]
        return (max(candidates), None) if candidates else (None, None)
    if ratio_tangente is None or (ratio_curva is not None and ratio_curva >= ratio_tangente):
        return before_curva, threshold_curva
    return before_tangente, threshold_tangente


def _create_timeline_row(
    action: str,
    label: str,
    step: Dict[str, Any],
    segment_thresholds: Dict[str, Tuple[Optional[float], Optional[float]]],
    direction: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Create a timeline row dictionary for a given action.

    Args:
        action: Action type (move, maintenance, maintenance_curves, wait, turn).
        label: SB (station-pair) label for this row.
        step: Raw simulation step data.
        segment_thresholds: Map of SB keys to (threshold_curva, threshold_tangente).
        direction: "carregado" | "vazio" | None -- which leg carried the
            maintenance in this step, for bar coloring (Task 2).

    Returns:
        Timeline row dict, or None if action not recognized.
    """
    threshold_curva, threshold_tangente = segment_thresholds.get(label, (None, None))
    base_row = {
        "step": label,
        "start_time": step.get("start"),
        "end_time": step.get("end"),
        "direction": direction,
    }

    if action in ("move", "maintenance", "maintenance_curves"):
        base_row["status"] = action
        mtbt_before, mtbt_threshold = _worst_case_mtbt(
            step.get("mtbt_before_curva"), step.get("mtbt_before_tangente"),
            threshold_curva, threshold_tangente,
        )
        base_row["mtbt_before"] = mtbt_before
        base_row["mtbt_threshold"] = mtbt_threshold
        return base_row
    elif action == "wait":
        base_row["status"] = "wait"
        base_row["mtbt_before"] = None
        base_row["mtbt_threshold"] = None
        return base_row
    elif action == "turn":
        base_row["status"] = "turn"
        base_row["mtbt_before"] = None
        base_row["mtbt_threshold"] = None
        return base_row
    return None


def prepare_timeline_rows(
    report_data: Sequence[Dict[str, Any]],
    segments: Optional[Sequence[Segment]] = None,
    timeline_order: Optional[Sequence[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, str]]:
    """Convert simulator report data into timeline rows, order, and aliases.

    Args:
        report_data: Sequence of step dictionaries from simulator.
        segments: Optional segment objects to extract MTBT thresholds.

    Returns:
        Tuple of (timeline_rows, y_order, alias_map) for visualization.
    """

    # Cache segment thresholds once to avoid repeated getattr calls.
    # Keyed by SB (station-pair): Singela/LP/LD of the same corridor share
    # the same base pair, so the last one processed wins -- acceptable
    # because in practice the 3 legs of a corridor carry the same
    # curva/tangente thresholds (see spec, item 1 of "Mudanças por camada").
    segment_thresholds: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    if segments:
        for seg_obj in segments:
            key = _sb_key(seg_obj.name)
            segment_thresholds[key] = (
                getattr(seg_obj, "mtbt_threshold_curva", None),
                getattr(seg_obj, "mtbt_threshold_tangente", None),
            )

    timeline_rows: List[Dict[str, Any]] = []
    last_step_label: Optional[str] = None
    for step in report_data:
        action = step.get("action", "move")
        if action in ("move", "maintenance", "maintenance_curves"):
            label = _sb_key(step.get("segment", ""))
            last_step_label = label
            direction = _direction_role(step.get("maintained_segments") or [])
            row = _create_timeline_row(action, label, step, segment_thresholds, direction)
            if row:
                timeline_rows.append(row)
        elif action == "wait":
            step_segments = step.get("segments") or ([step["segment"]] if step.get("segment") else [])
            seg = " + ".join(step_segments) if step_segments else step.get("segment", "")
            label = _sb_key(seg or last_step_label or "Idle")
            last_step_label = label
            row = _create_timeline_row(action, label, step, segment_thresholds, None)
            if row:
                timeline_rows.append(row)
        elif action == "turn" and last_step_label:
            row = _create_timeline_row(action, last_step_label, step, segment_thresholds, None)
            if row:
                timeline_rows.append(row)

    # Build y_order: prefer explicit timeline_order, fall back to segment list order
    y_order: List[str] = []
    if timeline_order:
        ordered_keys = _dedupe_sb_keys(timeline_order)
        all_labels = {row["step"] for row in timeline_rows}
        seg_keys = _dedupe_sb_keys(seg.name for seg in segments) if segments else []
        ordered = [name for name in ordered_keys if name in all_labels or name in seg_keys]
        extras = [name for name in seg_keys if name not in ordered]
        y_order = ordered + extras
    elif segments:
        y_order = _dedupe_sb_keys(seg.name for seg in segments)
    alias_map: Dict[str, str] = {}
    return timeline_rows, y_order, alias_map


__all__ = ["prepare_timeline_rows"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_basic.py -v`
Expected: PASS — todos os testes de `prepare_timeline_rows`/`TimelineGenerator`
em `test_basic.py`, incluindo os 6 novos/atualizados deste passo e os que já
existiam (`test_prepare_timeline_rows_and_generator`,
`test_prepare_timeline_rows_reports_worst_case_curva_tangente_mtbt`,
`test_timeline_generator_returns_structured_plot`).

- [ ] **Step 5: Rodar a suíte completa (regressão)**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: todos os testes passam (nenhuma regressão em `test_edge_cases.py`,
`test_integration.py`, etc. — nada nesses arquivos depende do formato de
linha do timeline).

- [ ] **Step 6: Commit**

```bash
git add src/simulator/timeline.py tests/test_basic.py
git commit -m "feat: colapsa timeline por SB (par de estacoes) e calcula direcao carregado/vazio"
```

---

### Task 2: Cor por direção e rótulo letra+número em `src/utils/timeline_generator.py`

**Files:**
- Modify: `src/utils/timeline_generator.py:200-211` (métodos `_should_add_label`/`_get_label_color`), `:309-321` (bloco de cor dentro de `create_timeline_plot`), `:565-577` (legenda em `customize_plot`)
- Test: `tests/test_basic.py`

**Interfaces:**
- Consumes: `row["status"]` (`move`/`maintenance`/`maintenance_curves`/`wait`/`turn`) e `row["direction"]` (`"carregado"`/`"vazio"`/`None`), ambos produzidos pela Task 1 em `prepare_timeline_rows`. `TimelineGenerator.__init__`/`process_data` não mudam de assinatura.
- Produces: nenhuma interface nova pra fora — `create_timeline_plot()` continua devolvendo `TimelinePlot(dataframe, figure, axes)` como hoje. Os testes desta task inspecionam o `Axes` devolvido (cor das barras via `ax.patches`, texto dos rótulos via `ax.texts`).

- [ ] **Step 1: Write the failing tests**

Adicionar em `tests/test_basic.py`:

```python
def test_timeline_generator_colors_maintenance_by_direction():
    rows = [
        {
            "step": "A-B", "start_time": "2026-01-01", "end_time": "2026-01-02",
            "status": "maintenance", "direction": "carregado",
            "mtbt_before": 8.0, "mtbt_threshold": 100.0,
        },
        {
            "step": "C-D", "start_time": "2026-01-02", "end_time": "2026-01-03",
            "status": "maintenance", "direction": "vazio",
            "mtbt_before": 5.0, "mtbt_threshold": 100.0,
        },
    ]
    generator = TimelineGenerator(rows, y_order=["A-B", "C-D"])
    generator.process_data()
    plot = generator.create_timeline_plot()
    colors = sorted(patch.get_facecolor() for patch in plot.axes.patches)
    import matplotlib.colors as mcolors
    expected = sorted([
        mcolors.to_rgba('#3B82F6', alpha=0.8),
        mcolors.to_rgba('#22C55E', alpha=0.8),
    ])
    assert colors == expected


def test_timeline_generator_colors_move_and_turn_and_wait():
    rows = [
        {
            "step": "A-B", "start_time": "2026-01-01", "end_time": "2026-01-02",
            "status": "move", "direction": None, "mtbt_before": None, "mtbt_threshold": None,
        },
        {
            "step": "A-B", "start_time": "2026-01-02", "end_time": "2026-01-03",
            "status": "wait", "direction": None, "mtbt_before": None, "mtbt_threshold": None,
        },
        {
            "step": "A-B", "start_time": "2026-01-03", "end_time": "2026-01-04",
            "status": "turn", "direction": None, "mtbt_before": None, "mtbt_threshold": None,
        },
    ]
    generator = TimelineGenerator(rows, y_order=["A-B"])
    generator.process_data()
    plot = generator.create_timeline_plot()
    import matplotlib.colors as mcolors
    colors = sorted(patch.get_facecolor() for patch in plot.axes.patches)
    expected = sorted([
        mcolors.to_rgba('#F97316', alpha=0.8),
        mcolors.to_rgba('#F2C744', alpha=0.8),
        mcolors.to_rgba('#777777', alpha=0.8),
    ])
    assert colors == expected


def test_timeline_generator_label_combines_letter_and_mtbt():
    rows = [
        {
            "step": "A-B", "start_time": "2026-01-01", "end_time": "2026-01-02",
            "status": "maintenance", "direction": "carregado",
            "mtbt_before": 8.0, "mtbt_threshold": 100.0,
        },
        {
            "step": "C-D", "start_time": "2026-01-01", "end_time": "2026-01-02",
            "status": "maintenance_curves", "direction": "carregado",
            "mtbt_before": 5.0, "mtbt_threshold": 100.0,
        },
    ]
    generator = TimelineGenerator(rows, y_order=["A-B", "C-D"])
    generator.process_data()
    plot = generator.create_timeline_plot()
    texts = {t.get_text() for t in plot.axes.texts}
    assert "A 8" in texts
    assert "C 5" in texts
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_basic.py -k "timeline_generator_colors or timeline_generator_label" -v`
Expected: FAIL — `test_timeline_generator_colors_maintenance_by_direction` falha
porque hoje as duas barras `maintenance` saem com a mesma cor
(`#4EA24E`) independente de `direction`; `test_timeline_generator_colors_move_and_turn_and_wait`
falha porque `move` hoje é azul (`#81C3FF`), não laranja;
`test_timeline_generator_label_combines_letter_and_mtbt` falha porque o
rótulo hoje é só o número (`"8"`/`"5"`), sem a letra.

- [ ] **Step 3: Implementar a paleta por `(status, direction)` e o rótulo combinado**

Em `src/utils/timeline_generator.py`, adicionar constante de classe logo
após a declaração de `TimelineGenerator` (antes de `__init__`, por volta da
linha 27-28):

```python
class TimelineGenerator:
    _STATUS_LETTERS = {"maintenance": "A", "maintenance_curves": "C"}

    def __init__(
```

Substituir `_should_add_label` (linhas 192-198) por:

```python
    def _should_add_label(self, status: str, mtbt_before: Any) -> Tuple[bool, Optional[str]]:
        """Determine if label should be added and what text to use."""
        if status == 'turn':
            return True, 'turn'
        elif isinstance(mtbt_before, (int, float)) and not pd.isna(mtbt_before):
            letter = self._STATUS_LETTERS.get(status)
            text = f"{letter} {mtbt_before:.0f}" if letter else f"{mtbt_before:.0f}"
            return True, text
        return False, None
```

Substituir o bloco de atribuição de cor dentro de `create_timeline_plot`
(linhas 309-321 do arquivo atual) por:

```python
            # Assign color based on status + direction (carregado/vazio)
            direction = row.get('direction')
            if status == 'turn':
                color = '#777777'  # gray for turns
            elif status == 'wait':
                color = '#F2C744'  # yellow for idle periods
            elif status == 'move':
                color = '#F97316'  # orange for pure movement
            elif status in ('maintenance', 'maintenance_curves'):
                color = '#22C55E' if direction == 'vazio' else '#3B82F6'  # green=Desviada, blue=Principal (default)
            else:
                color = '#888888'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_basic.py -v`
Expected: PASS — todos os testes de `test_basic.py`, incluindo os 3 novos
deste passo.

- [ ] **Step 5: Atualizar a legenda em `customize_plot`**

Substituir o bloco de legenda (linhas 565-577 do arquivo atual):

```python
        # Dynamic legend for statuses present (outside the plot area on the right)
        present = set(df['status'].unique().tolist())
        handles = []
        if 'move' in present:
            handles.append(mpatches.Patch(color='#333399', label='Move'))
        if 'maintenance' in present:
            handles.append(mpatches.Patch(color='#4EA24E', label='Maintenance'))
        if 'maintenance_curves' in present:
            handles.append(mpatches.Patch(color='#9B59B6', label='Maintenance (curves)'))
        if 'turn' in present:
            handles.append(mpatches.Patch(color='#777777', label='Turn'))
        if handles:
            self.ax.legend(handles=handles, loc='upper left', bbox_to_anchor=(1.02, 1.0), frameon=True, borderaxespad=0.0)
```

por:

```python
        # Dynamic legend for statuses+directions present (outside the plot area on the right)
        maintenance_mask = df['status'].isin(['maintenance', 'maintenance_curves'])
        has_carregado = bool((maintenance_mask & (df['direction'] != 'vazio')).any())
        has_vazio = bool((maintenance_mask & (df['direction'] == 'vazio')).any())
        present = set(df['status'].unique().tolist())
        handles = []
        if has_carregado:
            handles.append(mpatches.Patch(color='#3B82F6', label='Manutenção Principal/Carregado'))
        if has_vazio:
            handles.append(mpatches.Patch(color='#22C55E', label='Manutenção Desviada/Vazio'))
        if 'move' in present:
            handles.append(mpatches.Patch(color='#F97316', label='Movimento'))
        if 'wait' in present:
            handles.append(mpatches.Patch(color='#F2C744', label='Espera'))
        if 'turn' in present:
            handles.append(mpatches.Patch(color='#777777', label='Giro'))
        if has_carregado or has_vazio:
            handles.append(mpatches.Patch(facecolor='none', edgecolor='none', label='C = só curva · A = completa'))
        if handles:
            self.ax.legend(handles=handles, loc='upper left', bbox_to_anchor=(1.02, 1.0), frameon=True, borderaxespad=0.0)
```

- [ ] **Step 6: Write a test for the updated legend**

Adicionar em `tests/test_basic.py`:

```python
def test_timeline_generator_legend_shows_direction_and_letter_note():
    rows = [{
        "step": "A-B", "start_time": "2026-01-01", "end_time": "2026-01-02",
        "status": "maintenance", "direction": "vazio",
        "mtbt_before": 8.0, "mtbt_threshold": 100.0,
    }]
    generator = TimelineGenerator(rows, y_order=["A-B"])
    generator.process_data()
    plot = generator.create_timeline_plot()
    legend = plot.axes.get_legend()
    labels = {t.get_text() for t in legend.get_texts()}
    assert 'Manutenção Desviada/Vazio' in labels
    assert 'C = só curva · A = completa' in labels
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_basic.py -v`
Expected: PASS — incluindo `test_timeline_generator_legend_shows_direction_and_letter_note`.

- [ ] **Step 8: Rodar a suíte completa (regressão)**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: todos os testes passam.

- [ ] **Step 9: Commit**

```bash
git add src/utils/timeline_generator.py tests/test_basic.py
git commit -m "feat: timeline colore manutencao por Principal/Desviada e junta letra curva/completa no rotulo"
```

---

### Task 3: Verificação manual no app rodando

**Files:** nenhum arquivo tocado — só verificação.

**Interfaces:** N/A.

- [ ] **Step 1: Matar o processo Streamlit atual e subir de novo limpo pelo `.venv` do projeto**

(Mesmo procedimento das duas sessões anteriores — garante que o processo
não é uma instância antiga via `uv` nem tem cache de replay obsoleto em
`st.session_state`.)

```bash
# achar o processo na porta 8501 e matar
# subir de novo:
.venv/Scripts/python.exe run_streamlit.py
```

- [ ] **Step 2: Health check**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8501/_stcore/health`
Expected: `200`

- [ ] **Step 3: Carregar o plano salvo real e conferir visualmente**

No Manual Route, carregar `"Plano - Nós (v2 segment_actions)"` e conferir:
- Uma linha por SB (ex. `ZTO-ZCZ`), não mais 2-3 linhas por corredor.
- Barras de manutenção azuis (Principal, maioria do plano) e verdes nos
  passos onde só a Desviada foi mantida (passos 35-39, editados na sessão
  anterior pra "curva").
- Rótulo `"A <número>"` na maioria das barras de manutenção (tokens
  "completa") e `"C <número>"` nos passos 35-39 (curva).
- Legenda com as 5 entradas novas + nota "C = só curva · A = completa".
- Nenhum erro no app (`preview_errors` vazio, como já validado nas sessões
  anteriores).

Isso é confirmação visual — não há assert automatizado aqui, é o Bruno (ou
quem executar) olhando o app de verdade, como pedido ("vamos trabalhar e
de fato ver como vai ficar").
