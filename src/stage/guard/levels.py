"""Level helpers shared by every tool that writes a render next to its original.

A louder version tends to win an A/B comparison on loudness alone, so every render is matched to
the original's RMS before anyone hears it. The peak limit is a plain gain change, never a clipper
or compressor, so the waveform is only made quieter, not reshaped.
"""

from __future__ import annotations

import numpy as np

#: Peak ceiling for written files, about -0.2 dBFS. Leaves room for 24-bit rounding and for
#: players that resample.
PEAK_CEILING = 0.98


def rms(x: np.ndarray) -> float:
    """RMS over all channels and samples."""
    return float(np.sqrt(np.mean(np.square(x))))


def match_rms(x: np.ndarray, target_rms: float) -> np.ndarray:
    """Scale `x` to `target_rms`. Silence is returned unchanged."""
    current = rms(x)
    return x if current == 0.0 else x * (target_rms / current)


def peak_gain(peak: float, ceiling: float = PEAK_CEILING) -> float:
    """The gain that brings `peak` down to `ceiling`, or 1.0 when it is already below it."""
    return 1.0 if peak <= ceiling else ceiling / peak


def limit_peak(x: np.ndarray, ceiling: float = PEAK_CEILING) -> tuple[np.ndarray, float]:
    """Scale the whole signal down if its peak exceeds `ceiling`; return it and the gain used."""
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    gain = peak_gain(peak, ceiling)
    return x * gain, gain
