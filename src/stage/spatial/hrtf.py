"""Head-related filters for any direction, from the measured pack or the analytic fallback.

Directions use the SOFA convention throughout v2: azimuth in degrees counter-clockwise from the
front (positive to the LEFT), elevation positive up.

Interpolation (decision 0012): a query direction falls in one triangle of the spherical Delaunay
triangulation of the measured directions; its log magnitudes are the barycentric blend of the
three corners, and so is its ITD, separately. A minimum-phase filter is then rebuilt from the
blended magnitude and the ITD is applied as a pure (fractional) delay. Blending magnitudes rather
than impulse responses avoids the comb filter that summing three responses with different delays
creates, which is what made moving sources click and phase in v1's sector sum (decision 0010).

Diffuse-field equalisation (decision 0013): the average power response over the sphere is
divided out, so that a sound arriving from everywhere at once is heard with the record's own
tone. The same correction is applied to both ears, so interaural level differences are kept.

The analytic fallback is the v1 head model (spherical head and toy pinna, stage.render) sampled
on 1000 directions and processed exactly like a measured set, so CI and offline runs need no
download and use one code path.
"""

from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.spatial import ConvexHull

from stage.spatial.hrtfpack import (
    HrtfPack,
    area_weights,
    diffuse_field,
    minimum_phase_from_logmag,
    read_pack,
    sha256,
    unit_vectors,
)

#: Where the measured pack is published (tools/hrtf-pack, .github/workflows/hrtf-pack.yml).
PACK_URL = ("https://github.com/danielomoteshohacks/stage-spatial-audio/releases/download/"
            "hrtf-pack-v1/sadie2-d1-ku100.npz")
#: SHA-256 of the published pack; a download that does not match is refused.
PACK_SHA256 = "f99b77ff092e44c3d043060630abb68563e4696ca40b4d3a3c447cca5b084c74"
PACK_FILE = "sadie2-d1-ku100.npz"
#: The measured studio BRIRs of the same release, the reference the room model is fitted to.
BRIR_URL = PACK_URL.rsplit("/", 1)[0] + "/sadie2-d1-brir48k.npz"
BRIR_SHA256 = "7142adb4956c85bbec415c204f04b16ca2ebea88e6cf87f46338d5f798b0ab27"
BRIR_FILE = "sadie2-d1-brir48k.npz"
#: Constant latency of every filter, in samples, that holds the fractional delay's pre-ringing.
BASE_DELAY = 16


def cache_dir() -> Path:
    return Path(os.environ.get("SOUNDSTAGE_CACHE", Path.home() / ".cache" / "soundstage"))


def fibonacci_directions(n: int) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """n nearly uniform directions (the golden-angle spiral), as azimuth and elevation."""
    k = np.arange(n) + 0.5
    z = 1.0 - 2.0 * k / n
    az = np.degrees(np.mod(k * np.pi * (3.0 - np.sqrt(5.0)), 2 * np.pi))
    return np.mod(az + 180.0, 360.0) - 180.0, np.degrees(np.arcsin(z))


#: Smoothing of the analytic fallback (ipsilateral, contralateral, high-frequency factor): the
#: toy pinna has a discontinuity on the interaural axis, which this keeps under the continuity
#: target (measured in tests/unit/test_hrtf.py).
ANALYTIC_SMOOTHING = (10.0, 16.0, 1.5)


def analytic_pack(sample_rate: int = 48000, n_dir: int = 3000, n_fft: int = 512,
                  n_grid: int = 1500) -> HrtfPack:
    """The v1 spherical-head and pinna model sampled on a uniform grid, as a smoothed pack."""
    from stage.render.headmodel import ear_delays_s
    from stage.render.pinna import ear_filters
    from stage.spatial.hrtfpack import spatially_smooth

    az, el = fibonacci_directions(n_dir)
    # v1 measures azimuth to the right; v2 to the left.
    spec = ear_filters(-az, el, n_fft=n_fft, sample_rate=sample_rate, pinna=True)
    logmag = 20.0 * np.log10(np.abs(spec) + 1e-12)
    # The spherical head's ITD depends on the lateral angle only: asin(sin az cos el).
    lateral = np.degrees(np.arcsin(np.sin(np.radians(az)) * np.cos(np.radians(el))))
    d_left, d_right = ear_delays_s(-lateral)
    w = area_weights(az, el)
    df, coh = diffuse_field(spec[:, 0], spec[:, 1], w)
    raw = HrtfPack(az_deg=az, el_deg=el, logmag_db=logmag, itd_s=d_right - d_left,
                   freqs_hz=np.fft.rfftfreq(n_fft, d=1.0 / sample_rate), df_mag_db=df,
                   df_coherence=coh, meta={"dataset": "analytic", "format": 1,
                                           "description": "v1 spherical head and pinna model"})
    s_ipsi, s_contra, high = ANALYTIC_SMOOTHING
    return spatially_smooth(raw, s_ipsi, s_contra, target=fibonacci_directions(n_grid),
                            high_scale=high)


