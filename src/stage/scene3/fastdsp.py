"""Faster versions of v2's crossover split and loudness match (decision 0027).

* `fast_split`: the zero-phase Linkwitz-Riley split of `stage.spatial.neutral.split_low_high` done
  in the frequency domain. `sosfiltfilt` of an order-4 Butterworth applies |H|^2, so multiplying
  the spectrum by the squared magnitude response of the same filter gives the same low band
  (tested against the original to better than -80 dB away from the ends of the signal), with
  one FFT pair for any number of channels instead of two sequential IIR passes per channel.
  The high band is still the remainder, so the pair sums to the input exactly.
* `fast_match_loudness`: the same bisection as `match_loudness_upper`, but the K-weighting (a
  linear filter) is applied once to the low and the upper band, and each iteration works on
  per-step sums of squares and cross products: |a + g b|^2 = aa + 2 g ab + g^2 bb per 100 ms step.
  Thirty bisection steps cost thirty small array operations instead of thirty full filterings.
"""

from __future__ import annotations

import numpy as np
import scipy.fft as sfft
from numpy.typing import NDArray
from scipy.signal import butter, sosfreqz

from stage.guard.loudness import (
    BLOCK_S,
    STEP_S,
    _window_energies,
    gated_loudness,
    integrated_loudness,
    k_weight,
)
from stage.spatial.neutral import CROSSOVER_ORDER


def fast_split(x: NDArray, sample_rate: int, crossover_hz: float
               ) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """(low, high) of (channels, n) with low + high == x."""
    x = np.asarray(x, dtype=np.float32)
    n = x.shape[-1]
    pad = int(0.25 * sample_rate)  # room for the filter to ring out, so the ends do not wrap
    nfft = int(sfft.next_fast_len(n + 2 * pad, real=True))
    sos = butter(CROSSOVER_ORDER, crossover_hz, btype="lowpass", fs=sample_rate, output="sos")
    _, h = sosfreqz(sos, worN=nfft // 2 + 1, fs=sample_rate)
    gain = (np.abs(h) ** 2).astype(np.float32)
    spec = sfft.rfft(x, nfft, axis=-1)
    low = sfft.irfft(spec * gain, nfft, axis=-1)[..., :n].astype(np.float32)
    return low, x - low


def fast_match_loudness(original: NDArray, low: NDArray, upper: NDArray, sample_rate: int,
                        iterations: int = 30) -> tuple[NDArray, float]:
    """Scale `upper` so the BS.1770 loudness of low + g * upper equals the original's."""
    target = integrated_loudness(original, sample_rate)
    if not np.isfinite(target) or not np.any(upper):
        return upper, 1.0
    a = k_weight(low, sample_rate)
    b = k_weight(upper, sample_rate)
    step = int(round(STEP_S * sample_rate))
    n_steps = a.shape[-1] // step
    if n_steps == 0:
        return upper, 1.0

    def per_step(u: NDArray, v: NDArray) -> NDArray:
        m = (u[:, : n_steps * step] * v[:, : n_steps * step]).reshape(u.shape[0], n_steps, step)
        return m.mean(axis=-1).sum(axis=0)

    aa, ab, bb = per_step(a, a), per_step(a, b), per_step(b, b)
    n_per = int(round(BLOCK_S / STEP_S))

    def loudness(g: float) -> float:
        return gated_loudness(_window_energies(aa + 2.0 * g * ab + g * g * bb, n_per))

    lo_db, hi_db = -24.0, 24.0
    for _ in range(iterations):
        mid = 0.5 * (lo_db + hi_db)
        if loudness(10.0 ** (mid / 20.0)) > target:
            hi_db = mid
        else:
            lo_db = mid
    g = 10.0 ** (0.5 * (lo_db + hi_db) / 20.0)
    return upper * g, g
