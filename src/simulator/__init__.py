"""Core simulator primitives consumed by the Streamlit dashboard."""

from __future__ import annotations

from pathlib import Path

# Re-export public API from submodules
from src.simulator.core import Simulator, DailyMap
from src.simulator.network_utils import build_network
from src.simulator.timeline import prepare_timeline_rows
from src.simulator.direction_model import _classify_edge_global_dir

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NETWORK_FILE = PROJECT_ROOT / "data" / "networks" / "default.json"


__all__ = ["Simulator", "build_network", "prepare_timeline_rows", "DEFAULT_NETWORK_FILE", "DailyMap", "_classify_edge_global_dir"]

