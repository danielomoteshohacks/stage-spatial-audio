"""A believable room in closed form: image-source early reflections and an FDN late field.

Hypotheses H14 and H15 in docs/decisions/0007-spatialisation-spike.md. Everything is
deterministic so the Rust core can match it sample for sample.

Room coordinates: x forward (the listener's look direction at yaw 0), y to the right, z up, in
metres, with one room corner at the origin.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import product

import numpy as np
from numpy.typing import NDArray
from scipy.linalg import hadamard
from scipy.signal import lfilter

from stage.analysis import istft, stft
from stage.render.headmodel import HEAD_RADIUS_M, SPEED_OF_SOUND_M_S
from stage.render.pinna import ear_filters

#: Octave centres of the absorption table.
ALPHA_BANDS_HZ = np.array([125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0])
#: Hand-chosen absorption, rising with frequency like a furnished room. Not from a measured table.
ALPHA_WALLS = np.array([0.10, 0.12, 0.15, 0.20, 0.25, 0.30, 0.35])
ALPHA_FLOOR = np.array([0.12, 0.15, 0.20, 0.30, 0.40, 0.45, 0.50])
ALPHA_CEILING = np.array([0.15, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30])

#: Early reflections kept per source (the earliest of all images up to second order).
N_REFLECTIONS = 12
#: Length of an early-reflection FIR. Second-order images in this room arrive within about 45 ms.
ER_FIR_LEN = 4096


@dataclass(frozen=True)
class Room:
    """A shoebox room. The listener is off-centre so image delays do not coincide."""

    size_m: tuple[float, float, float] = (10.0, 8.0, 3.2)
    listener_m: tuple[float, float, float] = (3.0, 4.2, 1.2)


@dataclass(frozen=True)
class Reflection:
    """One image source: delay after the direct sound, spreading gain, wall hits, direction."""

    delay_s: float
    gain: float
    hits: tuple[int, int, int, int, int, int]  # x0, xL, y0, yL, floor, ceiling
    az_deg: float  # world azimuth of arrival (before head rotation)
    el_deg: float


def source_position(room: Room, az_deg: float, distance_m: float) -> NDArray[np.float64]:
    """World position of a source at ear height, `distance_m` away at world azimuth `az_deg`."""
    lx, ly, lz = room.listener_m
    a = np.radians(az_deg)
    pos = np.array([lx + distance_m * np.cos(a), ly + distance_m * np.sin(a), lz])
    if np.any(pos <= 0.0) or np.any(pos >= np.array(room.size_m)):
        raise ValueError(f"source at {az_deg} deg, {distance_m} m is outside the room")
    return pos


def image_sources(room: Room, src: NDArray[np.float64], max_order: int = 2) -> list[Reflection]:
    """All images up to `max_order` wall hits, sorted by arrival, excluding the direct path.

    Per axis the image coordinate is (1 - 2q) s + 2 n L, with q in {0, 1}; it has |n - q| hits on
    the wall at 0 and |n| on the wall at L (Allen and Berkley 1979).
    """
    listener = np.array(room.listener_m)
    direct = float(np.linalg.norm(src - listener))
    axis_options = []
    for s, length in zip(src, room.size_m, strict=True):
        opts = []
        for n, q in product((-1, 0, 1), (0, 1)):
            hits0, hits_l = abs(n - q), abs(n)
            if hits0 + hits_l <= max_order:
                opts.append(((1 - 2 * q) * s + 2 * n * length, hits0, hits_l))
        axis_options.append(opts)
    out = []
    for (x, x0, xl), (y, y0, yl), (z, z0, zl) in product(*axis_options):
        hits = (x0, xl, y0, yl, z0, zl)
        if not 0 < sum(hits) <= max_order:
            continue
        v = np.array([x, y, z]) - listener
        dist = float(np.linalg.norm(v))
        out.append(
            Reflection(
                delay_s=(dist - direct) / SPEED_OF_SOUND_M_S,
                gain=direct / dist,
                hits=hits,
                az_deg=float(np.degrees(np.arctan2(v[1], v[0]))),
                el_deg=float(np.degrees(np.arctan2(v[2], np.hypot(v[0], v[1])))),
            )
        )
    out.sort(key=lambda r: r.delay_s)
    return out


def wall_reflectance(hits: tuple[int, ...], freqs_hz: NDArray[np.float64]) -> NDArray[np.float64]:
    """Amplitude reflectance prod sqrt(1 - alpha(f)) over the wall hits, interpolated in log f."""
    logf = np.log(np.clip(freqs_hz, ALPHA_BANDS_HZ[0], ALPHA_BANDS_HZ[-1]))
    logb = np.log(ALPHA_BANDS_HZ)
    out = np.ones_like(freqs_hz)
    tables = (ALPHA_WALLS,) * 4 + (ALPHA_FLOOR, ALPHA_CEILING)
    for count, table in zip(hits, tables, strict=True):
        if count:
            out *= np.sqrt(1.0 - np.interp(logf, logb, table)) ** count
    return out


def early_reflection_fir(
    reflections: list[Reflection],
    *,
    sample_rate: int,
    yaw_deg: float = 0.0,
    pinna: bool = False,
    steering_db: float = 0.0,
    ear_norm: float = 1.0,
    n_fir: int = ER_FIR_LEN,
    highpass_hz: float | None = None,
    send_db: float = 0.0,
) -> NDArray[np.float64]:
    """Binaural FIR (2, n_fir) of the given reflections, time 0 = the direct sound.

    Each reflection is heard through the same ear model as the direct path, at its own arrival
    direction relative to the head, so rotating the head (yaw) moves the reflections correctly.
    `highpass_hz` and `send_db` are the H14b variant: below about 100 Hz the reflections arrive
    nearly in phase and pile up as bass, which a second-order high-pass removes.
    """
    freqs = np.fft.rfftfreq(n_fir, d=1.0 / sample_rate)
    spec = np.zeros((2, freqs.size), dtype=np.complex128)
    if not reflections:
        return np.zeros((2, n_fir))
    az = np.array([r.az_deg for r in reflections]) - yaw_deg
    el = np.array([r.el_deg for r in reflections])
    ears = ear_norm * ear_filters(
        az, el, n_fft=n_fir, sample_rate=sample_rate, pinna=pinna, steering_db=steering_db
    )
    for r, h in zip(reflections, ears, strict=True):
        shaped = r.gain * wall_reflectance(r.hits, freqs) * np.exp(-2j * np.pi * freqs * r.delay_s)
        spec += h * shaped[np.newaxis, :]
    if highpass_hz:
        with np.errstate(divide="ignore"):
            spec *= 1.0 / np.sqrt(1.0 + (highpass_hz / freqs) ** 4)
    spec *= 10.0 ** (send_db / 20.0)
    return np.fft.irfft(spec, n=n_fir, axis=-1)


# --- Late field -------------------------------------------------------------------------------

#: Number of FDN delay lines. 16 with a Hadamard matrix mixes every line into every other at
#: equal weight, which builds echo density faster than a Householder matrix of the same size.
FDN_LINES = 16
FDN_MIN_S = 0.023
FDN_MAX_S = 0.053
#: Reverberation time at DC and at Nyquist (seconds).
T60_LOW_S = 0.60
T60_HIGH_S = 0.25
#: Ear spacing used for the diffuse-field coherence target.
EAR_SPACING_M = 2.0 * HEAD_RADIUS_M


def _next_prime(n: int) -> int:
    def is_prime(k: int) -> bool:
        return k > 1 and all(k % d for d in range(2, int(k**0.5) + 1))

    while not is_prime(n):
        n += 1
    return n


def fdn_delays(sample_rate: int) -> NDArray[np.int64]:
    """Distinct primes near log-spaced targets: mutually prime lengths avoid repeating patterns."""
    out: list[int] = []
    for t in np.geomspace(FDN_MIN_S, FDN_MAX_S, FDN_LINES) * sample_rate:
        p = _next_prime(int(round(t)))
        while p in out:
            p = _next_prime(p + 1)
        out.append(p)
    return np.array(out, dtype=np.int64)


def fdn_absorption(
    delays: NDArray[np.int64], sample_rate: int, t60_low: float, t60_high: float
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Per-line gain g and pole b of g (1 - b) / (1 - b z^-1).

    DC gain g gives T60 = t60_low and Nyquist gain g (1 - b) / (1 + b) gives T60 = t60_high,
    because a line of m samples must lose 60 dB over T60 * fs / m passes.
    """
    m = delays.astype(np.float64)
    g = 10.0 ** (-3.0 * m / (sample_rate * t60_low))
    rho = 10.0 ** (-3.0 * m / sample_rate * (1.0 / t60_high - 1.0 / t60_low))
    b = (1.0 - rho) / (1.0 + rho)
    return g, b


