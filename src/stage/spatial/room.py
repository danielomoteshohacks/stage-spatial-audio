"""Binaural room responses: direct sound, image-source early reflections and an FDN late field.

Decision 0013. For one source in one space the binaural room impulse response (BRIR) is built
from three parts, all through the same head (stage.spatial.hrtf):

1. **Direct sound**: the head-related filter at the source direction.
2. **Early reflections**: image sources of a shoebox room up to order 2 or 3 (Allen and Berkley
   1979, "Image method for efficiently simulating small-room acoustics", JASA 65(4)). Each image
   arrives from its own direction through its own head-related filter, delayed by its extra path,
   attenuated by spherical spreading, by the absorption of every wall it touched (per octave) and
   by air absorption along its path (ISO 9613-1:1993, the standard's equations).
3. **Late field**: the existing 16-line Hadamard FDN (stage.render.room, Jot and Chaigne 1991)
   run once per octave band with that band's target RT60, band-split and summed, so the decay
   follows the target per band. Its two outputs are mixed per frequency to the interaural
   coherence of a diffuse field heard through the measured head (from the HRTF pack), instead of
   the free-field sin(kd)/kd of v1.

The level of the reverberant part follows the room's statistics: with Sabine's critical distance
r_c = 0.057 sqrt(V / T60), a source at distance r has a direct-to-reverberant ratio of
(r_c / r)^2. That makes distance audible in a physically consistent way (decision 0015).

Coordinates: x forward (the listener's look direction), y to the LEFT, z up, metres, with the
room's rear-right floor corner at the origin; azimuth counter-clockwise from x (SOFA).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from itertools import product

import numpy as np
from numpy.typing import NDArray

from stage.config import load_json
from stage.render.room import fdn_delays, fdn_process
from stage.spatial.hrtf import BASE_DELAY, HrtfSet

SPEED_OF_SOUND = 343.0
OCTAVES = np.array([125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0])


@dataclass(frozen=True)
class Space:
    name: str
    label: str
    size_m: tuple[float, float, float]
    listener_m: tuple[float, float, float]
    rt60_s: tuple[float, ...]
    absorption_bias: dict[str, float] = field(default_factory=dict)
    order: int = 2
    predelay_ms: float = 0.0
    speaker_distance_m: float = 2.0
    why: str = ""
    #: Level of all reflected sound (early and late) against the diffuse-room prediction. Rooms
    #: treated with absorbers and diffusers are not diffuse and reflect less than Sabine's theory
    #: predicts; the studio's value is fitted to the measured SADIE II BRIRs (decision 0013).
    reflection_level_db: float = 0.0

    @property
    def volume(self) -> float:
        return float(np.prod(self.size_m))

    @property
    def surface(self) -> float:
        lx, ly, lz = self.size_m
        return 2.0 * (lx * ly + lx * lz + ly * lz)

    def critical_distance(self, band: int = 3) -> float:
        """Sabine critical distance at the 1 kHz octave (where direct = reverberant energy)."""
        return 0.057 * float(np.sqrt(self.volume / self.rt60_s[band]))


def spaces() -> dict[str, Space]:
    raw = load_json("spaces/spaces.json")
    out = {}
    for name, d in raw.items():
        if name.startswith("_"):
            continue
        out[name] = Space(name=name, label=d["label"], size_m=tuple(d["size_m"]),
                          listener_m=tuple(d["listener_m"]), rt60_s=tuple(d["rt60_s"]),
                          absorption_bias=dict(d.get("absorption_bias", {})),
                          order=int(d.get("order", 2)), predelay_ms=float(d.get("predelay_ms", 0)),
                          speaker_distance_m=float(d.get("speaker_distance_m", 2.0)),
                          why=d.get("why", ""),
                          reflection_level_db=float(d.get("reflection_level_db", 0.0)))
    return out


def get_space(name: str) -> Space:
    all_spaces = spaces()
    if name not in all_spaces:
        raise ValueError(f"unknown space {name!r}; known: {sorted(all_spaces)}")
    return all_spaces[name]


def air_absorption_db_per_m(freqs_hz: NDArray, temperature_c: float = 20.0,
                            humidity_pct: float = 50.0, pressure_kpa: float = 101.325
                            ) -> NDArray[np.float64]:
    """Atmospheric absorption in dB per metre, ISO 9613-1:1993 equations (3) to (5) and (A.1)."""
    f = np.asarray(freqs_hz, dtype=np.float64)
    t = temperature_c + 273.15
    t0, t01, pr = 293.15, 273.16, 101.325
    pa = pressure_kpa
    psat = pr * 10.0 ** (-6.8346 * (t01 / t) ** 1.261 + 4.6151)
    h = humidity_pct * psat / pa  # molar concentration of water vapour, percent
    fro = (pa / pr) * (24.0 + 4.04e4 * h * (0.02 + h) / (0.391 + h))
    frn = (pa / pr) * (t / t0) ** -0.5 * (9.0 + 280.0 * h * np.exp(
        -4.170 * ((t / t0) ** (-1.0 / 3.0) - 1.0)))
    return 8.686 * f**2 * (
        1.84e-11 * (pa / pr) ** -1 * (t / t0) ** 0.5
        + (t / t0) ** -2.5 * (0.01275 * np.exp(-2239.1 / t) / (fro + f**2 / fro)
                              + 0.1068 * np.exp(-3352.0 / t) / (frn + f**2 / frn)))


def surface_absorption(space: Space) -> dict[str, NDArray[np.float64]]:
    """Per-octave absorption of walls, floor and ceiling consistent with the target RT60.

    Eyring: T = 0.161 V / (-S ln(1 - a) + 4 m V), solved for the mean absorption a, with the
    air's energy attenuation m at each octave. The bias then moves absorption between surfaces
    while keeping the area-weighted mean.
    """
    lx, ly, lz = space.size_m
    v, s = space.volume, space.surface
    m = air_absorption_db_per_m(OCTAVES) / (10.0 * np.log10(np.e))  # nepers of energy per metre
    t = np.asarray(space.rt60_s, dtype=np.float64)
    mean = 1.0 - np.exp(-np.maximum(0.161 * v / t - 4.0 * m * v, 1e-4) / s)
    bias = {"walls": 1.0, "floor": 1.0, "ceiling": 1.0, **space.absorption_bias}
    areas = {"walls": 2.0 * (lx + ly) * lz, "floor": lx * ly, "ceiling": lx * ly}
    norm = sum(bias[k] * areas[k] for k in areas) / s
    return {k: np.clip(mean * bias[k] / norm, 0.01, 0.99) for k in areas}


@dataclass(frozen=True)
class Image:
    delay_s: float  # extra path over the direct sound
    distance_m: float
    az_deg: float
    el_deg: float
    hits: tuple[int, int, int, int, int, int]  # x0, xL, y0, yL, floor, ceiling


def source_position(space: Space, az_deg: float, el_deg: float, distance_m: float
                    ) -> NDArray[np.float64]:
    """World position of a source; moved inside the room if the requested point is outside."""
    lis = np.asarray(space.listener_m, dtype=np.float64)
    a, e = np.radians(az_deg), np.radians(el_deg)
    u = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
    size = np.asarray(space.size_m)
    # Largest distance along u that stays 0.15 m inside every wall.
    with np.errstate(divide="ignore"):
        lim = np.where(u > 0, (size - 0.15 - lis) / u, np.where(u < 0, (0.15 - lis) / u, np.inf))
    return lis + u * min(distance_m, float(lim.min()))


def image_sources(space: Space, src: NDArray, max_order: int | None = None) -> list[Image]:
    """Every image up to `max_order` wall hits, excluding the direct path, by arrival time.

    Per axis the image coordinate is (1 - 2q) s + 2 n L for q in {0, 1}: |n - q| hits on the wall
    at 0 and |n| on the wall at L (Allen and Berkley 1979).
    """
    order = space.order if max_order is None else max_order
    lis = np.asarray(space.listener_m)
    direct = float(np.linalg.norm(src - lis))
    per_axis = []
    for s, length in zip(src, space.size_m, strict=True):
        opts = []
        for n, q in product(range(-order, order + 1), (0, 1)):
            h0, hl = abs(n - q), abs(n)
            if h0 + hl <= order:
                opts.append(((1 - 2 * q) * s + 2 * n * length, h0, hl))
        per_axis.append(opts)
    out = []
    for (x, x0, xl), (y, y0, yl), (z, z0, zl) in product(*per_axis):
        hits = (x0, xl, y0, yl, z0, zl)
        if not 0 < sum(hits) <= order:
            continue
        vec = np.array([x, y, z]) - lis
        dist = float(np.linalg.norm(vec))
        out.append(Image(delay_s=(dist - direct) / SPEED_OF_SOUND, distance_m=dist,
                         az_deg=float(np.degrees(np.arctan2(vec[1], vec[0]))),
                         el_deg=float(np.degrees(np.arctan2(vec[2], np.hypot(vec[0], vec[1])))),
                         hits=hits))
    out.sort(key=lambda r: r.delay_s)
    return out


def _octave_to_bins(values: NDArray, freqs: NDArray) -> NDArray[np.float64]:
    """Interpolate per-octave values onto FFT bins in log frequency, held flat at the ends."""
    return np.interp(np.log(np.maximum(freqs, 1.0)), np.log(OCTAVES), values)


def early_reflections(space: Space, hrtf: HrtfSet, src: NDArray, n: int) -> NDArray[np.float64]:
    """Binaural response (2, n) of the early reflections; time 0 is the direct sound's arrival.

    The direct sound itself is not included. Each image: minimum-phase head filter at its
    direction with its wall and air attenuation folded into the magnitude, then delayed.
    """
    images = image_sources(space, src)
    out = np.zeros((2, n))
    if not images:
        return out
    lis = np.asarray(space.listener_m)
    direct = float(np.linalg.norm(src - lis))
    alpha = surface_absorption(space)
    tables = (alpha["walls"],) * 4 + (alpha["floor"], alpha["ceiling"])
    freqs = hrtf.freqs
    air = air_absorption_db_per_m(freqs)
    extra = np.zeros((len(images), 1, freqs.size))
    for i, im in enumerate(images):
        refl_db = np.zeros(OCTAVES.size)
        for count, table in zip(im.hits, tables, strict=True):
            if count:
                refl_db += count * 10.0 * np.log10(1.0 - table)
        extra[i, 0] = (_octave_to_bins(refl_db, freqs) - air * (im.distance_m - direct)
                       + 20.0 * np.log10(direct / im.distance_m))
    spec = hrtf.spectra([im.az_deg for im in images], [im.el_deg for im in images], extra)
    big = int(2 ** np.ceil(np.log2(n + hrtf.n_fft)))
    fbig = np.fft.rfftfreq(big, d=1.0 / hrtf.sample_rate)
    irs = np.fft.irfft(spec, n=hrtf.n_fft, axis=-1)
    spec_big = np.fft.rfft(irs, n=big, axis=-1)  # (I, 2, K)
    delays = np.array([im.delay_s for im in images])
    total = np.sum(spec_big * np.exp(-2j * np.pi * fbig * delays[:, None, None]), axis=0)
    return np.fft.irfft(total, n=big, axis=-1)[:, :n]


def _band_weights(freqs: NDArray) -> NDArray[np.float64]:
    """Complementary octave weights (bands, bins) that sum to exactly 1 at every bin.

    Raised-cosine crossfades in log frequency between neighbouring octave centres, so the
    band-wise late fields join without dips or bumps.
    """
    lf = np.log2(np.maximum(freqs, 1.0))
    lc = np.log2(OCTAVES)
    w = np.zeros((OCTAVES.size, freqs.size))
    for b in range(OCTAVES.size):
        if b == 0:
            lo = np.ones_like(lf)
        else:
            x = np.clip((lf - lc[b - 1]) / (lc[b] - lc[b - 1]), 0, 1)
            lo = 0.5 - 0.5 * np.cos(np.pi * x)
        if b == OCTAVES.size - 1:
            hi = np.ones_like(lf)
        else:
            x = np.clip((lf - lc[b]) / (lc[b + 1] - lc[b]), 0, 1)
            hi = 0.5 + 0.5 * np.cos(np.pi * x)
        w[b] = lo * hi
    return w / w.sum(axis=0, keepdims=True)


@lru_cache(maxsize=32)
def _late_unit(rt60: tuple[float, ...], sample_rate: int, n: int) -> NDArray[np.float64]:
    """Two uncorrelated late-field responses (2, n) of unit energy, decaying at `rt60` per band."""
    # The FDN's first output appears after its shortest delay line (about 23 ms); that silence is
    # cut so the late field starts where the room model places it, with no gap in the decay.
    lead = int(fdn_delays(sample_rate).min())
    imp = np.zeros(n + lead)
    imp[0] = 1.0
    n_full = n + lead
    freqs = np.fft.rfftfreq(n_full, d=1.0 / sample_rate)
    weights = _band_weights(freqs)
    total = np.zeros((2, freqs.size), dtype=np.complex128)
    for b, t60 in enumerate(rt60):
        y = fdn_process(imp, sample_rate, t60_low=float(t60), t60_high=float(t60))
        total += weights[b] * np.fft.rfft(y, axis=-1)
    y = np.fft.irfft(total, n=n_full, axis=-1)[:, lead:]
    return y / np.sqrt(np.sum(y**2) / 2.0)


def _balance(s: NDArray, freqs: NDArray) -> NDArray[np.complex128]:
    """Give the second FDN output the first one's power in every 1/3-octave band.

    The coherence mix below gives exactly gamma only when its two inputs have equal power at
    each frequency. The FDN's two output taps are nearly uncorrelated (|r| about 0.1 per band)
    but their powers differ by up to 3 dB from band to band, which pushed the measured coherence
    from 0.35 to 0.59 at 350 Hz. The correction is a smooth gain curve (interpolated in log
    frequency between band centres), so it reshapes the spectrum without ringing in time.
    """
    centres = 1000.0 * 2.0 ** (np.arange(-17, 15) / 3.0)
    centres = centres[centres < freqs[-1] / 1.12]
    ratio_db = []
    for fc in centres:
        band = (freqs >= fc / 1.12) & (freqs < fc * 1.12)
        p1 = float(np.sum(np.abs(s[0, band]) ** 2))
        p2 = float(np.sum(np.abs(s[1, band]) ** 2))
        ratio_db.append(10.0 * np.log10(p1 / p2) if p1 > 0 and p2 > 0 else 0.0)
    # Limited to +/-6 dB: in a very short response a band can hold almost no energy in one
    # output, and boosting it further would amplify numerical noise into a slow tail.
    curve = np.interp(np.log2(np.maximum(freqs, 1.0)), np.log2(centres),
                      np.clip(ratio_db, -6.0, 6.0))
    return np.stack([s[0], s[1] * 10.0 ** (curve / 20.0)])


def late_field(space: Space, hrtf: HrtfSet, n: int) -> NDArray[np.float64]:
    """Binaural late field (2, n) with unit energy per ear and the measured diffuse coherence.

    L = a Y1 + b Y2, R = a Y1 - b Y2 per frequency with a^2 + b^2 = 1 and a^2 - b^2 = gamma(f)
    (Menzer and Faller 2009): uncorrelated inputs give exactly gamma between the ears. Done on
    the whole response at once, so there is no frame to smear it.
    """
    y = _late_unit(tuple(space.rt60_s), hrtf.sample_rate, n)
    # Shaping by per-frequency gains is a convolution; working on a response padded to twice its
    # length keeps the shaping filters' tails from wrapping round onto the decay.
    m = 2 * n
    freqs = np.fft.rfftfreq(m, d=1.0 / hrtf.sample_rate)
    gamma = np.interp(freqs, hrtf.freqs, hrtf.df_coherence)
    a = np.sqrt((1.0 + gamma) / 2.0)
    b = np.sqrt((1.0 - gamma) / 2.0)
    s = _balance(np.fft.rfft(y, n=m, axis=-1), freqs)
    out = np.fft.irfft(np.stack([a * s[0] + b * s[1], a * s[0] - b * s[1]]), n=m, axis=-1)
    return out[:, :n]


def response_length(space: Space, sample_rate: int) -> int:
    """Long enough for a 60 dB decay at the slowest band, plus the pre-delay."""
    return int((max(space.rt60_s) * 1.1 + space.predelay_ms * 1e-3 + 0.05) * sample_rate)


@dataclass(frozen=True)
class Brir:
    direct: NDArray[np.float64]  # (2, n), the direct sound at BASE_DELAY
    early: NDArray[np.float64]
    late: NDArray[np.float64]

    @property
    def total(self) -> NDArray[np.float64]:
        return self.direct + self.early + self.late


def brir(space: Space, hrtf: HrtfSet, az_deg: float, el_deg: float, distance_m: float,
         reverb_scale: float = 1.0, early_scale: float = 1.0,
         direct_extra_db: NDArray | None = None) -> Brir:
    """The three parts of the binaural response for a source at (az, el, distance).

    The direct part has unit gain (distance level cues are applied by the scene, decision 0016);
    `direct_extra_db` (2, K) shapes it, for air absorption and near-field level differences.
    Early and late are scaled so their sum's energy over the direct's is (r / r_c)^2 at the
    source's actual distance, as in a diffuse room, unless the images alone already exceed it.
    """
    sr = hrtf.sample_rate
    n = response_length(space, sr)
    src = source_position(space, az_deg, el_deg, distance_m)
    lis = np.asarray(space.listener_m)
    r = float(np.linalg.norm(src - lis))
    rel = src - lis
    az = float(np.degrees(np.arctan2(rel[1], rel[0])))
    el = float(np.degrees(np.arctan2(rel[2], np.hypot(rel[0], rel[1]))))
    direct = np.zeros((2, n))
    h = hrtf.hrirs(az, el, direct_extra_db)[0]
    direct[:, : h.shape[1]] = h
    early = np.zeros((2, n))
    er = early_reflections(space, hrtf, src, n)
    early[:, BASE_DELAY:] = er[:, : n - BASE_DELAY]
    level = 10.0 ** (space.reflection_level_db / 20.0)
    early *= early_scale * level
    e_direct = float(np.sum(direct**2))
    e_early = float(np.sum(early**2))
    e_reverb = e_direct * (r / space.critical_distance()) ** 2 * level**2
    e_late = max(e_reverb - e_early, 0.25 * e_reverb)
    pre = int(round(space.predelay_ms * 1e-3 * sr))
    # The late field takes over after the first reflections; it begins at the earliest image so
    # there is no gap in the decay, plus the space's pre-delay.
    images = image_sources(space, src)
    start = BASE_DELAY + pre + int(round((images[0].delay_s if images else 0.005) * sr))
    late = np.zeros((2, n))
    lf = late_field(space, hrtf, n - start)
    # A 10 ms raised-cosine onset, so the FDN's first echoes do not click in.
    ramp = min(lf.shape[1], int(0.01 * sr))
    lf[:, :ramp] *= 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, ramp))
    late[:, start:] = lf * np.sqrt(e_late / max(float(np.sum(lf**2)), 1e-30))
    return Brir(direct=direct, early=early, late=late * reverb_scale)
