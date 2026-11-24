"""Level 6: split a stereo stem by where it sits in the stereo image (azimuth discrimination).

Source: Barry, Lawlor and Coyle, "Sound Source Separation: Azimuth Discrimination and
Resynthesis" (DAFx-04, Naples, 2004). ADRess scales one channel by a gain g between 0 and 1 and
subtracts it from the other: a source that sits at a pan ratio g0 in both channels is cancelled
exactly at g = g0, so a null in the "azimuth plane" of a time-frequency tile gives the pan of
the source that dominates the tile, and the depth of the null says how dominant it is.

What this file does differently, and why:

* The null is found in closed form. For one tile, min over real g in [0, 1] of |L - g R| is
  reached at g = Re(L R*) / |R|^2 (clipped), so the search over the discretised gains of the
  paper (beta = 100 steps) is the limit beta -> infinity here. The pan of the tile is then
  p = (1 - g) / (1 + g), signed by the channel that was reduced. This is plain algebra on the
  paper's model (a source with one gain per channel), ESTABLISHED as a derivation.
* Soft masks. The paper's resynthesis keeps the tiles whose null falls inside an azimuth window
  and discards the rest, which leaves isolated tiles (musical noise). Here each tile is shared
  between the sources by Gaussian weights around their pans, scaled by the null depth, and what
  no source claims goes to a diffuse remainder, so the weights sum to one in every tile.
* Resynthesis from the original. Barry et al.'s later work on reconstruction (AES 2005,
  "Signal reconstruction methods for ADRess") compares ways of resynthesising from the separated
  magnitudes. That paper could not be retrieved in this environment (its host is blocked), so
  the choice made here is stated as ours and SPECULATIVE with respect to it: the mask multiplies
  the original complex left and right spectra, so each output keeps the original phase and
  level difference of its source (a stereo stem, not a mono estimate), and the outputs sum to
  the input exactly.

The method assumes one dominant source per tile (W-disjoint orthogonality, Rickard and Yilmaz
2004). Where two sources with the same pan overlap in a bin it cannot separate them, and it
cannot separate sources that share a pan at all: that is what the neural levels are for.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks

from stage.analysis.stft import istft, stft

N_FFT = 4096
HOP = 1024
EPS = 1e-12


def pan_map(left: NDArray, right: NDArray) -> tuple[NDArray, NDArray]:
    """Per-tile pan p in [-1, 1] (negative to the left) and confidence c in [0, 1].

    `left` and `right` are complex spectra of the same shape. Confidence is one minus the depth
    of the null relative to the tile's level: 1 for a single in-phase amplitude-panned source,
    falling for phase-different (time-panned, reverberant) content.
    """
    l2 = np.abs(left) ** 2 + EPS
    r2 = np.abs(right) ** 2 + EPS
    cross = np.real(left * np.conj(right))
    g_r = np.clip(cross / r2, 0.0, 1.0)  # L - g R: nulls for a source panned right
    g_l = np.clip(cross / l2, 0.0, 1.0)  # R - g L: nulls for a source panned left
    res_r = np.abs(left - g_r * right)
    res_l = np.abs(right - g_l * left)
    right_side = res_r <= res_l
    g = np.where(right_side, g_r, g_l)
    res = np.where(right_side, res_r, res_l)
    pan = np.where(right_side, 1.0, -1.0) * (1.0 - g) / (1.0 + g)
    level = np.sqrt(0.5 * (l2 + r2))
    conf = np.clip(1.0 - res / (np.sqrt(2.0) * level), 0.0, 1.0)
    return pan, conf


@dataclass
class PanCluster:
    centre: float
    share: float  # share of the stem's confident energy


def find_pan_clusters(pan: NDArray, conf: NDArray, energy: NDArray, *, min_share: float = 0.12,
                      min_separation: float = 0.3, min_conf: float = 0.6,
                      max_clusters: int = 4) -> list[PanCluster]:
    """Peaks of the energy-weighted pan histogram of the tiles that are dominated by one source."""
    sel = conf >= min_conf
    if not np.any(sel):
        return []
    bins = np.linspace(-1.0, 1.0, 41)
    hist, _ = np.histogram(pan[sel], bins=bins, weights=energy[sel])
    hist = uniform_filter1d(hist, 3, mode="constant")
    total = float(hist.sum())
    if total <= 0.0:
        return []
    centres = 0.5 * (bins[1:] + bins[:-1])
    peaks, _ = find_peaks(np.pad(hist, 1), prominence=0.04 * total)
    peaks = peaks - 1
    # A cluster's share is the energy within half the minimum separation of its peak.
    near = min_separation / 2.0
    found = sorted(((float(centres[p]),
                     float(hist[np.abs(centres - centres[p]) <= near].sum() / total))
                    for p in peaks if p >= 0), key=lambda c: -c[1])
    out: list[PanCluster] = []
    for c, s in found:
        if s < min_share or any(abs(c - o.centre) < min_separation for o in out):
            continue
        out.append(PanCluster(c, s))
        if len(out) == max_clusters:
            break
    return sorted(out, key=lambda c: c.centre)


def soft_masks(pan: NDArray, conf: NDArray, centres: list[float], sigma: float = 0.22,
               gamma: float = 1.0) -> NDArray:
    """(K + 1, T, F) masks summing to one: K sources by Gaussian pan weights, then a remainder."""
    c = conf**gamma
    w = np.stack([c * np.exp(-0.5 * ((pan - mu) / sigma) ** 2) for mu in centres])
    # What the sources do not claim (low confidence, far from every centre) is the remainder.
    rest = np.clip(1.0 - w.sum(axis=0), 0.0, None) + EPS
    all_w = np.concatenate([w, rest[np.newaxis]])
    return all_w / all_w.sum(axis=0, keepdims=True)


def azimuth_split(x: NDArray, centres: list[float] | None = None, *, sigma: float = 0.22,
                  n_fft: int = N_FFT, hop: int = HOP) -> tuple[list[NDArray], list[float], NDArray]:
    """Split a stereo signal (2, n) into one stereo signal per pan centre, plus the remainder.

    Returns (signals, centres, masks); the signals and the remainder (last) sum to `x`. With no
    `centres` they are found from the stem's own pan histogram, and a stem with one cluster is
    returned whole. The masks are (K + 1, T, F) for the callers that want to inspect them.
    """
    x = np.asarray(x, dtype=np.float64)
    n = x.shape[1]
    spec = stft(x, n_fft=n_fft, hop=hop)
    pan, conf = pan_map(spec[0], spec[1])
    if centres is None:
        energy = np.abs(spec[0]) ** 2 + np.abs(spec[1]) ** 2
        centres = [c.centre for c in find_pan_clusters(pan, conf, energy)]
    if len(centres) < 2:
        return [x.copy()], list(centres), np.ones((1,) + pan.shape)
    masks = soft_masks(pan, conf, list(centres), sigma)
    outs = [istft(spec * m[np.newaxis], n, n_fft=n_fft, hop=hop) for m in masks]
    return outs, list(centres), masks
