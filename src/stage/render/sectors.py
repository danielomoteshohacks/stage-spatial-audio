"""Sector decomposition and the widen warp.

A stereo mix places each time-frequency bin at an angle inside the speaker pair (about +/-30
degrees). We split every bin's power across 13 fixed sectors by that angle, then give each sector
its own wider rendered azimuth, so sounds keep their left-to-right order but spread around the
listener.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

#: Sector centres, 13 of them every 5 degrees from -30 to +30 (0 is ahead, positive is right).
SECTOR_CENTRES_DEG: NDArray[np.float64] = np.linspace(-30.0, 30.0, 13)

#: Gaussian width. Half the 5 degree spacing keeps neighbouring sectors overlapping smoothly,
#: so a source panned between two centres is shared rather than snapped to one.
SECTOR_SIGMA_DEG = 2.5

#: Asymptote of the widen warp: no source is pushed past 80 degrees (never fully to the side).
WIDEN_LIMIT_DEG = 80.0

#: Bounds of the widen strength used by the plan; 1.0 is nearly the identity near the centre.
WIDEN_BETA_MIN = 1.0
WIDEN_BETA_MAX = 2.4


def sector_weights(angle_deg: ArrayLike) -> NDArray[np.float64]:
    """Share of each of the 13 sectors for source angle(s) in degrees.

    Returns shape (13, *np.shape(angle_deg)). Weights are Gaussians around the centres,
    normalised so they sum to 1 over axis 0 for every angle.

    The normalisation is done as a softmax (subtract the largest exponent first). A plain
    exp-then-divide underflows to 0/0 for angles far outside the sector range and would give NaN;
    this way an out-of-range angle simply falls entirely on the nearest edge sector.
    """
    angle = np.asarray(angle_deg, dtype=np.float64)
    centres = SECTOR_CENTRES_DEG.reshape((-1,) + (1,) * angle.ndim)
    expo = -0.5 * ((angle[np.newaxis] - centres) / SECTOR_SIGMA_DEG) ** 2
    expo -= expo.max(axis=0, keepdims=True)
    w = np.exp(expo)
    return w / w.sum(axis=0, keepdims=True)


def widen_azimuth(theta_deg: ArrayLike, beta: float = WIDEN_BETA_MAX) -> NDArray[np.float64]:
    """Order-preserving widen warp: alpha = 80 * tanh(beta * theta / 80).

    Odd and strictly increasing, so left stays left and ordering is never swapped; the slope at
    zero is beta and the output saturates below 80 degrees. Valid for beta in [1.0, 2.4].
    """
    if not WIDEN_BETA_MIN <= beta <= WIDEN_BETA_MAX:
        raise ValueError(f"beta must be in [{WIDEN_BETA_MIN}, {WIDEN_BETA_MAX}], got {beta}")
    theta = np.asarray(theta_deg, dtype=np.float64)
    return WIDEN_LIMIT_DEG * np.tanh(beta * theta / WIDEN_LIMIT_DEG)


def sector_azimuths(beta: float = WIDEN_BETA_MAX) -> NDArray[np.float64]:
    """Rendered azimuth of each of the 13 sectors, shape (13,): the widened centres."""
    return widen_azimuth(SECTOR_CENTRES_DEG, beta)


def apply_sectors(
    power: NDArray[np.float64], angle_deg: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Split power across the 13 sectors by each bin's source angle.

    Args:
        power: shape (frames, bins), no channel axis. Combine channels before calling.
        angle_deg: source angle of every bin, same shape as ``power``.

    Returns:
        Array of shape (13, frames, bins). Weights are (13, frames, bins) and sum to 1 over
        axis 0, so summing the result over axis 0 returns ``power`` (to rounding error, about
        1e-16 relative). Silent bins stay exactly zero.

    Memory: the output is 13 times the input, and weights need as much again while it is built.
    A 4 minute song at 44.1 kHz with hop 1024 is about 10,350 frames x 1025 bins, so one call
    on the whole song needs over 1 GB in float64 for the weights alone. Call this on blocks of
    frames (a few hundred at a time), render each block, and discard it before the next.
    """
    power = np.asarray(power, dtype=np.float64)
    angle = np.asarray(angle_deg, dtype=np.float64)
    if power.ndim != 2:
        raise ValueError(f"power must be (frames, bins), got shape {power.shape}")
    if angle.shape != power.shape:
        raise ValueError(f"angle_deg shape {angle.shape} must match power {power.shape}")
    return sector_weights(angle) * power[np.newaxis]
