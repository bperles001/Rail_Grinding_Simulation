"""Greedy urgency-first Auto Planner strategy (the pre-existing default heuristic)."""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Dict, Tuple

from src.models import ACTION_MAINTAIN, ACTION_MAINTAIN_CURVES, ACTION_MOVE

from .base import AutoPlanStrategy, StepDecision

if TYPE_CHECKING:
    from ...domain.simulator import Simulator


def component_due(seg, component: str) -> bool:
    """True if a single component (curva or tangente) reached its threshold."""
    threshold = getattr(seg, f"mtbt_threshold_{component}", None)
    load = getattr(seg, f"load_{component}", 0.0) or 0.0
    if threshold is None:
        return False
    try:
        return float(load) >= float(threshold)
    except (TypeError, ValueError):  # pragma: no cover
        return False


def needs_maintenance(segments) -> bool:
    seq = (segments,) if not isinstance(segments, (tuple, list)) else segments
    return any(component_due(seg, "curva") or component_due(seg, "tangente") for seg in seq)


def maintenance_action_for(segments) -> str:
    seq = (segments,) if not isinstance(segments, (tuple, list)) else segments
    if any(component_due(seg, "tangente") for seg in seq):
        return ACTION_MAINTAIN
    return ACTION_MAINTAIN_CURVES


def segments_already_due(sim: "Simulator") -> bool:
    return any(needs_maintenance(seg) for seg in sim.segments)


def days_until_next_threshold(sim: "Simulator", *, scan_limit_days: int = 180) -> int:
    if not sim.daily_map or not sim.simulation_date:
        return 0
    projected: Dict[str, float] = {}
    thresholds: Dict[str, float] = {}
    component_seg_name: Dict[str, str] = {}
    for seg in sim.segments:
        for component, threshold, load in (
            (f"{seg.name}::curva", seg.mtbt_threshold_curva, seg.load_curva),
            (f"{seg.name}::tangente", seg.mtbt_threshold_tangente, seg.load_tangente),
        ):
            if threshold in (None, 0):
                continue
            thresholds[component] = float(threshold)
            projected[component] = float(load or 0.0)
            component_seg_name[component] = seg.name
    if not thresholds:
        return 0
    if segments_already_due(sim):
        return 0
    cached_daily_vals = {
        component: sim.daily_map.get(component_seg_name[component]) or {}
        for component in thresholds
    }
    current = sim.simulation_date
    for offset in range(1, scan_limit_days + 1):
        date_str = (current + timedelta(days=offset - 1)).strftime("%Y-%m-%d")
        progressed = False
        for component, threshold in thresholds.items():
            daily_values = cached_daily_vals[component]
            increment = daily_values.get(date_str)
            if increment:
                projected[component] = projected.get(component, 0.0) + float(increment)
                progressed = True
            if projected.get(component, 0.0) >= threshold:
                return offset
        if not progressed:
            if not any(daily_vals.get(date_str) for daily_vals in cached_daily_vals.values()):
                break
    return 0


def _move_priority(pair) -> Tuple[int, float, str]:
    segments, _ = pair
    urgent = 0 if needs_maintenance(segments) else 1
    load = max(
        max(
            float(getattr(seg, "load_curva", 0.0) or 0.0),
            float(getattr(seg, "load_tangente", 0.0) or 0.0),
        )
        for seg in segments
    )
    name = "+".join(seg.name for seg in segments)
    return (urgent, -load, name)


class GreedyUrgencyStrategy(AutoPlanStrategy):
    """Same heuristic the Auto Planner has always used: move to the most
    urgent (highest-load, already-due) segment; if nothing is due, wait
    until the next threshold is projected to hit."""

    def decide_next_action(self, sim: "Simulator") -> StepDecision:
        if segments_already_due(sim):
            options = sim.get_possible_moves()
            if not options:
                if sim.current_station and sim.current_station.can_turn:
                    return StepDecision(kind="turn")
                options = sim.get_all_moves_any_direction()
                if not options:
                    return StepDecision(kind="none")
            segments, next_station = sorted(options, key=_move_priority)[0]
            action = maintenance_action_for(segments) if needs_maintenance(segments) else ACTION_MOVE
            return StepDecision(kind="move", segments=segments, next_station=next_station, action=action)

        wait_days = days_until_next_threshold(sim)
        if wait_days <= 0:
            if sim.daily_map:
                wait_days = 1
            else:
                return StepDecision(kind="none")
        return StepDecision(kind="wait", wait_days=wait_days)


__all__ = ["GreedyUrgencyStrategy"]
