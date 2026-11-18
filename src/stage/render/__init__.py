"""Pan-Anchored Spatial Rendering: sectors, widen warp, HRTF filtering, room, timbre bound."""

from stage.render.headmodel import ear_delays_s, head_shadow, sector_filters
from stage.render.renderer import render_stereo
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
    "ear_delays_s",
    "head_shadow",
    "render_stereo",
    "sector_azimuths",
    "sector_filters",
    "sector_weights",
    "widen_azimuth",
]
