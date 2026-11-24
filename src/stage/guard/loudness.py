"""Loudness and true peak after ITU-R BS.1770-4, plus short-term loudness after EBU Tech 3341.

Integrated loudness is the measure listeners' level judgements track best, which is why the guard
matches and reports it instead of RMS alone. Three parts, all from BS.1770-4:

* K-weighting: a high shelf (+4 dB above about 1.5 kHz, a model of the head's acoustic effect)
  followed by a high-pass (the "RLB" curve). The standard lists the coefficients for 48 kHz only;
  for other rates the same two analogue prototypes are re-derived with the bilinear transform,
  using the parameters that Brecht De Man fitted to the 48 kHz table (github.com/BrechtDeMan/
  loudness.py). At 48 kHz the table itself is used, so the reference rate is exact.
* Gating: 400 ms blocks with 75 percent overlap, an absolute gate at -70 LUFS and a relative gate
  10 LU below the loudness of the blocks that pass the absolute gate.
* True peak (Annex 2): oversample by four (by two at 96 kHz and above, where the standard notes
  that the error is already small), take the largest absolute sample, report in dBTP.

Every function takes (channels, samples) float arrays; stereo channels get weight 1.0.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
from numpy.typing import NDArray
from scipy.signal import lfilter, lfilter_zi, resample_poly

#: The BS.1770-4 table for 48 kHz (Tables 1 and 2).
K_SHELF_48K = (
    np.array([1.53512485958697, -2.69169618940638, 1.19839281085285]),
    np.array([1.0, -1.69065929318241, 0.73248077421585]),
)
K_HIGHPASS_48K = (
    np.array([1.0, -2.0, 1.0]),
    np.array([1.0, -1.99004745483398, 0.99007225036621]),
)
#: Parameters of the analogue prototypes that reproduce the 48 kHz table.
_SHELF_GAIN_DB = 3.99984385397
_SHELF_Q = 0.7071752369554193
_SHELF_FC = 1681.9744509555319
_SHELF_VB_EXP = 0.499666774155
_HP_Q = 0.5003270373253953
_HP_FC = 38.13547087613982

BLOCK_S = 0.4
STEP_S = 0.1  # 75 percent overlap
ABSOLUTE_GATE_LUFS = -70.0
RELATIVE_GATE_LU = -10.0
SHORT_TERM_S = 3.0
#: Loudness offset of the standard: -0.691 makes a 1 kHz full-scale sine read -3.01 LUFS.
_OFFSET = -0.691


def k_weighting(sample_rate: int) -> tuple[tuple[NDArray, NDArray], tuple[NDArray, NDArray]]:
    """(b, a) of the shelf and of the high-pass for `sample_rate` (the table at 48 kHz)."""
    if int(sample_rate) == 48000:
        return K_SHELF_48K, K_HIGHPASS_48K
    return design_k_weighting(sample_rate)


def design_k_weighting(
    sample_rate: int,
) -> tuple[tuple[NDArray, NDArray], tuple[NDArray, NDArray]]:
    """The bilinear-transform design of both stages (Brecht De Man's derivation).

    The shelf is a second-order high shelf with gain Vh and a mid-band gain Vb; the high-pass is
    a second-order section with the standard's [1, -2, 1] numerator. At 48 kHz this reproduces
    the BS.1770-4 table to about 1e-8, which the tests check.
    """
    k = math.tan(math.pi * _SHELF_FC / sample_rate)
    vh = 10.0 ** (_SHELF_GAIN_DB / 20.0)
    vb = vh**_SHELF_VB_EXP
    a0 = 1.0 + k / _SHELF_Q + k * k
    shelf = (
        np.array([(vh + vb * k / _SHELF_Q + k * k), 2.0 * (k * k - vh),
                  (vh - vb * k / _SHELF_Q + k * k)]) / a0,
        np.array([1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / _SHELF_Q + k * k) / a0]),
    )
    k = math.tan(math.pi * _HP_FC / sample_rate)
    a0 = 1.0 + k / _HP_Q + k * k
    highpass = (
        np.array([1.0, -2.0, 1.0]),
        np.array([1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / _HP_Q + k * k) / a0]),
    )
    return shelf, highpass


def k_weight(x: NDArray, sample_rate: int) -> NDArray[np.float64]:
    """Apply the K-weighting to (channels, samples)."""
    (b1, a1), (b2, a2) = k_weighting(sample_rate)
    y = lfilter(b1, a1, np.asarray(x, dtype=np.float64), axis=-1)
    return lfilter(b2, a2, y, axis=-1)


def _step_energies(weighted: NDArray, sample_rate: int) -> NDArray[np.float64]:
    """Channel-summed mean square of each 100 ms step: the building block of every window."""
    step = int(round(STEP_S * sample_rate))
    n_steps = weighted.shape[-1] // step
    if n_steps == 0:
        return np.zeros(0)
    sq = np.square(weighted[:, : n_steps * step]).reshape(weighted.shape[0], n_steps, step)
    return sq.mean(axis=-1).sum(axis=0)


def _window_energies(steps: NDArray, n_per: int) -> NDArray[np.float64]:
    """Mean of each run of `n_per` consecutive steps (a sliding window at the step hop)."""
    if steps.size < n_per:
        return np.zeros(0)
    c = np.concatenate([[0.0], np.cumsum(steps)])
    return (c[n_per:] - c[:-n_per]) / n_per


def _lufs(energy: NDArray | float) -> NDArray | float:
    with np.errstate(divide="ignore"):
        return _OFFSET + 10.0 * np.log10(energy)


def gated_loudness(block_energies: NDArray) -> float:
    """Integrated loudness from 400 ms block energies, with both gates. -inf for silence."""
    z = np.asarray(block_energies, dtype=np.float64)
    if z.size == 0:
        return float("-inf")
    loud = _lufs(z)
    above_abs = z[loud > ABSOLUTE_GATE_LUFS]
    if above_abs.size == 0:
        return float("-inf")
    relative = float(_lufs(above_abs.mean())) + RELATIVE_GATE_LU
    kept = z[(loud > ABSOLUTE_GATE_LUFS) & (loud > relative)]
    if kept.size == 0:
        return float("-inf")
    return float(_lufs(kept.mean()))


def integrated_loudness(x: NDArray, sample_rate: int) -> float:
    """BS.1770-4 integrated loudness in LUFS. Clips shorter than one block return -inf."""
    steps = _step_energies(k_weight(x, sample_rate), sample_rate)
    return gated_loudness(_window_energies(steps, int(round(BLOCK_S / STEP_S))))


def short_term_loudness(x: NDArray, sample_rate: int) -> tuple[NDArray, NDArray]:
    """EBU Tech 3341 short-term loudness (3 s window) every 100 ms: (start times s, LUFS)."""
    steps = _step_energies(k_weight(x, sample_rate), sample_rate)
    n_per = int(round(SHORT_TERM_S / STEP_S))
    e = _window_energies(steps, n_per)
    return np.arange(e.size) * STEP_S, np.asarray(_lufs(e), dtype=np.float64)


def true_peak_dbtp(x: NDArray, sample_rate: int) -> float:
    """Largest absolute value after oversampling, in dB true peak. -inf for silence."""
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return float("-inf")
    factor = 4 if sample_rate < 96000 else 2
    # BS.1770-4 Annex 2 attenuates by 12.04 dB before interpolating so the integer reference
    # implementation cannot overflow; in floating point that is unnecessary and is left out.
    peak = float(np.max(np.abs(resample_poly(x, factor, 1, axis=-1))))
    peak = max(peak, float(np.max(np.abs(x))))
    return 20.0 * math.log10(peak) if peak > 0 else float("-inf")


class StreamingStepEnergies:
    """K-weighted 100 ms step energies of a long file read in pieces, with filter state kept.

    Used to find the most energetic excerpt of a whole track without holding it in memory: a
    12 minute stereo file is about 500 MB as float64, the step energies are 7200 numbers.
    """

    def __init__(self, sample_rate: int, channels: int) -> None:
        (self.b1, self.a1), (self.b2, self.a2) = k_weighting(sample_rate)
        self.z1 = np.zeros((channels, 2))
        self.z2 = np.zeros((channels, 2))
        self.step = int(round(STEP_S * sample_rate))
        self.carry = np.zeros((channels, 0))
        self.energies: list[float] = []
        self._started = False

    def push(self, block: NDArray) -> None:
        block = np.asarray(block, dtype=np.float64)
        if not self._started:
            # Start the filters from a steady state at the first sample so a track that begins
            # loud does not get a step transient counted as energy.
            self.z1 = lfilter_zi(self.b1, self.a1)[np.newaxis, :] * block[:, :1]
            self.z2 = np.zeros_like(self.z1)
            self._started = True
        y, self.z1 = lfilter(self.b1, self.a1, block, axis=-1, zi=self.z1)
        y, self.z2 = lfilter(self.b2, self.a2, y, axis=-1, zi=self.z2)
        y = np.concatenate([self.carry, y], axis=-1)
        n = y.shape[-1] // self.step
        if n:
            sq = np.square(y[:, : n * self.step]).reshape(y.shape[0], n, self.step)
            self.energies.extend(sq.mean(axis=-1).sum(axis=0).tolist())
        self.carry = y[:, n * self.step :]

    def result(self) -> NDArray[np.float64]:
        return np.asarray(self.energies, dtype=np.float64)


def loudest_window(step_energies: Iterable[float], window_s: float) -> tuple[float, float]:
    """Start (s) of the `window_s` excerpt with the highest mean K-weighted energy, and its LUFS.

    The mean energy over the window is the ungated integrated loudness of that excerpt, so the
    window chosen is the loudest one a listener would hear, which in popular music is nearly
    always a chorus or a drop. Ties go to the earliest window.
    """
    steps = np.asarray(list(step_energies), dtype=np.float64)
    n_per = max(1, int(round(window_s / STEP_S)))
    if steps.size <= n_per:
        return 0.0, float(_lufs(steps.mean())) if steps.size else float("-inf")
    e = _window_energies(steps, n_per)
    best = int(np.argmax(e))
    return best * STEP_S, float(_lufs(e[best]))
