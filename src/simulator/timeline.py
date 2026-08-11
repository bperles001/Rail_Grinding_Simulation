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
            maintenance in this step, for bar coloring.

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
    # curva/tangente thresholds.
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
        elif action == "turn":
            # Normally reuses the last SB visited. If the plan turns
            # before ever moving (machine starts at a can_turn station),
            # last_step_label is still None -- fall back to the turn's
            # own station name instead of silently dropping the row
            # (found via the 2026-08-11 fuzz campaign: an all-turn plan
            # produced zero timeline rows, which crashed
            # TimelineGenerator.process_data() on an empty DataFrame).
            label = last_step_label or _sb_key(step.get("segment", "")) or "Idle"
            last_step_label = label
            row = _create_timeline_row(action, label, step, segment_thresholds, None)
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
