"""Level 1 ensemble: combine several vocal models per frequency band, with fitted weights.

Averaging every model equally wastes what ensembling is for: models differ by band (one keeps
more of the top octave, another leaks less bass). Solovyev, Stempkovskiy and Habruseva (2023,
"Benchmarks and leaderboards for sound demixing tasks", arXiv 2305.07489) ensemble per stem with
weights chosen on a validation set, which is the approach MVSep's published ensembles follow.
This module does it per band: the spectrum is split into complementary bands (raised-cosine
cross-fades in the STFT, so they sum to one), and for each band the non-negative weights that
minimise the squared error against the reference on the validation songs are found by
non-negative least squares, normalised to sum to one.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import nnls

from stage.analysis.stft import istft, stft

N_FFT = 4096
HOP = 1024


def band_masks(edges_hz: list[float], sample_rate: int, n_fft: int = N_FFT) -> NDArray:
    """(B, F) masks that sum to one at every bin; each edge cross-fades over an octave-ish span."""
    f = np.fft.rfftfreq(n_fft, 1.0 / sample_rate)
    inner = [e for e in edges_hz if 0 < e < sample_rate / 2]
    masks = []
    lo_prev = np.ones_like(f)
    for e in inner:
        x = np.clip((np.log2(np.maximum(f, 1.0)) - np.log2(e / 1.2)) / (np.log2(e * 1.2)
                                                                         - np.log2(e / 1.2)), 0, 1)
        up = 0.5 - 0.5 * np.cos(np.pi * x)
        masks.append(lo_prev * (1.0 - up))
        lo_prev = lo_prev * up
    masks.append(lo_prev)
    return np.stack(masks)


def fit_band_weights(estimates: list[list[NDArray]], references: list[NDArray], sample_rate: int,
                     edges_hz: list[float]) -> NDArray:
    """Weights (B, M) for M models, fitted on validation songs.

    `estimates[s][m]` is model m's (2, n) estimate of song s; `references[s]` the true stem.
    """
    masks = band_masks(edges_hz, sample_rate)
    b, m = masks.shape[0], len(estimates[0])
    ata = np.zeros((b, m, m))
    atb = np.zeros((b, m))
    for ests, ref in zip(estimates, references, strict=True):
        r = stft(ref, N_FFT, HOP)
        e = np.stack([stft(x, N_FFT, HOP) for x in ests])  # (M, 2, T, F)
        for bi in range(b):
            mk = masks[bi][None, None, :]
            eb = (e * mk[None]).reshape(m, -1)
            rb = (r * mk).reshape(-1)
            ata[bi] += np.real(eb.conj() @ eb.T)
            atb[bi] += np.real(eb.conj() @ rb)
    w = np.zeros((b, m))
    for bi in range(b):
        # Solve the normal equations with the non-negativity constraint (NNLS on a Cholesky
        # factor), then normalise: weights that sum to one keep the level of the stem.
        chol = np.linalg.cholesky(ata[bi] + 1e-9 * np.eye(m) * np.trace(ata[bi]) / m)
        sol, _ = nnls(chol.T, np.linalg.solve(chol, atb[bi]))
        w[bi] = sol / sol.sum() if sol.sum() > 0 else np.full(m, 1.0 / m)
    return w


def combine(estimates: list[NDArray], weights: NDArray | None, sample_rate: int,
            edges_hz: list[float]) -> NDArray:
    """Weighted per-band combination of model estimates (each (2, n)); equal weights if None."""
    n = estimates[0].shape[1]
    masks = band_masks(edges_hz, sample_rate)
    m = len(estimates)
    w = np.full((masks.shape[0], m), 1.0 / m) if weights is None else weights
    spec = np.stack([stft(x, N_FFT, HOP) for x in estimates])  # (M, 2, T, F)
    mix_w = np.einsum("bm,bf->mf", w, masks)  # (M, F): the weight of model m at each bin
    return istft((spec * mix_w[:, None, None, :]).sum(axis=0), n, N_FFT, HOP)
