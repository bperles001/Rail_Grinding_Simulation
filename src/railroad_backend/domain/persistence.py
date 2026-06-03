"""File-based helpers for plan storage and related persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

PlanSnapshot = Dict[str, Dict[str, Any]]
_PLAN_STORAGE_DEFAULT: PlanSnapshot = {"manual": {}, "auto": {}}


def _fresh_snapshot() -> PlanSnapshot:
    return {"manual": {}, "auto": {}}


def load_plan_storage(path: Path) -> PlanSnapshot:
    """Load manual/auto plan snapshots from disk, falling back to defaults."""
    if not path.exists():
        return _fresh_snapshot()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _fresh_snapshot()
    if not isinstance(raw, dict):
        return _fresh_snapshot()
    manual = raw.get("manual", {})
    auto = raw.get("auto", {})
    return {
        "manual": manual if isinstance(manual, dict) else {},
        "auto": auto if isinstance(auto, dict) else {},
    }


def persist_plan_storage(path: Path, snapshot: PlanSnapshot) -> None:
    """Write the provided plan snapshot to disk using UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = snapshot if isinstance(snapshot, dict) else _fresh_snapshot()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
