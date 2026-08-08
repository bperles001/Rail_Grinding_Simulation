"""Plan storage helpers decoupled from Streamlit state."""
from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.railroad_backend.domain.persistence import (
    load_plan_storage as load_plan_storage_file,
    persist_plan_storage as persist_plan_storage_file,
)


def storage_defaults() -> Dict[str, Dict[str, Any]]:
    """Return empty storage structure with manual and auto sections.

    Returns:
        Dictionary with empty 'manual' and 'auto' keys.
    """
    return {"manual": {}, "auto": {}}


def load_plan_storage(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load plan storage from file with validation.

    Args:
        path: Path to storage JSON file.

    Returns:
        Dictionary with 'manual' and 'auto' sections, defaulting to empty dicts.
    """
    snapshot = load_plan_storage_file(path)
    if not snapshot:
        return storage_defaults()
    manual = snapshot.get("manual", {})
    auto = snapshot.get("auto", {})
    return {
        "manual": manual if isinstance(manual, dict) else {},
        "auto": auto if isinstance(auto, dict) else {},
    }


def persist_plan_storage(path: Path, snapshot: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
    """Persist plan storage snapshot to file.

    Args:
        path: Path to storage JSON file.
        snapshot: Storage data to write, or None for defaults.
    """
    data = snapshot if snapshot is not None else storage_defaults()
    path.parent.mkdir(parents=True, exist_ok=True)
    persist_plan_storage_file(path, data)


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


def persist_plan_sections(
    path: Path,
    manual_saved: Optional[Dict[str, Any]] = None,
    auto_saved: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist manual and auto plans to storage file.

    Args:
        path: Path to storage JSON file.
        manual_saved: Dictionary of manual plans to save.
        auto_saved: Dictionary of auto results to save.
    """
    snapshot = plan_storage_snapshot(manual_saved, auto_saved)
    persist_plan_storage(path, snapshot)


def clone_auto_result(data: Dict[str, Any]) -> Dict[str, Any]:
    """Deep copy auto planning result.

    Args:
        data: Auto planning result dictionary.

    Returns:
        Deep copy of the result.
    """
    return copy.deepcopy(data)


def save_auto_run_entry(
    saved_runs: Optional[Dict[str, Any]],
    name: str,
    auto_result: Dict[str, Any],
    *,
    saved_at: Optional[str] = None,
) -> Dict[str, Any]:
    new_runs = dict(saved_runs or {})
    new_runs[name] = {
        "config": dict(auto_result.get("config", {})),
        "result": clone_auto_result(auto_result),
        "saved_at": saved_at or datetime.utcnow().isoformat(timespec="seconds"),
    }
    return new_runs


def import_auto_run_payload(
    saved_runs: Optional[Dict[str, Any]],
    payload: Any,
) -> Tuple[Dict[str, Any], int]:
    if not isinstance(payload, dict):
        raise ValueError("Auto run file must contain a JSON object.")
    auto_section = payload.get("auto") if "auto" in payload else payload
    if not isinstance(auto_section, dict):
        raise ValueError("Auto run file must include an 'auto' object or be a mapping of run names.")
    new_runs = dict(saved_runs or {})
    imported = 0
    for name, entry in auto_section.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        config = entry.get("config")
        result = entry.get("result") or entry.get("result_snapshot")
        if not isinstance(config, dict) or not isinstance(result, dict):
            continue
        new_runs[name] = {
            "config": dict(config),
            "result": clone_auto_result(result),
            "saved_at": entry.get("saved_at") or datetime.utcnow().isoformat(timespec="seconds"),
        }
        imported += 1
    return new_runs, imported


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


__all__ = [
    "clone_auto_result",
    "import_auto_run_payload",
    "import_manual_plan_payload",
    "load_manual_plan",
    "load_plan_storage",
    "persist_plan_sections",
    "persist_plan_storage",
    "plan_storage_snapshot",
    "save_auto_run_entry",
    "save_manual_plan",
    "storage_defaults",
]