def find_pack() -> Path | None:
    """The measured pack, if it is cached or named by SOUNDSTAGE_HRTF_PACK. Never downloads."""
    env = os.environ.get("SOUNDSTAGE_HRTF_PACK")
    if env:
        return Path(env) if Path(env).is_file() else None
    path = cache_dir() / "hrtf" / PACK_FILE
    return path if path.is_file() else None


def _download(url: str, sha: str, target: Path, timeout_s: float) -> Path:
    if target.is_file() and sha256(target) == sha:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": "soundstage"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp, open(tmp, "wb") as fh:
        fh.write(resp.read())
    if sha256(tmp) != sha:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"the file downloaded from {url} does not match its published checksum")
    tmp.replace(target)
    return target


def download_pack(timeout_s: float = 60.0) -> Path:
    """Fetch the measured pack into the cache, checking its SHA-256. Used by the Space at start."""
    return _download(PACK_URL, PACK_SHA256, cache_dir() / "hrtf" / PACK_FILE, timeout_s)


def download_brirs(timeout_s: float = 60.0) -> Path:
    """Fetch the measured SADIE II studio BRIRs (the room model's reference) into the cache."""
    return _download(BRIR_URL, BRIR_SHA256, cache_dir() / "hrtf" / BRIR_FILE, timeout_s)


def find_brirs() -> Path | None:
    path = cache_dir() / "hrtf" / BRIR_FILE
    return path if path.is_file() else None


def third_octave_smooth(logmag_db: NDArray, freqs: NDArray, fraction: float = 3.0
                        ) -> NDArray[np.float64]:
    """Smooth log magnitudes over a 1/`fraction`-octave window in power, along the last axis."""
    p = 10.0 ** (np.asarray(logmag_db) / 10.0)
    out = np.empty_like(p)
    half = 2.0 ** (1.0 / (2.0 * fraction))
    for k, f in enumerate(freqs):
        if f <= 0:
            out[..., k] = p[..., k]
            continue
        sel = (freqs >= f / half) & (freqs <= f * half)
        out[..., k] = p[..., sel].mean(axis=-1)
    return 10.0 * np.log10(out + 1e-30)


@dataclass
class Interpolation:
    idx: NDArray[np.int64]  # (Q, 3) corner directions
    w: NDArray[np.float64]  # (Q, 3) barycentric weights, non-negative, summing to 1


