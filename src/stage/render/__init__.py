"""Pan-Anchored Spatial Rendering: sectors, widen warp, HRTF filtering, room, timbre bound."""

from stage.render.sectors import (
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
