"""Direction model for segment-based movement classification."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.models import Segment
from src.utils.network_loader import load_network

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NETWORK_FILE = PROJECT_ROOT / "data" / "networks" / "default.json"


class DirectionModel:
    """Encapsulate segment-based direction classification.
    
    Direction is determined by the segment's allowed_movements:
    - If movement A->B exists but B->A doesn't: A->B is the primary direction
    - If both A->B and B->A exist: Bidirectional (both CARREGADO and VAZIO allowed)
    - Classification is based on which movements are physically allowed
    """

    def __init__(self, segments: List[Segment]) -> None:
        """Initialize direction model from segments.
        
        Args:
            segments: List of network segments with allowed_movements
        """
        # Build lookup: (source, dest) -> segment
        self.movement_to_segment: Dict[Tuple[str, str], Segment] = {}
        for segment in segments:
            for src, dst in segment.allowed_movements:
                self.movement_to_segment[(src, dst)] = segment
    
    def classify(self, a_name: str, b_name: str) -> Optional[str]:
        """Return "CARREGADO" or "VAZIO" based on segment movement rules.
        
        Logic:
        - Find the segment that allows this movement
        - If segment Start->End matches a->b: CARREGADO
        - If segment End->Start matches a->b: VAZIO  
        - If bidirectional: return CARREGADO (default/primary)
        - If no segment allows this movement: None
        
        Args:
            a_name: Source station name
            b_name: Destination station name
            
        Returns:
            "CARREGADO", "VAZIO", or None if movement not allowed
        """
        # Check if this movement is allowed
        segment = self.movement_to_segment.get((a_name, b_name))
        if not segment:
            return None
        
        # Determine direction based on segment orientation
        # Primary direction (Start->End) is CARREGADO
        # Reverse direction (End->Start) is VAZIO
        if segment.start_station.name == a_name and segment.end_station.name == b_name:
            return "CARREGADO"
        elif segment.end_station.name == a_name and segment.start_station.name == b_name:
            return "VAZIO"
        else:
            # Shouldn't happen, but default to CARREGADO
            return "CARREGADO"


def _direction_model_from_segments(segments: List[Segment]) -> DirectionModel:
    """Build a DirectionModel from network segments.
    
    Args:
        segments: List of network segments
        
    Returns:
        DirectionModel instance
    """
    return DirectionModel(segments)


# Default direction model for legacy compatibility
_DEFAULT_CONFIG = load_network(DEFAULT_NETWORK_FILE)
_DEFAULT_DIRECTION_MODEL = DirectionModel(_DEFAULT_CONFIG.segments)


def _classify_edge_global_dir(a_name: str, b_name: str) -> Optional[str]:
    """Return "CARREGADO" or "VAZIO" for the default network direction model.
    
    Args:
        a_name: Source station name
        b_name: Destination station name
        
    Returns:
        "CARREGADO", "VAZIO", or None
    """
    return _DEFAULT_DIRECTION_MODEL.classify(a_name, b_name)


__all__ = ["DirectionModel", "_direction_model_from_segments", "_classify_edge_global_dir"]
