"""
Rendering module for stage spatial audio engine.
"""

from .sectors import (
    SECTOR_CENTRES_DEG,
    apply_sectors,
    sector_azimuths,
    sector_weights,
    widen_azimuth,
)

__all__ = [
    "SECTOR_CENTRES_DEG",
    "apply_sectors",
    "sector_azimuths",
    "sector_weights",
    "widen_azimuth",
]