def fdn_process(
    x: NDArray[np.float64],
    sample_rate: int,
    t60_low: float = T60_LOW_S,
    t60_high: float = T60_HIGH_S,
) -> NDArray[np.float64]:
    """Run a mono signal through the FDN; returns two uncorrelated outputs, shape (2, n).

    Processed in blocks no longer than the shortest delay: then every sample a block reads was
    written by an earlier block, so the vectorised result equals the sample-by-sample loop.
    """
    x = np.asarray(x, dtype=np.float64)
    m = fdn_delays(sample_rate)
    g, b = fdn_absorption(m, sample_rate, t60_low, t60_high)
    n_lines = m.size
    matrix = hadamard(n_lines).astype(np.float64) / np.sqrt(n_lines)  # orthogonal: lossless loop
    taps = hadamard(n_lines).astype(np.float64)[[1, 2]] / np.sqrt(n_lines)  # orthogonal rows
    b_in = np.ones(n_lines) / np.sqrt(n_lines)

    block = int(m.min())
    size = int(m.max()) + block
    buf = np.zeros((n_lines, size))
    states = np.zeros((n_lines, 1))
    lines = np.arange(n_lines)[:, np.newaxis]
    out = np.zeros((2, x.size))
    for t0 in range(0, x.size, block):
        t = np.arange(t0, min(t0 + block, x.size))
        delayed = buf[lines, (t[np.newaxis, :] - m[:, np.newaxis]) % size]
        filtered = np.empty_like(delayed)
        for i in range(n_lines):
            filtered[i], states[i] = lfilter(
                [g[i] * (1.0 - b[i])], [1.0, -b[i]], delayed[i], zi=states[i]
            )
        buf[lines, t[np.newaxis, :] % size] = b_in[:, np.newaxis] * x[t] + matrix @ filtered
        out[:, t] = taps @ filtered
    return out


