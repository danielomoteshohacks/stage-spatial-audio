"""Every renderer the pipeline can run, under one name space.

* v1 profiles (stage.render.profiles): "max", "V0" to "V5b". Analytic head, pan sectors.
* v2 spaces (stage.spatial): "space:<name>" for each preset in configs/spaces/spaces.json.
  Measured KU100 HRTFs, binaural room, zero-phase bass bypass, timbre and loudness matching.

v2 renders come back loudness-matched with the original's bass untouched, so the pipeline must
not RMS-match them again (that would move the bass with the rest); `is_v2` tells it so.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from stage.render.profiles import PROFILES, render_profile

SPACE_PREFIX = "space:"
DEFAULT_PROFILE = "space:studio"


def space_profiles() -> list[str]:
    from stage.spatial.room import spaces

    return [SPACE_PREFIX + name for name in spaces()]


def profile_names() -> list[str]:
    """v2 spaces first (the default first of all), then the v1 profiles for comparison."""
    return space_profiles() + list(PROFILES)


def is_v2(profile: str) -> bool:
    return profile.startswith(SPACE_PREFIX)


def check_profile(profile: str) -> None:
    if profile not in profile_names():
        raise ValueError(f"unknown profile {profile!r}; known: {profile_names()}")


def render(audio: NDArray, sample_rate: int, profile: str, beta: float = 2.0
           ) -> tuple[NDArray[np.float64], dict[str, Any] | None]:
    """Render stereo (2, n) with a named profile: (binaural (2, n), engine details or None)."""
    if is_v2(profile):
        from stage.spatial.render import render_stereo_room

        y, info = render_stereo_room(audio, sample_rate, profile[len(SPACE_PREFIX):])
        return y, {"engine": "v2", **info.as_dict()}
    return render_profile(audio, sample_rate, profile, beta), None
