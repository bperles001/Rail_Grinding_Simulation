"""Projects which segments will need maintenance inside a rolling window."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from ...domain.simulator import Simulator


@dataclass(frozen=True)
class DueCandidate:
    segment_name: str
    station_name: str
    days_until_due: int
    service_days: int
    severity: float = 1.0


def _days_until_component_due(sim: "Simulator", seg, component: str, horizon_days: int) -> Optional[int]:
    threshold = getattr(seg, f"mtbt_threshold_{component}", None)
    if not threshold:
        return None
    load = float(getattr(seg, f"load_{component}", 0.0) or 0.0)
    if load >= float(threshold):
        return 0
    if not sim.daily_map or not sim.simulation_date:
        return None
    daily_values = sim.daily_map.get(seg.name) or {}
    projected = load
    current = sim.simulation_date
    for offset in range(1, horizon_days + 1):
        date_str = (current + timedelta(days=offset - 1)).strftime("%Y-%m-%d")
        increment = daily_values.get(date_str)
        if increment:
            projected += float(increment)
        if projected >= float(threshold):
            return offset
    return None


def _severity_if_due(seg, component: str) -> float:
    """How far past its threshold a component already is, as a ratio
    (1.0 = just crossed, 9.0 = loaded at 9x the threshold). Segments not yet
    due, or without a configured threshold, report the baseline 1.0 -- they
    carry no extra urgency signal beyond their projected days_until_due.
    """
    threshold = getattr(seg, f"mtbt_threshold_{component}", None)
    if not threshold:
        return 1.0
    load = float(getattr(seg, f"load_{component}", 0.0) or 0.0)
    if load < float(threshold):
        return 1.0
    return load / float(threshold)


def project_due_candidates(sim: "Simulator", horizon_days: int) -> List[DueCandidate]:
    candidates: List[DueCandidate] = []
    for seg in sim.segments:
        curva_days = _days_until_component_due(sim, seg, "curva", horizon_days)
        tangente_days = _days_until_component_due(sim, seg, "tangente", horizon_days)
        due_days = [d for d in (curva_days, tangente_days) if d is not None]
        if not due_days:
            continue
        severity = max(_severity_if_due(seg, "curva"), _severity_if_due(seg, "tangente"))
        candidates.append(
            DueCandidate(
                segment_name=seg.name,
                station_name=seg.end_station.name,
                days_until_due=min(due_days),
                service_days=max(1, int(seg.maintenance_time_days)),
                severity=severity,
            )
        )
    return candidates


__all__ = ["DueCandidate", "project_due_candidates"]
