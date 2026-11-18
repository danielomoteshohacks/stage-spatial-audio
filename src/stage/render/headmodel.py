"""Closed-form head model: Woodworth ear delays and a Brown-Duda head shadow.

No measured data is used, so there is nothing to download or license. This is a coarse
stand-in for an HRTF: it carries the two cues that matter most (inter-ear time and the
high-frequency level difference) and nothing else.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

HEAD_RADIUS_M = 0.0875
SPEED_OF_SOUND_M_S = 343.0


def _ear_angles_deg(az_deg: NDArray[np.float64]) -> tuple[NDArray, NDArray]:
    """Angle between the source and each ear axis (left, right), in degrees.

    The ear axes are the +/-90 degree directions, so cos(theta_right) = sin(az). Going through
    arccos of sin(az) means a rear source (e.g. 150) lands on the same angle as its front mirror
    (30), which is what a model with no pinna cues should do.
    """
    s = np.sin(np.radians(az_deg))
    return np.degrees(np.arccos(-s)), np.degrees(np.arccos(s))


def ear_delays_s(az_deg: ArrayLike) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Per-ear arrival delays in seconds, as (left, right).

    Woodworth: itd = (a / c) * (|lat| + |sin lat|) with lat = arcsin(sin az). Only the far ear is
    delayed and the near ear gets 0, so both are non-negative and the filters stay causal.
    Positive azimuth is to the right, so the left ear is the far one.
    """
    az = np.asarray(az_deg, dtype=np.float64)
    lat = np.arcsin(np.sin(np.radians(az)))
    itd = (HEAD_RADIUS_M / SPEED_OF_SOUND_M_S) * (np.abs(lat) + np.abs(np.sin(lat)))
    side = _lateral_sign(az)
    # Far ear gets the delay: source on the right (side > 0) delays the left ear.
    return np.where(side > 0, itd, 0.0), np.where(side < 0, itd, 0.0)


def _lateral_sign(az: NDArray[np.float64]) -> NDArray[np.float64]:
    """Sign of the lateral position, positive on the right, 0 on the median plane.

    Uses sin(az) rather than az so that 150 degrees (rear right) is still on the right.
    """
    s = np.sin(np.radians(az))
    # Exact zeros matter: sin(180 deg) is ~1e-16 and must not pick a side.
    return np.where(np.abs(s) < 1e-12, 0.0, np.sign(s))


def head_shadow(theta_deg: ArrayLike, freqs_hz: ArrayLike) -> NDArray[np.complex128]:
    """Complex response of one ear, Brown and Duda one-pole one-zero shadow.

    theta_deg is the angle between the source and that ear's axis (0 near, 180 far).
    H(w) = (1 + j*alpha*w/(2*w0)) / (1 + j*w/(2*w0)), w0 = c / a,
    alpha = 1.05 + 0.95 * cos(theta * 180/150): alpha > 1 boosts highs on the near side and
    alpha < 1 cuts them on the far side, with the dip peaking near 150 degrees.

    Returns shape broadcast(theta, freqs). Pass theta as a column to get (n_theta, n_freq).
    """
    theta = np.asarray(theta_deg, dtype=np.float64)
    w = 2.0 * np.pi * np.asarray(freqs_hz, dtype=np.float64)
    alpha = 1.05 + 0.95 * np.cos(np.radians(theta * 180.0 / 150.0))
    w0 = SPEED_OF_SOUND_M_S / HEAD_RADIUS_M
    return (1.0 + 1j * alpha * w / (2.0 * w0)) / (1.0 + 1j * w / (2.0 * w0))


def sector_filters(
    azimuths_deg: ArrayLike, n_fft: int = 2048, sample_rate: int = 44100
) -> NDArray[np.complex128]:
    """Two-ear frequency responses for each azimuth, shape (n_az, 2, n_fft // 2 + 1).

    Axis 1 is left then right. Each ear is the head-shadow magnitude times a pure delay phase
    exp(-j 2 pi f delay). Magnitude only (not the shadow's own phase) so the delay is the single
    source of inter-ear timing and the measured lag matches the Woodworth value.
    """
    az = np.atleast_1d(np.asarray(azimuths_deg, dtype=np.float64))
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    theta_l, theta_r = _ear_angles_deg(az)
    delay_l, delay_r = ear_delays_s(az)
    out = np.empty((az.size, 2, freqs.size), dtype=np.complex128)
    for ear, (theta, delay) in enumerate(((theta_l, delay_l), (theta_r, delay_r))):
        mag = np.abs(head_shadow(theta[:, np.newaxis], freqs[np.newaxis, :]))
        out[:, ear, :] = mag * np.exp(-2j * np.pi * freqs[np.newaxis, :] * delay[:, np.newaxis])
    return out