class HrtfSet:
    """Filters at one sample rate and FFT size, interpolated over the sphere."""

    def __init__(self, pack: HrtfPack, sample_rate: int, n_fft: int = 512,
                 diffuse_eq: bool = True) -> None:
        self.pack = pack
        self.sample_rate = int(sample_rate)
        self.n_fft = int(n_fft)
        self.freqs = np.fft.rfftfreq(self.n_fft, d=1.0 / self.sample_rate)
        # Resample the magnitudes onto this rate's bins: a minimum-phase filter is defined by its
        # magnitude alone, so sampling the magnitude at new frequencies is a resampling. Above the
        # pack's highest bin (a 96 kHz render of a 48 kHz pack) the last value is held.
        src = pack.freqs_hz
        mag = np.empty(pack.logmag_db.shape[:2] + (self.freqs.size,))
        for ear in range(2):
            for i in range(pack.logmag_db.shape[0]):
                mag[i, ear] = np.interp(self.freqs, src, pack.logmag_db[i, ear])
        df = np.stack([np.interp(self.freqs, src, pack.df_mag_db[e]) for e in range(2)])
        self.df_coherence = np.interp(self.freqs, src, pack.df_coherence)
        self.diffuse_eq_db = third_octave_smooth(df.mean(axis=0), self.freqs)
        if diffuse_eq:
            mag = mag - self.diffuse_eq_db
        self.logmag = mag
        self.itd = pack.itd_s
        self.vectors = unit_vectors(pack.az_deg, pack.el_deg)
        hull = ConvexHull(self.vectors)
        self.simplices = hull.simplices.astype(np.int64)
        self.normals = hull.equations[:, :3]
        self.offsets = hull.equations[:, 3]
        corners = self.vectors[self.simplices]  # (T, 3 corners, 3 coords)
        self.inverse = np.linalg.inv(np.transpose(corners, (0, 2, 1)))

    @property
    def name(self) -> str:
        return str(self.pack.meta.get("dataset", "unknown"))

    def interpolation(self, az_deg: ArrayLike, el_deg: ArrayLike = 0.0) -> Interpolation:
        az = np.atleast_1d(np.asarray(az_deg, dtype=np.float64))
        el = np.broadcast_to(np.asarray(el_deg, dtype=np.float64), az.shape)
        v = unit_vectors(az, el)  # (Q, 3)
        # The ray from the centre along v leaves the hull through exactly one facet: the one it
        # reaches first (smallest positive distance along the ray).
        dots = v @ self.normals.T  # (Q, T)
        with np.errstate(divide="ignore", invalid="ignore"):
            dist = np.where(dots > 1e-12, -self.offsets[np.newaxis, :] / dots, np.inf)
        face = np.argmin(dist, axis=1)
        w = np.einsum("qij,qj->qi", self.inverse[face], v)
        w = np.clip(w, 0.0, None)
        w /= w.sum(axis=1, keepdims=True)
        return Interpolation(idx=self.simplices[face], w=w)

    def logmag_db(self, az_deg: ArrayLike, el_deg: ArrayLike = 0.0) -> NDArray[np.float64]:
        """(Q, 2, K) interpolated ear magnitudes in dB."""
        it = self.interpolation(az_deg, el_deg)
        return np.einsum("qc,qcek->qek", it.w, self.logmag[it.idx])

    def itd_s(self, az_deg: ArrayLike, el_deg: ArrayLike = 0.0) -> NDArray[np.float64]:
        it = self.interpolation(az_deg, el_deg)
        return np.sum(it.w * self.itd[it.idx], axis=1)

    def spectra(self, az_deg: ArrayLike, el_deg: ArrayLike = 0.0,
                extra_db: NDArray | None = None) -> NDArray[np.complex128]:
        """(Q, 2, K) complex responses: minimum phase, the ITD and the base delay.

        `extra_db` (broadcast to (Q, 2, K)) is added to the magnitude before the minimum-phase
        step, so wall absorption, air absorption and distance shaping stay minimum phase too.
        """
        mag = self.logmag_db(az_deg, el_deg)
        if extra_db is not None:
            mag = mag + extra_db
        h = np.fft.rfft(minimum_phase_from_logmag(mag, self.n_fft), axis=-1)
        itd = self.itd_s(az_deg, el_deg)
        delays = BASE_DELAY / self.sample_rate + np.stack(
            [np.maximum(0.0, -itd), np.maximum(0.0, itd)], axis=-1)
        return h * np.exp(-2j * np.pi * self.freqs * delays[..., np.newaxis])

    def hrirs(self, az_deg: ArrayLike, el_deg: ArrayLike = 0.0,
              extra_db: NDArray | None = None) -> NDArray[np.float64]:
        """(Q, 2, n_fft) impulse responses; the direct sound arrives at BASE_DELAY samples."""
        return np.fft.irfft(self.spectra(az_deg, el_deg, extra_db), n=self.n_fft, axis=-1)


@lru_cache(maxsize=4)
def _load(path: str | None, sample_rate: int, n_fft: int) -> HrtfSet:
    pack = read_pack(path) if path else analytic_pack()
    return HrtfSet(pack, sample_rate, n_fft)


def get_hrtf(sample_rate: int, n_fft: int = 512, prefer: str = "measured",
             head: str | None = None) -> HrtfSet:
    """The measured set if its pack is available locally, else the analytic fallback.

    `head` names a SADIE II subject (stage.spatial.heads); D1 or None is the original pack. A
    head that is not on this machine falls back to D1, then to the analytic head: rendering
    never fails for want of a download (the plan records which head was used).
    """
    path: Path | None = None
    if prefer == "measured":
        if head and head.upper() != "D1":
            from stage.spatial.heads import pack_path

            p = pack_path(head.upper())
            path = p if p.is_file() else None
        path = path or find_pack()
    return _load(str(path) if path else None, int(sample_rate), int(n_fft))


