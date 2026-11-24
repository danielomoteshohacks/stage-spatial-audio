"""Separation metrics that need no external package: SDR, the permutation match and the
direction-map distance.

SDR here is the plain signal-to-distortion ratio of a stem, 10 log10 |s|^2 / |s - s_hat|^2, over
the whole excerpt. It is not museval's windowed BSSEval v4 (scripts/eval_separation.py uses that
for MUSDB18-HQ); on generated songs, where the references are exact and the same code scores every
engine, it is a fair like-for-like number and is labelled "plain SDR" wherever it is printed.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import linear_sum_assignment, linprog

from stage.metrics.spatial import DirectionMap, angular_distance_deg


def sdr_db(ref: NDArray, est: NDArray) -> float:
    num = float(np.sum(ref**2))
    den = float(np.sum((ref - est) ** 2))
    return float(10.0 * np.log10((num + 1e-20) / (den + 1e-20)))


def sdr_matrix(refs: dict[str, NDArray], ests: dict[str, NDArray]) -> NDArray[np.float64]:
    out = np.zeros((len(refs), len(ests)))
    for i, r in enumerate(refs.values()):
        for j, e in enumerate(ests.values()):
            out[i, j] = sdr_db(r, e)
    return out


def match_leaves(refs: dict[str, NDArray], ests: dict[str, NDArray]) -> dict[str, str]:
    """Assign each estimate to the reference it resembles most (Hungarian, on plain SDR), so a
    separator's own names do not have to equal the references' (BSS-eval's permutation step).
    Estimates beyond the number of references stay unmatched."""
    m = sdr_matrix(refs, ests)
    rows, cols = linear_sum_assignment(-m)
    r_names, e_names = list(refs), list(ests)
    return {r_names[i]: e_names[j] for i, j in zip(rows, cols, strict=True)}


def best_stem_for(ref: NDArray, ests: dict[str, NDArray]) -> str:
    """The estimate that holds most of the reference: largest normalised projection of the
    reference on it. For a four-stem separator and a leaf this names the stem the leaf ended up
    in, which is many-to-one where `match_leaves` is one-to-one."""
    best, name = -1.0, ""
    for k, e in ests.items():
        c = abs(float(np.sum(ref * e))) / (np.sqrt(np.sum(ref**2) * np.sum(e**2)) + 1e-20)
        if c > best:
            best, name = c, k
    return name


def grid_directions(step_deg: float = 30.0) -> tuple[NDArray, NDArray]:
    """Cell centres of an azimuth/elevation grid (elevations -30 to 60)."""
    azs = np.arange(-180.0 + step_deg / 2, 180.0, step_deg)
    els = np.array([-30.0, 0.0, 30.0, 60.0])
    a, e = np.meshgrid(azs, els)
    return a.ravel(), e.ravel()


def histogram(dmap: DirectionMap, step_deg: float = 30.0) -> tuple[NDArray, NDArray, NDArray]:
    """Direct energy of a map on the grid, normalised to sum to one: (az, el, mass)."""
    ga, ge = grid_directions(step_deg)
    mass = np.zeros(ga.size)
    total = float(dmap.direct.sum())
    if total <= 0.0:
        return ga, ge, mass
    for a, e, d in zip(dmap.az, dmap.el, dmap.direct, strict=True):
        dist = [angular_distance_deg(a, e, x, y) for x, y in zip(ga, ge, strict=True)]
        mass[int(np.argmin(dist))] += d / total
    return ga, ge, mass


def map_distance_deg(a: DirectionMap, b: DirectionMap, step_deg: float = 30.0) -> float:
    """Earth mover's distance between two direction-energy maps, in degrees of great-circle
    travel: the average angle the energy of one render must move to become the other. Zero for
    identical maps, up to 180 for opposite ones."""
    ga, ge, ma = histogram(a, step_deg)
    _, _, mb = histogram(b, step_deg)
    n = ga.size
    cost = np.array([[angular_distance_deg(ga[i], ge[i], ga[j], ge[j]) for j in range(n)]
                     for i in range(n)])
    # Transportation problem: minimise sum cost * flow, rows sum to ma, columns to mb.
    a_eq = np.zeros((2 * n, n * n))
    for i in range(n):
        a_eq[i, i * n : (i + 1) * n] = 1.0
        a_eq[n + i, i::n] = 1.0
    res = linprog(cost.ravel(), A_eq=a_eq, b_eq=np.concatenate([ma, mb]), bounds=(0, None),
                  method="highs")
    if not res.success:
        raise RuntimeError(f"transport problem failed: {res.message}")
    return float(res.fun)


# --- Bleedless and fullness (the MVSep leaderboard metrics) --------------------------------------


def mel_filterbank(sr: int, n_fft: int, n_mels: int) -> NDArray[np.float64]:
    """Triangular mel filters on the Slaney scale with Slaney area normalisation, the default
    of librosa.filters.mel, which the published implementation uses."""
    def hz_to_mel(f):
        f = np.asarray(f, dtype=np.float64)
        lin = f / (200.0 / 3.0)
        log_t = 1000.0 / (200.0 / 3.0)
        logstep = np.log(6.4) / 27.0
        return np.where(f >= 1000.0, log_t + np.log(np.maximum(f, 1e-9) / 1000.0) / logstep, lin)

    def mel_to_hz(m):
        m = np.asarray(m, dtype=np.float64)
        log_t = 1000.0 / (200.0 / 3.0)
        logstep = np.log(6.4) / 27.0
        return np.where(m >= log_t, 1000.0 * np.exp(logstep * (m - log_t)), (200.0 / 3.0) * m)

    fft_f = np.fft.rfftfreq(n_fft, 1.0 / sr)
    mel_f = mel_to_hz(np.linspace(hz_to_mel(0.0), hz_to_mel(sr / 2.0), n_mels + 2))
    fdiff = np.diff(mel_f)
    ramps = mel_f[:, None] - fft_f[None, :]
    lower = -ramps[:-2] / fdiff[:-1, None]
    upper = ramps[2:] / fdiff[1:, None]
    weights = np.maximum(0.0, np.minimum(lower, upper))
    weights *= (2.0 / (mel_f[2 : n_mels + 2] - mel_f[:n_mels]))[:, None]
    return weights


def _mel_db(x: NDArray, sr: int, n_fft: int, hop: int, n_mels: int, top_db: float = 80.0
            ) -> NDArray:
    from scipy.signal import stft as sp_stft

    window = np.hanning(n_fft + 1)[:-1]
    _, _, z = sp_stft(x, window=window, nperseg=n_fft, noverlap=n_fft - hop, boundary="zeros",
                      padded=False, return_onesided=True, scaling="spectrum")
    mag = np.abs(z) * (window.sum())  # undo the "spectrum" scaling: plain |STFT|
    mel = np.einsum("mf,cft->cmt", mel_filterbank(sr, n_fft, n_mels), mag)
    db = 20.0 * np.log10(np.maximum(mel, 1e-10))
    return np.maximum(db, db.max() - top_db)


def bleed_full(reference: NDArray, estimate: NDArray, sr: int = 44100, n_fft: int = 4096,
               hop: int = 1024, n_mels: int = 512) -> tuple[float, float]:
    """(bleedless, fullness), both 0 to 100, higher is better.

    From the published definition (the open `bleed_full` of ZFTurbo's Music-Source-Separation-
    Training utils/metrics.py, MIT, which MVSep's quality checker reports): mel spectrograms of
    reference and estimate in dB (floor 80 dB below the loudest tile); wherever the estimate is
    louder than the reference (positive difference, content that should not be there: bleed) the
    mean excess gives bleedless = 100 / (mean + 1); wherever it is quieter (negative difference,
    content that is missing) the mean shortfall gives fullness = 100 / (mean + 1). Identical
    signals score 100 on both.
    """
    d1 = _mel_db(np.asarray(reference, dtype=np.float64), sr, n_fft, hop, n_mels)
    d2 = _mel_db(np.asarray(estimate, dtype=np.float64), sr, n_fft, hop, n_mels)
    diff = d2 - d1
    pos = diff[diff > 0]
    neg = diff[diff < 0]
    avg_pos = float(pos.mean()) if pos.size else 0.0
    avg_neg = float(neg.mean()) if neg.size else 0.0
    return 100.0 / (avg_pos + 1.0), 100.0 / (-avg_neg + 1.0)
