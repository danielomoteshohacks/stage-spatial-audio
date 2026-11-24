"""The separator's DSP back end (numpy): Wiener refinement, mixture consistency, bleed reduction.

All functions work on complex STFTs shaped (S, 2, T, F): stems, channels, frames, bins, with
the mixture X shaped (2, T, F).

1. **Multichannel Wiener refinement** (Duong, Vincent and Gribonval 2010, "Under-determined
   reverberant audio source separation using a full-rank spatial covariance model", IEEE TASLP
   18(7); the procedure norbert implements for Open-Unmix). Each stem j has a power spectral
   density v_j(t, f) and a 2 x 2 spatial covariance R_j(f). The refined estimate is
       Y_j = v_j R_j (sum_k v_k R_k)^-1 X,
   and one EM pass re-estimates v_j and R_j from the result. R_j is where the stem's stereo
   position enters: a centred vocal and a wide pad separate better because they sit in
   different places.
2. **Bleed reduction**: the stems' powers are sharpened (an exponent above 1 on each stem's
   share) before the Wiener gains are formed, which lowers the floor of the soft masks where one
   stem clearly dominates. Exponent 1 leaves the Wiener filter unchanged.
3. **Mixture consistency** (Wisdom et al. 2019, "Differentiable consistency constraints for
   improved deep speech enhancement", ICASSP): the residual X - sum_j Y_j is shared out by each
   stem's power share, so the stems sum to the mixture exactly. The spatial renderer depends on
   that: whatever the separator gets wrong is still in some stem, so nothing of the record is
   lost.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

EPS = 1e-10


def _inv2x2(a: NDArray) -> NDArray:
    """Inverse of (..., 2, 2) complex matrices, with a small diagonal load for stability."""
    a = a + EPS * np.eye(2)
    det = a[..., 0, 0] * a[..., 1, 1] - a[..., 0, 1] * a[..., 1, 0]
    inv = np.empty_like(a)
    inv[..., 0, 0] = a[..., 1, 1]
    inv[..., 1, 1] = a[..., 0, 0]
    inv[..., 0, 1] = -a[..., 0, 1]
    inv[..., 1, 0] = -a[..., 1, 0]
    return inv / det[..., None, None]


def spatial_stats(y: NDArray) -> tuple[NDArray, NDArray]:
    """PSD v (S, T, F) and normalised spatial covariance R (S, F, 2, 2) of stem estimates."""
    v = 0.5 * np.sum(np.abs(y) ** 2, axis=1)  # mean over the two channels
    outer = y[:, :, None] * np.conj(y[:, None, :])  # (S, 2, 2, T, F)
    r = np.sum(outer / (v[:, None, None] + EPS), axis=3) / y.shape[2]  # (S, 2, 2, F)
    return v, np.moveaxis(r, (1, 2), (-2, -1))


def wiener(y: NDArray, x: NDArray, iterations: int = 1, sharpen: float = 1.0) -> NDArray:
    """Refine stem estimates y (S, 2, T, F) against the mixture x (2, T, F)."""
    y = np.asarray(y, dtype=np.complex128)
    x = np.asarray(x, dtype=np.complex128)
    for _ in range(max(1, iterations)):
        v, r = spatial_stats(y)
        if sharpen != 1.0:
            share = v / (v.sum(axis=0, keepdims=True) + EPS)
            v = v.sum(axis=0, keepdims=True) * share**sharpen / (
                np.sum(share**sharpen, axis=0, keepdims=True) + EPS)
        cov = v[..., None, None] * r[:, None]  # (S, T, F, 2, 2)
        inv = _inv2x2(cov.sum(axis=0))  # (T, F, 2, 2)
        xt = np.moveaxis(x, 0, -1)[..., None]  # (T, F, 2, 1)
        gain = cov @ inv[None]  # (S, T, F, 2, 2)
        y = np.moveaxis((gain @ xt[None])[..., 0], -1, 1)  # (S, 2, T, F)
    return y


def mixture_consistency(y: NDArray, x: NDArray) -> NDArray:
    """Share the residual out by power, so sum over stems equals x exactly."""
    resid = x - y.sum(axis=0)
    p = np.abs(y) ** 2
    share = (p + EPS / y.shape[0]) / (p.sum(axis=0, keepdims=True) + EPS)
    return y + share * resid[None]


def residual_snr_db(y: NDArray, x: NDArray) -> float:
    """Mixture energy over the energy of what the raw estimates leave unexplained."""
    num = float(np.sum(np.abs(x) ** 2))
    den = float(np.sum(np.abs(x - y.sum(axis=0)) ** 2))
    return float("inf") if den == 0 else 10.0 * np.log10(max(num, 1e-30) / den)


def leakage_db(y: NDArray) -> NDArray[np.float64]:
    """Per-stem leakage estimate: the share of a stem's energy in bins another stem dominates.

    Without references the true leakage is unknown. A stem's energy in time-frequency bins where
    a different stem holds more than half of the total power is, for well-separated sources,
    mostly bleed; its fraction (in dB) is reported per stem as an estimate, lower is cleaner.
    """
    p = np.sum(np.abs(y) ** 2, axis=1)  # (S, T, F)
    total = p.sum(axis=0) + EPS
    dominant = np.argmax(p, axis=0)
    strong = (p.max(axis=0) / total) > 0.5
    out = []
    for j in range(p.shape[0]):
        elsewhere = strong & (dominant != j)
        frac = float(p[j][elsewhere].sum()) / max(float(p[j].sum()), 1e-30)
        out.append(10.0 * np.log10(max(frac, 1e-6)))
    return np.asarray(out)


def refine(y: NDArray, x: NDArray, sharpen: float = 1.25, iterations: int = 1
           ) -> tuple[NDArray, dict[str, object]]:
    """The whole back end: Wiener with bleed reduction, then consistency, with the numbers."""
    before = residual_snr_db(y, x)
    y = wiener(y, x, iterations=iterations, sharpen=sharpen)
    y = mixture_consistency(y, x)
    return y, {"raw_residual_snr_db": None if not np.isfinite(before) else round(before, 2),
               "leakage_db": [round(float(v), 2) for v in leakage_db(y)],
               "wiener_iterations": iterations, "bleed_sharpen": sharpen}
