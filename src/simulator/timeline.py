"""Timeline data preparation for visualization."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.models import Segment


def _create_timeline_row(
    action: str,
    label: str,
    step: Dict[str, Any],
    segment_thresholds: Dict[str, Optional[float]],
) -> Optional[Dict[str, Any]]:
    """Create a timeline row dictionary for a given action.

    Args:
        action: Action type (move, maintenance, wait, turn).
        label: Segment or step label.
        step: Raw simulation step data.
        segment_thresholds: Map of segment names to MTBT thresholds.

    Returns:
        Timeline row dict, or None if action not recognized.
    """
    base_row = {
        "step": label,
        "start_time": step.get("start"),
        "end_time": step.get("end"),
        "mtbt_threshold": segment_thresholds.get(label, None),
    }

    if action in ("move", "maintenance"):
        base_row["status"] = "maintenance" if action == "maintenance" else "move"
        base_row["mtbt_before"] = step.get("mtbt_before", None)
        return base_row
    elif action == "wait":
        base_row["status"] = "wait"
        base_row["mtbt_before"] = None
        return base_row
    elif action == "turn":
        base_row["status"] = "turn"
        base_row["mtbt_before"] = None
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
    segment_thresholds: Dict[str, Any] = {}
    if segments:
        segment_thresholds = {
            _base_label(seg_obj.name): getattr(seg_obj, "mtbt_threshold", None)
            for seg_obj in segments
        }

    timeline_rows: List[Dict[str, Any]] = []
    last_step_label: Optional[str] = None
    for step in report_data:
        seg = step.get("segment", "")
        action = step.get("action", "move")
        if action in ("move", "maintenance"):
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