def diffuse_coherence(freqs_hz: NDArray[np.float64], spacing_m: float = EAR_SPACING_M):
    """Free-field diffuse coherence sin(kd)/(kd) between two points `spacing_m` apart."""
    return np.sinc(2.0 * np.asarray(freqs_hz) * spacing_m / SPEED_OF_SOUND_M_S)


def coherence_mix(y: NDArray[np.float64], sample_rate: int, n_fft: int = 2048):
    """Mix two uncorrelated signals (2, n) into ears with the diffuse coherence target per bin.

    L = a Y1 + b Y2, R = a Y1 - b Y2 with a^2 + b^2 = 1 and a^2 - b^2 = gamma(f), outside the
    loop as in Menzer and Faller (2009). Real per-bin gains, so the STFT round trip stays exact.
    """
    hop = n_fft // 2
    spec = stft(y, n_fft=n_fft, hop=hop)
    gamma = diffuse_coherence(np.fft.rfftfreq(n_fft, d=1.0 / sample_rate))
    a = np.sqrt((1.0 + gamma) / 2.0)
    b = np.sqrt((1.0 - gamma) / 2.0)
    ears = np.stack([a * spec[0] + b * spec[1], a * spec[0] - b * spec[1]])
    return istft(ears, y.shape[1], n_fft=n_fft, hop=hop)


@lru_cache(maxsize=8)
def late_unit_energy(sample_rate: int) -> float:
    """Binaural energy (both ears) of the late chain's impulse response, for level calibration."""
    n = int(4.0 * T60_LOW_S * sample_rate)
    imp = np.zeros(n)
    imp[0] = 1.0
    ir = coherence_mix(fdn_process(imp, sample_rate), sample_rate)
    return float(np.sum(ir**2))
