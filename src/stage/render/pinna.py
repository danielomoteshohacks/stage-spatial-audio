"""Closed-form direction cues beyond the spherical head: pinna, band steering, near field.

Everything here is a formula; no measured data. Sources and the exact values used are recorded in
docs/decisions/0007-spatialisation-spike.md.

Coordinates: azimuth `az` is vertical-polar, 0 straight ahead, +90 right, 180 behind; elevation
`el` is 0 at ear level and +90 overhead. Brown and Duda's pinna formula is written in
interaural-polar coordinates (lateral angle `theta`, polar angle `phi`), so we convert.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

from stage.render.headmodel import HEAD_RADIUS_M, sector_filters

# Brown and Duda (1998), Table I, delays in samples at 44.1 kHz. Event 1 is the direct path
# (rho 1, delay 0); events 2 to 6 are the table rows. D uses the column for subjects PB and NH.
PINNA_RHO = np.array([1.0, 0.5, -1.0, 0.5, -0.25, 0.25])
PINNA_A = np.array([0.0, 1.0, 5.0, 5.0, 5.0, 5.0])
PINNA_B = np.array([0.0, 2.0, 4.0, 7.0, 11.0, 13.0])
PINNA_D = np.array([0.0, 1.0, 0.5, 0.5, 0.5, 0.5])
PINNA_TABLE_RATE = 44100.0

# Blauert's directional bands (centre Hz, relative depth), read from the reproduction of his
# figure by Sengpiel (UdK Berlin, 1994). The 400 Hz front band gets half depth because a low-mid
# boost is the most audible colouring of the lot.
FRONT_BANDS = ((3150.0, 1.0), (400.0, 0.5))
REAR_BANDS = ((1000.0, 1.0), (11200.0, 1.0))
ABOVE_BANDS = ((8000.0, 1.0),)
BAND_SIGMA_OCT = 1.0 / 3.0

# Near-field ILD is applied below this corner: at high frequency the far-field head shadow already
# carries the level difference, and the 1/r cue would double-count it.
NEARFIELD_CORNER_HZ = 1000.0


def interaural_polar(az_deg: ArrayLike, el_deg: ArrayLike = 0.0) -> tuple[NDArray, NDArray]:
    """Lateral angle theta in [-90, 90] and polar angle phi in [-90, 270), in degrees.

    phi is 0 ahead, 90 overhead, 180 behind. The seam of the polar angle is put directly below
    the listener, where no music source is ever placed, because Eq. (8) is not periodic in phi
    for D = 0.5 and would jump wherever the seam is.
    """
    az = np.radians(np.asarray(az_deg, dtype=np.float64))
    el = np.radians(np.asarray(el_deg, dtype=np.float64))
    theta = np.degrees(np.arcsin(np.clip(np.sin(az) * np.cos(el), -1.0, 1.0)))
    phi = np.degrees(np.arctan2(np.sin(el), np.cos(az) * np.cos(el)))
    phi = np.where(phi < -90.0, phi + 360.0, phi)
    return theta, phi


def pinna_delays_s(az_deg: ArrayLike, el_deg: ArrayLike = 0.0) -> NDArray[np.float64]:
    """Delay of each of the 6 pinna events in seconds, shape (*broadcast(az, el), 6).

    tau_n = A_n cos(theta / 2) sin(D_n (90 - phi)) + B_n (Brown and Duda 1998, Eq. 8). The
    formula was fitted for phi in [-90, 90]; behind the listener (phi > 90) it is extrapolated,
    which is the SPECULATIVE part of hypothesis H12.
    """
    theta, phi = interaural_polar(az_deg, el_deg)
    theta, phi = theta[..., np.newaxis], phi[..., np.newaxis]
    tau = PINNA_A * np.cos(np.radians(theta / 2.0)) * np.sin(np.radians(PINNA_D * (90.0 - phi)))
    return (tau + PINNA_B) / PINNA_TABLE_RATE


def _pinna_raw(az, el, freqs: NDArray[np.float64]) -> NDArray[np.complex128]:
    tau = pinna_delays_s(az, el)  # (..., 6)
    phase = np.exp(-2j * np.pi * freqs * tau[..., np.newaxis])  # (..., 6, n_freq)
    return np.einsum("n,...nf->...f", PINNA_RHO, phase)


def _diffuse_field_power(freqs: NDArray[np.float64]) -> NDArray[np.float64]:
    """Mean pinna power over the sphere, weighted by cos(el) so each solid angle counts once.

    Cached per frequency grid: it is the same for every direction and is the slow part.
    """
    key = (freqs.size, float(freqs[0]), float(freqs[-1]))
    if key not in _DF_CACHE:
        _DF_CACHE[key] = _diffuse_field_power_uncached(freqs)
    return _DF_CACHE[key]


_DF_CACHE: dict[tuple[int, float, float], NDArray[np.float64]] = {}


def _diffuse_field_power_uncached(freqs: NDArray[np.float64]) -> NDArray[np.float64]:
    az, el = np.meshgrid(np.arange(0.0, 360.0, 5.0), np.arange(-45.0, 90.1, 7.5))
    w = np.cos(np.radians(el)).ravel()
    p = np.abs(_pinna_raw(az.ravel(), el.ravel(), freqs)) ** 2
    return (w[:, np.newaxis] * p).sum(axis=0) / w.sum()


def pinna_response(
    az_deg: ArrayLike, el_deg: ArrayLike, freqs_hz: ArrayLike
) -> NDArray[np.complex128]:
    """Diffuse-field equalised pinna response, shape (n_dir, n_freq). Same for both ears.

    Brown and Duda found the event timing about the same at the near and the far ear, so one
    response serves both. Dividing by the diffuse-field average removes the colour every
    direction shares and keeps only what differs between directions.
    """
    az = np.atleast_1d(np.asarray(az_deg, dtype=np.float64))
    el = np.broadcast_to(np.asarray(el_deg, dtype=np.float64), az.shape)
    freqs = np.asarray(freqs_hz, dtype=np.float64)
    return _pinna_raw(az, el, freqs) / np.sqrt(_diffuse_field_power(freqs))


def _bands_db(freqs: NDArray[np.float64], bands) -> NDArray[np.float64]:
    out = np.zeros_like(freqs)
    f = np.maximum(freqs, 1e-3)  # DC: log is -inf, the bump is 0 there anyway
    for centre, depth in bands:
        out += depth * np.exp(-0.5 * (np.log2(f / centre) / BAND_SIGMA_OCT) ** 2)
    return out


def steering_gain_db(
    az_deg: ArrayLike, el_deg: ArrayLike, freqs_hz: ArrayLike, depth_db: float
) -> NDArray[np.float64]:
    """Directional-band steering EQ in dB, shape (n_dir, n_freq) (hypothesis H13).

    Frontness c = cos(az) cos(el) moves the front bands up and the rear bands down by c * depth
    (the signs swap behind). Sources above get sin(el) * depth at 8 kHz. No band moves by more
    than `depth_db`, so the colour stays inside the H2 timbre bound when depth is 1.5 dB.
    """
    az = np.radians(np.atleast_1d(np.asarray(az_deg, dtype=np.float64)))
    el = np.radians(np.broadcast_to(np.asarray(el_deg, dtype=np.float64), az.shape))
    freqs = np.asarray(freqs_hz, dtype=np.float64)
    front = _bands_db(freqs, FRONT_BANDS)
    rear = _bands_db(freqs, REAR_BANDS)
    above = _bands_db(freqs, ABOVE_BANDS)
    c = (np.cos(az) * np.cos(el))[:, np.newaxis]
    up = np.maximum(np.sin(el), 0.0)[:, np.newaxis]
    return depth_db * (c * (front - rear) + up * above)


def _path_to_ear(r: NDArray, gamma: NDArray, a: float) -> NDArray:
    """Source-to-ear path for a sphere: straight if the ear is visible, else tangent plus arc.

    gamma is the angle (radians) between the source direction and the ear, seen from the centre.
    """
    visible = np.arccos(np.clip(a / r, -1.0, 1.0))
    straight = np.sqrt(r**2 + a**2 - 2.0 * r * a * np.cos(gamma))
    wrapped = np.sqrt(np.maximum(r**2 - a**2, 0.0)) + a * (gamma - visible)
    return np.where(gamma <= visible, straight, wrapped)


def nearfield_ild_db(az_deg: ArrayLike, distance_m: ArrayLike) -> NDArray[np.float64]:
    """Low-frequency ILD (near ear minus far ear, dB) from the 1/r path difference (H16).

    First-order geometry, not the spherical-head series solution: positive whenever the source
    is off-centre, 0 on the median plane, and growing as the source comes closer.
    """
    lat = np.abs(np.radians(np.asarray(az_deg, dtype=np.float64)))
    lat = np.arcsin(np.sin(lat))  # rear mirrors onto front, as for the ITD
    r = np.maximum(np.asarray(distance_m, dtype=np.float64), HEAD_RADIUS_M * 1.01)
    near = _path_to_ear(r, np.pi / 2.0 - lat, HEAD_RADIUS_M)
    far = _path_to_ear(r, np.pi / 2.0 + lat, HEAD_RADIUS_M)
    return 20.0 * np.log10(far / near)


def nearfield_gains(
    az_deg: ArrayLike, distance_m: ArrayLike, freqs_hz: ArrayLike
) -> NDArray[np.float64]:
    """Per-ear amplitude gains (n_dir, 2, n_freq), left then right, for the near-field ILD.

    Split symmetrically (+ILD/2 near, -ILD/2 far) and faded out above NEARFIELD_CORNER_HZ, so the
    summed power of the ears is about unchanged and the high band is left to the head shadow.
    """
    az = np.atleast_1d(np.asarray(az_deg, dtype=np.float64))
    ild = np.broadcast_to(nearfield_ild_db(az, distance_m), az.shape)
    freqs = np.asarray(freqs_hz, dtype=np.float64)
    fade = 1.0 / (1.0 + (freqs / NEARFIELD_CORNER_HZ) ** 2)
    side = np.sign(np.sin(np.radians(az)))[:, np.newaxis]  # + right
    half = 0.5 * ild[:, np.newaxis] * fade[np.newaxis, :]
    right = 10.0 ** (side * half / 20.0)
    left = 10.0 ** (-side * half / 20.0)
    return np.stack([left, right], axis=1)


def ear_filters(
    az_deg: ArrayLike,
    el_deg: ArrayLike = 0.0,
    *,
    n_fft: int = 2048,
    sample_rate: int = 44100,
    pinna: bool = False,
    steering_db: float = 0.0,
) -> NDArray[np.complex128]:
    """Two-ear responses for directions (az, el), shape (n_dir, 2, n_fft // 2 + 1).

    The head part is `sector_filters` at the lateral angle (ITD and shadow depend only on it).
    With el = 0 everywhere the azimuth is passed through unchanged, so with no extras this is
    bit-for-bit `sector_filters` and the V0 profile reproduces the default renderer exactly.
    """
    az = np.atleast_1d(np.asarray(az_deg, dtype=np.float64))
    el = np.broadcast_to(np.asarray(el_deg, dtype=np.float64), az.shape)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    if np.any(el != 0.0):
        lateral, _ = interaural_polar(az, el)
        h = sector_filters(lateral, n_fft=n_fft, sample_rate=sample_rate)
    else:
        h = sector_filters(az, n_fft=n_fft, sample_rate=sample_rate)
    if pinna:
        h = h * pinna_response(az, el, freqs)[:, np.newaxis, :]
    if steering_db:
        gain = 10.0 ** (steering_gain_db(az, el, freqs, steering_db) / 20.0)
        h = h * gain[:, np.newaxis, :]
    return h