#: The continuity target of decision 0012: band level change per degree of source movement.
MAX_DB_PER_DEGREE = 0.5
CONTINUITY_ELEVATIONS = (-30.0, 0.0, 30.0, 60.0)


def max_band_gradient(hs: HrtfSet, step_deg: float = 0.25,
                      elevations: tuple[float, ...] = CONTINUITY_ELEVATIONS,
                      azimuths: tuple[float, ...] = (0.0, 45.0, 90.0, 135.0, 180.0),
                      low_hz: float = 100.0, high_hz: float = 16000.0
                      ) -> dict[str, dict[str, float]]:
    """Largest 1/3-octave band level change per degree, for azimuth and for elevation sweeps.

    Azimuth sweeps go once round the head at each of `elevations`; elevation sweeps go from -40
    to +85 degrees at each of `azimuths`. Each result says where the worst change is. Bands below
    one bin of `hs` are skipped, so measure with a long FFT (4096).
    """
    from stage.guard.checks import third_octave_bands

    centres, lo, hi = third_octave_bands(low_hz, min(high_hz, hs.sample_rate / 2.2))
    sel = [(hs.freqs >= a) & (hs.freqs < b) for a, b in zip(lo, hi, strict=True)]
    keep = [k for k, s in enumerate(sel) if s.any()]

    def sweep(az: NDArray, el: NDArray, worst: dict[str, float]) -> None:
        p = 10.0 ** (hs.logmag_db(az, el) / 10.0)
        bands = np.stack([10.0 * np.log10(p[..., sel[k]].mean(axis=-1)) for k in keep], -1)
        d = np.abs(np.diff(bands, axis=0)) / step_deg
        q, ear, b = np.unravel_index(int(np.argmax(d)), d.shape)
        if d[q, ear, b] > worst["db_per_degree"]:
            worst.update(db_per_degree=float(d[q, ear, b]), az_deg=float(az[q]),
                         el_deg=float(el[q]), band_hz=float(centres[keep[b]]), ear=int(ear))

    def blank() -> dict[str, float]:
        return {"db_per_degree": 0.0, "az_deg": 0.0, "el_deg": 0.0, "band_hz": 0.0, "ear": 0}

    out = {"azimuth": blank(), "elevation": blank()}
    az = np.arange(-180.0, 180.0 + step_deg, step_deg)
    for e in elevations:
        sweep(az, np.full_like(az, e), out["azimuth"])
    el = np.arange(-40.0, 85.0, step_deg)
    for a in azimuths:
        sweep(np.full_like(el, a), el, out["elevation"])
    return out


def choose_smoothing(pack: HrtfPack, sample_rate: int = 48000, n_grid: int = 4000,
                     candidates: tuple[tuple[float, float, float], ...] = (
                         (2.0, 6.0, 2.0), (3.0, 8.0, 2.0), (4.0, 10.0, 2.0), (5.0, 12.0, 2.0),
                         (6.0, 14.0, 2.0), (8.0, 16.0, 2.0))
                     ) -> tuple[HrtfPack, dict[str, dict[str, float]]]:
    """Resample onto a uniform grid with the least smoothing that keeps azimuth sweeps under
    MAX_DB_PER_DEGREE, and report both sweep directions (decision 0012).

    Only azimuth movement is gated: the elevation notch of the pinna sweeps through the 6 to
    10 kHz bands faster than 0.5 dB per degree because that sweep is the elevation cue itself, so
    smoothing it below the target would remove what makes height audible.
    """
    from stage.spatial.hrtfpack import spatially_smooth

    grid = fibonacci_directions(n_grid)
    result = None
    for s_ipsi, s_contra, high in candidates:
        cand = spatially_smooth(pack, s_ipsi, s_contra, target=grid, high_scale=high)
        worst = max_band_gradient(HrtfSet(cand, sample_rate, 4096, diffuse_eq=False))
        result = (cand, worst)
        if worst["azimuth"]["db_per_degree"] <= MAX_DB_PER_DEGREE:
            break
    assert result is not None
    result[0].meta["continuity_db_per_degree"] = {
        k: round(v["db_per_degree"], 3) for k, v in result[1].items()}
    return result
