"""Split a stereo part into its centre and its two sides, so no part is ever collapsed to mono.

Why this exists (decision 0031). v3 rendered most parts as ONE point source from their mid
signal (`mode: mono`) or as two point sources fed by the raw left and right channels
(`mode: pair`). Listening on real songs: the spatial version sounded narrower than the original,
"like mono", with the instruments squashed together. Both modes cause it:

* A mono point source throws away everything that made the part wide in the mix: a doubled
  vocal, a stereo reverb, overheads, a stereo piano. Four-stem separation puts most of a song in
  four such parts, so most of the song lost its width.
* A pair fed by raw L and R puts the part's centre content (the kick and snare inside "drums",
  the lead inside "other") into BOTH far-apart sources. Through head filters that is a phantom
  image from two directions 150 degrees apart: hollow, combed and vague.

The fix is the centre/side decomposition of stereo upmixing (Avendano and Jot, "A frequency-domain
approach to multichannel upmix", JAES 52(7/8), 2004): per time-frequency tile, the inter-channel
similarity psi = 2|S_LR| / (S_LL + S_RR) is 1 for content panned to the centre and 0 for content
in one channel only. The centre is m * (L + R) / 2 with the mask m = psi ** SHARPNESS, and each
side is its channel minus the centre, computed in the time domain so that

    left = centre + side_left  and  right = centre + side_right   (exactly, to rounding)

and nothing of the part is lost or added. The centre is rendered where the part sits; each side
is rendered as its own source out at the part's width. The statistics are smoothed over time
(a one-pole average of about 40 ms) so the mask does not flutter, which is what makes the
musical-noise artifacts of hard time-frequency masks inaudible here: nothing is removed, the
mask only decides which of two nearby sources a tile comes from.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.signal import lfilter

from stage.analysis.stft import istft, stft

N_FFT = 2048
HOP = 512
#: psi ** 3: a centred tile (psi 1) stays centre, a tile panned halfway (psi about 0.7) goes
#: mostly (66 percent) to its side, so half-panned instruments move out instead of staying in the
#: middle, and noise in psi near 1 changes little.
SHARPNESS = 3.0
SMOOTH_S = 0.04


def centre_sides(x: NDArray, sample_rate: int) -> dict[str, NDArray[np.float32]]:
    """{"C": centre (n,), "Ls": left side (n,), "Rs": right side (n,)} of a (2, n) part."""
    x = np.asarray(x, dtype=np.float64)
    n = x.shape[1]
    if n < N_FFT:
        mid = 0.5 * (x[0] + x[1])
        return {"C": mid.astype(np.float32), "Ls": (x[0] - mid).astype(np.float32),
                "Rs": (x[1] - mid).astype(np.float32)}
    spec = stft(x, n_fft=N_FFT, hop=HOP)  # (2, frames, bins)
    xl, xr = spec[0], spec[1]
    a = float(np.exp(-HOP / (SMOOTH_S * sample_rate)))
    smooth = lambda v: lfilter([1.0 - a], [1.0, -a], v, axis=0)  # noqa: E731
    sll = smooth(np.abs(xl) ** 2)
    srr = smooth(np.abs(xr) ** 2)
    slr = smooth(xl * np.conj(xr))
    psi = 2.0 * np.abs(slr) / (sll + srr + 1e-20)
    m = np.clip(psi, 0.0, 1.0) ** SHARPNESS
    c = istft((m * 0.5 * (xl + xr))[np.newaxis], n, n_fft=N_FFT, hop=HOP)[0]
    return {"C": c.astype(np.float32), "Ls": (x[0] - c).astype(np.float32),
            "Rs": (x[1] - c).astype(np.float32)}


def width_ratio(x: NDArray) -> float:
    """Side-to-mid energy of a stereo signal: 0 for mono, 1 for two unrelated channels."""
    x = np.asarray(x, dtype=np.float64)
    mid = x[0] + x[1]
    side = x[0] - x[1]
    return float(np.sum(side**2) / max(np.sum(mid**2), 1e-20))


#: The width matcher may raise the side signal by at most this much in any band. More would make
#: lateral sources jump to the ears instead of opening the stage.
WIDTH_MAX_DB = 9.0


def width_filter(original: NDArray, render: NDArray, sample_rate: int
                 ) -> tuple[NDArray[np.float64], dict[str, float]]:
    """A minimum-phase filter for the render's side channel, so the render is never narrower
    than the record in any 1/3-octave band (decision 0031).

    Head filters make every source reach both ears, so a binaural render is always more
    correlated between the ears than headphone stereo, where a hard-panned part is in one ear
    only. Measured on the generated songs: side-to-mid energy 0.27 in the record and 0.06 in the
    v3 render; the centre/side upmix took it to 0.12. This lifts the render's side (L - R) in
    each band by the dB that brings its side-to-mid ratio to the record's, only upwards and at
    most WIDTH_MAX_DB, smoothly across bands. Directions stay where the head filters put them;
    what changes is how far apart the two ears' signals are, which is the width a listener
    compares against the original."""
    from stage.guard.checks import third_octave_bands
    from stage.spatial.neutral import MATCH_HIGH_HZ, _band_powers, correction_filter

    o = np.asarray(original, dtype=np.float64)
    r = np.asarray(render, dtype=np.float64)
    centres, lo, hi = third_octave_bands(200.0, min(MATCH_HIGH_HZ, sample_rate / 2.3))
    def ms(x: NDArray) -> tuple[NDArray, NDArray]:
        return (_band_powers(x[0] + x[1], sample_rate, lo, hi),
                _band_powers(x[0] - x[1], sample_rate, lo, hi))

    om, os_ = ms(o)
    rm, rs = ms(r)
    valid = (om > om.max() * 1e-6) & (rm > 0) & (rs > 0)
    want = np.zeros(centres.size)
    want[valid] = 10.0 * np.log10((os_[valid] / om[valid]) / (rs[valid] / rm[valid]))
    gain_db = np.clip(want, 0.0, WIDTH_MAX_DB)
    gain_db = np.convolve(np.pad(gain_db, 1, mode="edge"), np.ones(3) / 3.0, mode="valid")
    return correction_filter(centres, gain_db, sample_rate), {
        "max_side_lift_db": round(float(gain_db.max()), 2),
        "mean_side_lift_db": round(float(gain_db.mean()), 2)}


def apply_width(render: NDArray, h: NDArray) -> NDArray[np.float32]:
    """Filter the side channel of a (2, n) render with `h` and rebuild left and right."""
    from scipy.signal import fftconvolve

    r = np.asarray(render, dtype=np.float32)
    n = r.shape[1]
    mid = 0.5 * (r[0] + r[1])
    side = 0.5 * (r[0] - r[1])
    side = fftconvolve(side, np.asarray(h, dtype=np.float32))[:n]
    return np.stack([mid + side, mid - side]).astype(np.float32)


#: Sample-peak ceiling of the final render. The inter-sample peak of music sits at most about
#: 0.5 dB above its sample peak at 44.1 kHz in practice, so -1.5 dBFS keeps it under -1 dBTP.
PEAK_CEILING_DB = -1.5
LIMIT_WINDOW_S = 0.04


def limit_peaks(x: NDArray, sample_rate: int, ceiling_db: float = PEAK_CEILING_DB
                ) -> tuple[NDArray[np.float32], float]:
    """A transparent peak limiter for the final render; returns it and the deepest cut in dB.

    The width matcher raises the side signal, and a side peak adds to a mid peak in one ear: the
    first live renders measured +4 dBTP. A gain of 1 everywhere the render is under the ceiling,
    and just enough reduction around each peak. The gain is the minimum of the required gain over
    a 40 ms window, then a 40 ms moving average of that: every averaged value comes from windows
    that contain the sample, so the gain never exceeds what the sample needs, and it changes
    smoothly enough not to be heard as distortion. Zero phase (it is offline), applied to both
    ears alike so the image does not move."""
    from scipy.ndimage import minimum_filter1d, uniform_filter1d

    x = np.asarray(x, dtype=np.float32)
    ceiling = 10.0 ** (ceiling_db / 20.0)
    peak = np.max(np.abs(x), axis=0)
    need = np.minimum(1.0, ceiling / np.maximum(peak, 1e-12)).astype(np.float32)
    if need.min() >= 1.0:
        return x, 0.0
    w = max(int(LIMIT_WINDOW_S * sample_rate), 1)
    g = uniform_filter1d(minimum_filter1d(need, w, mode="nearest"), w, mode="nearest")
    g = np.minimum(g, need)  # rounding in the average must never let a peak through
    return (x * g[np.newaxis]).astype(np.float32), round(float(20 * np.log10(g.min())), 2)
