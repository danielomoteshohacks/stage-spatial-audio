"""Decorrelators for the surround and height bed: velvet noise with transient-aware gating.

Decision 0016. Envelopment needs the ambience to arrive from many directions with low mutual
coherence; feeding the same signal to every bed loudspeaker would collapse into the head.

* **Velvet-noise decorrelator** (Alary, Politis and Valimaki 2017, "Velvet-noise decorrelator",
  DAFx-17): a sparse filter of +1 and -1 impulses at random positions within regular grid cells
  (Karjalainen and Jarvelainen 2007), here 1500 impulses per second over 25 ms with an
  exponentially decaying envelope. Different seeds give mutually decorrelated, spectrally flat
  filters that are cheap and smear far less than long noise bursts.
* **Transient gating** (after Vilkamo and Pulkki's analysis of decorrelator artifacts): around
  onsets the decorrelated output is cross-faded back to the dry signal, so claps and snares that
  leak into the ambience are not smeared over the decorrelator's 25 ms.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import maximum_filter1d, uniform_filter1d
from scipy.signal import butter, oaconvolve, sosfiltfilt

DENSITY_PER_S = 1500.0
LENGTH_S = 0.025
DECAY_DB = 30.0


def velvet_filter(seed: int, sample_rate: int, length_s: float = LENGTH_S,
                  density: float = DENSITY_PER_S, decay_db: float = DECAY_DB
                  ) -> NDArray[np.float64]:
    """One unit-energy velvet-noise decorrelation filter."""
    rng = np.random.default_rng(seed)
    n = int(round(length_s * sample_rate))
    grid = sample_rate / density
    cells = int(n / grid)
    h = np.zeros(n)
    for m in range(cells):
        pos = int(m * grid + rng.uniform(0, grid - 1))
        if pos < n:
            env = 10.0 ** (-decay_db / 20.0 * pos / n)
            h[pos] = env * (1.0 if rng.random() < 0.5 else -1.0)
    return h / np.sqrt(np.sum(h**2))


def transient_gate(x: NDArray, sample_rate: int, attack_s: float = 0.002,
                   hold_s: float = 0.03) -> NDArray[np.float64]:
    """Weight in [0, 1] per sample: 1 where a transient is starting, 0 in steady sound.

    The envelope above 1.5 kHz is compared with its slow average; a sharp rise is a transient.
    The weight is held for 30 ms (the decorrelator's length) and smoothed so the cross-fade does
    not click.
    """
    mono = np.asarray(x, dtype=np.float64)
    if mono.ndim > 1:
        mono = mono.mean(axis=0)
    sos = butter(2, 1500.0, btype="highpass", fs=sample_rate, output="sos")
    env = np.abs(sosfiltfilt(sos, mono))
    fast = uniform_filter1d(env, max(1, int(attack_s * sample_rate)))
    slow = uniform_filter1d(env, max(1, int(0.05 * sample_rate)))
    ratio = fast / (slow + 1e-9)
    gate = np.clip((ratio - 1.5) / 1.5, 0.0, 1.0)
    gate = maximum_filter1d(gate, max(1, int(hold_s * sample_rate)), origin=-int(
        hold_s * sample_rate) // 2 + 1)
    return uniform_filter1d(gate, max(1, int(0.004 * sample_rate)))


def decorrelate(x: NDArray, seed: int, sample_rate: int,
                gate: NDArray | None = None) -> NDArray[np.float64]:
    """x (n,) through one velvet filter, falling back to the dry signal at transients."""
    y = oaconvolve(x, velvet_filter(seed, sample_rate))[: x.size]
    if gate is None:
        return y
    return (1.0 - gate) * y + gate * x
