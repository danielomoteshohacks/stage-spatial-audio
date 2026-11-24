"""v2 binaural rendering of a stereo signal through two virtual loudspeakers in a room.

This is the Phase 1 renderer and the base the scene renderer (Phase 2B) builds on:

    stereo -> zero-phase LR4 split at the crossover
           -> upper band: left and right channels through the BRIRs of loudspeakers at +/-30
              degrees in the chosen space (measured KU100 HRTFs, image-source reflections,
              FDN late field)  -> timbre matcher
           -> + the original lower band, untouched

The loudspeakers sit where a stereo mix is meant to be heard from (ITU-R BS.775 places the front
pair at +/-30 degrees), so every pan position in the record lands where the engineer heard it.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from numpy.typing import NDArray
from scipy.signal import oaconvolve

from stage.spatial.hrtf import BASE_DELAY, get_hrtf
from stage.spatial.neutral import (
    DEFAULT_CROSSOVER_HZ,
    match_loudness_upper,
    match_timbre,
    split_low_high,
)
from stage.spatial.room import Brir, brir, get_space

#: Azimuth of the virtual front pair (SOFA convention: positive is left).
STEREO_AZ_DEG = 30.0


@dataclass
class RenderInfo:
    hrtf: str
    space: str
    crossover_hz: float
    timbre: dict[str, float]

    def as_dict(self) -> dict[str, object]:
        return {"hrtf": self.hrtf, "space": self.space, "crossover_hz": self.crossover_hz,
                "timbre_match": self.timbre}


@lru_cache(maxsize=64)
def cached_brir(space: str, sample_rate: int, az: float, el: float, dist: float,
                reverb_scale: float = 1.0) -> Brir:
    return brir(get_space(space), get_hrtf(sample_rate), az, el, dist, reverb_scale=reverb_scale)


def convolve(x: NDArray, ir: NDArray) -> NDArray[np.float64]:
    """Mono signal (n,) through a binaural response (2, m): (2, n), time-aligned to BASE_DELAY.

    Overlap-add FFT convolution (scipy's oaconvolve partitions the long signal into blocks); the
    constant BASE_DELAY latency of the head filters is removed, so the render lines up with the
    original sample for sample.
    """
    y = oaconvolve(np.asarray(x)[np.newaxis, :], ir, axes=-1)
    return y[:, BASE_DELAY : BASE_DELAY + x.shape[-1]]


def render_stereo_room(audio: NDArray, sample_rate: int, space: str = "studio",
                       crossover_hz: float = DEFAULT_CROSSOVER_HZ, match: bool = True
                       ) -> tuple[NDArray[np.float64], RenderInfo]:
    """Render stereo (2, n) to binaural (2, n) through virtual loudspeakers in `space`."""
    audio = np.asarray(audio, dtype=np.float64)
    hs = get_hrtf(sample_rate)
    sp = get_space(space)
    low, high = split_low_high(audio, sample_rate, crossover_hz)
    out = np.zeros_like(high)
    for ch, az in ((0, STEREO_AZ_DEG), (1, -STEREO_AZ_DEG)):
        b = cached_brir(space, int(sample_rate), az, 0.0, sp.speaker_distance_m)
        out += convolve(high[ch], b.total)
    timbre: dict[str, float] = {}
    if match:
        out, timbre = match_timbre(high, out, sample_rate)
    out, gain = match_loudness_upper(audio, low, out, sample_rate)
    timbre["upper_gain_db"] = round(20.0 * np.log10(gain), 2)
    return low + out, RenderInfo(hrtf=hs.name, space=space, crossover_hz=crossover_hz,
                                 timbre=timbre)
