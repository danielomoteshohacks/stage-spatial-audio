"""Keep the record's tone and its bass: the low-end crossover and the final timbre matcher.

Decision 0014.

**Crossover.** Everything below about 120 Hz bypasses the spatial renderer: it stays centred where
the mix put it, dry, and sample-identical to the original. The split is a fourth-order
Linkwitz-Riley magnitude (two cascaded second-order Butterworth sections, Linkwitz 1976, "Active
crossover networks for noncoincident drivers", JAES 24(1)) applied forward and backward, so it
has zero phase. A causal Linkwitz-Riley pair sums to an all-pass; the zero-phase pair sums to
exactly the input, because |H_lp|^2 + |H_hp|^2 = 1 for a Butterworth pair. So when the spatial
path is transparent the output equals the input, and whatever the spatial path does above the
crossover cannot shift the bass in time against the original.

**Timbre matcher.** Binaural rendering colours the long-term spectrum (the head's response at
each direction, room reflections). The matcher compares the long-term average spectrum of the
rendered upper band with the original's upper band in 1/3-octave resolution (no finer: finer
corrections would undo the directional cues themselves), limits the correction, and applies one
smooth minimum-phase filter to both ears identically. Identical filtering of both ears leaves
every interaural difference, so the stereo and spatial image are untouched, and it is applied
only above the crossover, so the low end is never touched.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.signal import butter, fftconvolve, sosfiltfilt, welch

from stage.guard.checks import third_octave_bands
from stage.spatial.hrtfpack import minimum_phase_from_logmag

DEFAULT_CROSSOVER_HZ = 120.0
#: Order of the Butterworth applied forward and backward: 4 gives Linkwitz-Riley magnitudes of
#: 48 dB per octave (LR8). The second-order version (LR4, 24 dB per octave) let enough of the
#: rendered upper band through below 100 Hz to lower the bass's correlation with the record to
#: 0.98 on broadband noise; the eighth-order slope keeps it above 0.99 (tests/unit/test_room.py).
CROSSOVER_ORDER = 4
MATCH_LOW_HZ = 125.0
MATCH_HIGH_HZ = 16000.0
MATCH_LIMIT_DB = 12.0
MATCH_TAPS = 2048


def split_low_high(x: NDArray, sample_rate: int, crossover_hz: float = DEFAULT_CROSSOVER_HZ
                   ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Zero-phase Linkwitz-Riley split of (channels, n): low + high == x to rounding."""
    x = np.asarray(x, dtype=np.float64)
    sos = butter(CROSSOVER_ORDER, crossover_hz, btype="lowpass", fs=sample_rate, output="sos")
    low = sosfiltfilt(sos, x, axis=-1, padtype="constant")
    # The high band is defined as the remainder, so the pair is complementary by construction;
    # for the Butterworth pair the remainder is exactly the zero-phase LR4 high-pass.
    return low, x - low


def _band_powers(x: NDArray, sample_rate: int, lo: NDArray, hi: NDArray) -> NDArray[np.float64]:
    nper = int(min(16384, x.shape[-1]))
    freqs, p = welch(x, fs=sample_rate, nperseg=nper, axis=-1)
    p = p.sum(axis=0) if p.ndim > 1 else p
    return np.array([p[(freqs >= a) & (freqs < b)].sum() for a, b in zip(lo, hi, strict=True)])


def timbre_correction_db(original_high: NDArray, render_high: NDArray, sample_rate: int,
                         limit_db: float = MATCH_LIMIT_DB) -> tuple[NDArray, NDArray]:
    """(band centres, correction dB) that brings the render's 1/3-octave spectrum to the original's.

    The broadband level is excluded (loudness is matched separately), so only the shape changes.
    Bands with almost no energy in the original are left at 0 dB.
    """
    centres, lo, hi = third_octave_bands(MATCH_LOW_HZ, min(MATCH_HIGH_HZ, sample_rate / 2.3))
    po = _band_powers(original_high, sample_rate, lo, hi)
    pr = _band_powers(render_high, sample_rate, lo, hi)
    valid = (po > po.max() * 1e-7) & (pr > 0)
    corr = np.zeros(centres.size)
    corr[valid] = 10.0 * np.log10(po[valid] / pr[valid])
    # Remove the energy-weighted mean so the matcher changes shape, not level.
    w = po * valid
    corr[valid] -= np.sum(w[valid] * corr[valid]) / max(np.sum(w[valid]), 1e-30)
    return centres, np.clip(corr, -limit_db, limit_db)


def correction_filter(centres: NDArray, corr_db: NDArray, sample_rate: int,
                      taps: int = MATCH_TAPS) -> NDArray[np.float64]:
    """Minimum-phase FIR whose magnitude follows the band corrections, flat outside them.

    The curve is interpolated in log frequency between band centres and faded to 0 dB over the
    octave below the first band, so nothing changes at or below the crossover.
    """
    n_fft = 4 * taps
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    logf = np.log2(np.maximum(freqs, 1.0))
    curve = np.interp(logf, np.log2(centres), corr_db, left=corr_db[0], right=0.0)
    fade = np.clip(logf - (np.log2(centres[0]) - 1.0), 0.0, 1.0)
    curve *= 0.5 - 0.5 * np.cos(np.pi * fade)
    h = minimum_phase_from_logmag(curve, n_fft)[:taps]
    return h * np.hanning(2 * taps)[taps:]  # a gentle tail taper; the head is untouched


def timbre_filter(original_high: NDArray, render_high: NDArray, sample_rate: int
                  ) -> tuple[NDArray[np.float64], dict[str, float]]:
    """The correction FIR alone, so the same filter can be applied to every object stem."""
    centres, corr = timbre_correction_db(original_high, render_high, sample_rate)
    return correction_filter(centres, corr, sample_rate), {
        "max_correction_db": round(float(np.max(np.abs(corr))), 2), "bands": int(centres.size)}


def match_timbre(original_high: NDArray, render_high: NDArray, sample_rate: int
                 ) -> tuple[NDArray[np.float64], dict[str, float]]:
    """Apply the correction to both ears of the rendered upper band; return it and a summary."""
    centres, corr = timbre_correction_db(original_high, render_high, sample_rate)
    h = correction_filter(centres, corr, sample_rate)
    out = fftconvolve(render_high, h[np.newaxis, :], axes=-1)[:, : render_high.shape[-1]]
    return out, {"max_correction_db": round(float(np.max(np.abs(corr))), 2),
                 "bands": int(centres.size)}


def match_loudness_upper(original: NDArray, low: NDArray, upper: NDArray, sample_rate: int,
                         iterations: int = 30) -> tuple[NDArray[np.float64], float]:
    """Scale only the upper band so BS.1770 loudness of low + g * upper equals the original's.

    Levelling the whole render would move the untouched low band with it; the bass must stay the
    record's bass, so the gain goes on the rendered part alone. Loudness grows monotonically
    with g, so a bisection in dB finds it to 0.01 dB.
    """
    from stage.guard.loudness import integrated_loudness

    target = integrated_loudness(original, sample_rate)
    if not np.isfinite(target) or not np.any(upper):
        return upper, 1.0
    lo_db, hi_db = -24.0, 24.0
    for _ in range(iterations):
        mid = 0.5 * (lo_db + hi_db)
        if integrated_loudness(low + upper * 10.0 ** (mid / 20.0), sample_rate) > target:
            hi_db = mid
        else:
            lo_db = mid
    g = 10.0 ** (0.5 * (lo_db + hi_db) / 20.0)
    return upper * g, g
