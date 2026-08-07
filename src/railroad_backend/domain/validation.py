"""Common validation utilities for configuration and data structures."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


def validate_year_range(start_year: int, end_year: int) -> None:
    """Validate that years are in reasonable range and properly ordered.
    
    Args:
        start_year: Starting year.
        end_year: Ending year.
        
    Raises:
        TypeError: If years are not integers.
        ValueError: If years are out of range or improperly ordered.
    """
    if not isinstance(start_year, int):
        raise TypeError(f"start_year must be int, got {type(start_year).__name__}")
    if not isinstance(end_year, int):
        raise TypeError(f"end_year must be int, got {type(end_year).__name__}")
    if not (1900 <= start_year <= 2200):
        raise ValueError(f"start_year must be between 1900 and 2200, got {start_year}")
    if not (1900 <= end_year <= 2200):
        raise ValueError(f"end_year must be between 1900 and 2200, got {end_year}")
    if end_year < start_year:
        raise ValueError(f"end_year ({end_year}) cannot be before start_year ({start_year})")


def validate_station_name(name: str, field_label: str = "station") -> None:
    """Validate that a station name is non-empty string.
    
    Args:
        name: Station name to validate.
        field_label: Label for error messages (e.g., "start_station").
        
    Raises:
        TypeError: If name is not a string.
        ValueError: If name is empty or whitespace-only.
    """
    if not isinstance(name, str):
        raise TypeError(f"{field_label} must be str, got {type(name).__name__}")
    if not name.strip():
        raise ValueError(f"{field_label} cannot be empty or whitespace")


def validate_file_path(path: Path, must_exist: bool = True) -> None:
    """Validate that a path is valid and optionally exists.
    
    Args:
        path: Path to validate.
        must_exist: If True, verify path exists.
        
    Raises:
        TypeError: If path is not a Path object.
        ValueError: If path doesn't exist when must_exist=True.
    """
    if not isinstance(path, Path):
        raise TypeError(f"path must be Path, got {type(path).__name__}")
    if must_exist and not path.exists():
        raise ValueError(f"File not found: {path}")
    if must_exist and not path.is_file():
        raise ValueError(f"Path is not a file: {path}")


def validate_manual_plan_step(step: Dict[str, Any], step_idx: int) -> List[str]:
    """Validate a single manual plan step structure.
    
    Args:
        step: Plan step dictionary.
        step_idx: Step index for error messages (1-based).
        
    Returns:
        List of validation error messages (empty if valid).
    """
    errors: List[str] = []
    
    if not isinstance(step, dict):
        errors.append(f"Step {step_idx}: must be a dictionary, got {type(step).__name__}")
        return errors
    
    mode = step.get("mode")
    if mode not in ("move", "turn", "wait"):
        errors.append(f"Step {step_idx}: mode must be 'move', 'turn', or 'wait', got '{mode}'")
    
    if mode == "move":
        if "segment" not in step and "segments" not in step:
            errors.append(f"Step {step_idx}: 'move' mode requires a 'segment' or 'segments' field")
        if "destination" not in step:
            errors.append(f"Step {step_idx}: 'move' mode requires 'destination' field")
        if "action" not in step:
            errors.append(f"Step {step_idx}: 'move' mode requires 'action' field")
        elif step["action"] not in ("v", "m", "move", "maintain", "maintain_curves"):
            errors.append(f"Step {step_idx}: action must be 'move'/'v', 'maintain'/'m', or 'maintain_curves', got '{step['action']}'")
    
    elif mode == "wait":
        if "days" not in step:
            errors.append(f"Step {step_idx}: 'wait' mode requires 'days' field")
        else:
            days = step["days"]
            if not isinstance(days, int):
                errors.append(f"Step {step_idx}: days must be int, got {type(days).__name__}")
            elif days < 1:
                errors.append(f"Step {step_idx}: days must be at least 1, got {days}")
    
    # 'turn' mode has no additional required fields
    
    return errors


def validate_manual_plan(plan: List[Dict[str, Any]]) -> List[str]:
    """Validate entire manual plan structure.
    
    Args:
        plan: List of plan step dictionaries.
        
    Returns:
        List of validation error messages (empty if valid).
    """
    if not isinstance(plan, list):
        return [f"Plan must be a list, got {type(plan).__name__}"]
    
    all_errors: List[str] = []
    for idx, step in enumerate(plan, start=1):
        step_errors = validate_manual_plan_step(step, idx)
        all_errors.extend(step_errors)
    
    return all_errors


def validate_network_payload(payload: Dict[str, Any]) -> List[str]:
    """Validate network JSON payload structure.
    
    Args:
        payload: Network configuration dictionary.
        
    Returns:
        List of validation error messages (empty if valid).
    """
    errors: List[str] = []
    
    if not isinstance(payload, dict):
        return [f"Network payload must be dict, got {type(payload).__name__}"]
    
    # Check required top-level keys
    if "stations" not in payload:
        errors.append("Missing required key: 'stations'")
    elif not isinstance(payload["stations"], list):
        errors.append(f"'stations' must be a list, got {type(payload['stations']).__name__}")
    
    if "segments" not in payload:
        errors.append("Missing required key: 'segments'")
    elif not isinstance(payload["segments"], list):
        errors.append(f"'segments' must be a list, got {type(payload['segments']).__name__}")
    
    # Validate stations structure
    if "stations" in payload and isinstance(payload["stations"], list):
        for idx, station in enumerate(payload["stations"], start=1):
            if not isinstance(station, dict):
                errors.append(f"Station {idx}: must be dict, got {type(station).__name__}")
            elif "name" not in station:
                errors.append(f"Station {idx}: missing required 'name' field")
            elif not isinstance(station["name"], str) or not station["name"].strip():
                errors.append(f"Station {idx}: 'name' must be non-empty string")
    
    # Validate segments structure
    required_seg_fields = {"name", "start", "end", "length_km", "mtbt_threshold_curva", "mtbt_threshold_tangente", "move_time_days", "maintenance_time_days"}
    if "segments" in payload and isinstance(payload["segments"], list):
        for idx, segment in enumerate(payload["segments"], start=1):
            if not isinstance(segment, dict):
                errors.append(f"Segment {idx}: must be dict, got {type(segment).__name__}")
            else:
                missing = required_seg_fields - set(segment.keys())
                if missing:
                    errors.append(f"Segment {idx}: missing required fields: {', '.join(sorted(missing))}")
    
    return errors


__all__ = [
    "validate_year_range",
    "validate_station_name",
    "validate_file_path",
    "validate_manual_plan_step",
    "validate_manual_plan",
    "validate_network_payload",
]
