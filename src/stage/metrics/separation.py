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
