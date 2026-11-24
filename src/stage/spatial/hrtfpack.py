"""The compact HRTF pack: measured head-related transfer functions as magnitudes plus ITDs.

A measured HRIR has three parts that matter to the ear and behave differently when they are
interpolated between measured directions:

* the interaural time difference (ITD), the main cue for left and right below about 1.5 kHz;
* the magnitude response of each ear (pinna notches, head shadow), which carries elevation and
  front/back;
* the excess phase, which is perceptually negligible for HRTFs once the ITD is kept (Kulkarni,
  Isabelle and Colburn 1999, "Sensitivity of human subjects to head-related transfer-function
  phase spectra", JASA 105(5)).

So each direction is stored as a log magnitude per ear and one ITD, and rebuilt as a minimum-phase
filter plus a pure delay. Interpolating the log magnitudes and the ITD separately is what keeps
moving sources free of the comb filtering that interpolating raw HRIRs (with their different
delays) produces.

Pack file (numpy .npz, no pickles):
    az_deg, el_deg      (M,) float32   directions, azimuth counter-clockwise from the front
                                         (positive to the LEFT, the SOFA convention), elevation up
    logmag_db           (M, 2, K) float16   ear magnitudes in dB on `freqs_hz`, ears (left, right)
    itd_s               (M,) float32   right-ear arrival minus left-ear arrival (positive: the
                                         source is on the left)
    freqs_hz            (K,) float32
    df_mag_db           (2, K) float32 diffuse-field (power average over the sphere) magnitude
    df_coherence        (K,) float32   diffuse-field interaural coherence of the measured set
    meta_json           ()  str        source, licence, attribution, processing parameters
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.signal import butter, resample_poly, sosfiltfilt
from scipy.spatial import ConvexHull

PACK_FORMAT = 1


@dataclass(frozen=True)
class HrtfPack:
    az_deg: NDArray[np.float64]
    el_deg: NDArray[np.float64]
    logmag_db: NDArray[np.float64]  # (M, 2, K)
    itd_s: NDArray[np.float64]
    freqs_hz: NDArray[np.float64]
    df_mag_db: NDArray[np.float64]  # (2, K)
    df_coherence: NDArray[np.float64]  # (K,)
    meta: dict[str, Any]

    @property
    def n_directions(self) -> int:
        return int(self.az_deg.size)


def unit_vectors(az_deg: NDArray, el_deg: NDArray) -> NDArray[np.float64]:
    """(M, 3) unit vectors: x front, y left, z up (SOFA spherical convention)."""
    az, el = np.radians(az_deg), np.radians(el_deg)
    return np.stack([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)], axis=-1)


def minimum_phase_from_logmag(logmag_db: NDArray, n_fft: int) -> NDArray[np.float64]:
    """Real minimum-phase impulse responses (..., n_fft) from log magnitudes on rfft bins.

    The homomorphic method (Oppenheim and Schafer, Discrete-Time Signal Processing, 3rd ed.,
    section 13.8): the real cepstrum of the log magnitude, folded onto positive quefrencies, is
    the complex cepstrum of the minimum-phase system with that magnitude. `n_fft` should be well
    above the filter length so the cepstral aliasing is negligible.
    """
    log_amp = np.asarray(logmag_db, dtype=np.float64) * (np.log(10.0) / 20.0)
    cep = np.fft.irfft(log_amp, n=n_fft, axis=-1)
    fold = np.zeros(n_fft)
    fold[0] = 1.0
    fold[1 : (n_fft + 1) // 2] = 2.0
    if n_fft % 2 == 0:
        fold[n_fft // 2] = 1.0
    spec = np.exp(np.fft.rfft(cep * fold, axis=-1))
    return np.fft.irfft(spec, n=n_fft, axis=-1)


def onset_s(ir: NDArray, sample_rate: float, threshold_db: float = -20.0,
            upsample: int = 8) -> NDArray[np.float64]:
    """Onset time of each impulse response (..., n): first crossing of `threshold_db` re peak.

    The responses are low-passed at 3 kHz first, so the onset is that of the part of the
    wavefront that carries the ITD cue, and upsampled by `upsample` for sub-sample precision.
    The threshold method with a -20 dB threshold on low-passed responses is one of the ITD
    estimators compared by Andreopoulou and Katz (2017, "Identification of perceptually relevant
    methods of inter-aural time difference estimation", JASA 142(2)); it is robust to the
    contralateral ear's low level, where cross-correlation picks side lobes.
    """
    x = np.asarray(ir, dtype=np.float64)
    sos = butter(4, 3000.0, btype="lowpass", fs=sample_rate, output="sos")
    y = np.abs(resample_poly(sosfiltfilt(sos, x, axis=-1), upsample, 1, axis=-1))
    peak = y.max(axis=-1, keepdims=True)
    above = y >= peak * 10.0 ** (threshold_db / 20.0)
    return np.argmax(above, axis=-1) / (sample_rate * upsample)


def sphere_triangles(az_deg: NDArray, el_deg: NDArray) -> NDArray[np.int64]:
    """Triangles (T, 3) of the spherical Delaunay triangulation of the directions.

    For points on a sphere the convex hull's facets are exactly the spherical Delaunay
    triangles, so scipy's Qhull gives the triangulation directly.
    """
    return ConvexHull(unit_vectors(az_deg, el_deg)).simplices.astype(np.int64)


def area_weights(az_deg: NDArray, el_deg: NDArray) -> NDArray[np.float64]:
    """Quadrature weight of each direction: a third of the area of its adjacent triangles.

    Measured grids are denser near the horizon than at the poles, so an unweighted mean over
    directions would over-count the horizon in the diffuse-field average.
    """
    v = unit_vectors(az_deg, el_deg)
    tri = sphere_triangles(az_deg, el_deg)
    a, b, c = v[tri[:, 0]], v[tri[:, 1]], v[tri[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=-1)
    w = np.zeros(v.shape[0])
    for k in range(3):
        np.add.at(w, tri[:, k], area / 3.0)
    return w / w.sum()


def diffuse_field(spec_l: NDArray, spec_r: NDArray, weights: NDArray
                  ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Diffuse-field magnitude (2, K) in dB and interaural coherence (K,) of complex HRTFs (M, K).

    The coherence is the real part of the weighted cross-spectrum over the weighted powers: the
    interaural coherence of an ideal diffuse field heard through this head (Borss and Martin
    2009, "An improved parametric model for perception-based design of virtual acoustics", AES
    35th Conference, use the same definition). It replaces the free-field sin(kd)/kd model.
    """
    w = weights[:, np.newaxis]
    p_l = np.sum(w * np.abs(spec_l) ** 2, axis=0)
    p_r = np.sum(w * np.abs(spec_r) ** 2, axis=0)
    cross = np.sum(w * spec_l * np.conj(spec_r), axis=0)
    coherence = np.real(cross) / np.sqrt(p_l * p_r + 1e-30)
    df = 10.0 * np.log10(np.stack([p_l, p_r]) + 1e-30)
    return df, np.clip(coherence, -1.0, 1.0)


def process_hrirs(ir: NDArray, sample_rate: float, az_deg: NDArray, el_deg: NDArray,
                  n_fft: int = 256, meta: dict[str, Any] | None = None) -> HrtfPack:
    """Turn measured HRIRs (M, 2, N) into a pack: ITDs, log magnitudes, diffuse-field data."""
    ir = np.asarray(ir, dtype=np.float64)
    if ir.ndim != 3 or ir.shape[1] != 2:
        raise ValueError(f"expected HRIRs of shape (M, 2, N), got {ir.shape}")
    n = ir.shape[-1]
    n_fft = max(n_fft, 1 << int(np.ceil(np.log2(n))))
    onsets = onset_s(ir, sample_rate)
    itd = onsets[:, 1] - onsets[:, 0]
    spec = np.fft.rfft(ir, n=n_fft, axis=-1)
    logmag = 20.0 * np.log10(np.abs(spec) + 1e-12)
    weights = area_weights(az_deg, el_deg)
    df_mag, df_coh = diffuse_field(spec[:, 0], spec[:, 1], weights)
    info = dict(meta or {})
    info.update(format=PACK_FORMAT, source_sample_rate=float(sample_rate), n_fft=n_fft,
                itd_method="onset, -20 dB re peak, 3 kHz low-pass, 8x upsampled",
                n_directions=int(ir.shape[0]))
    return HrtfPack(
        az_deg=np.asarray(az_deg, dtype=np.float64), el_deg=np.asarray(el_deg, dtype=np.float64),
        logmag_db=logmag, itd_s=itd, freqs_hz=np.fft.rfftfreq(n_fft, d=1.0 / sample_rate),
        df_mag_db=df_mag, df_coherence=df_coh, meta=info,
    )


def write_pack(pack: HrtfPack, path: str | Path) -> str:
    """Write the pack as a compressed .npz; return its SHA-256."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        np.savez_compressed(
            fh,
            az_deg=pack.az_deg.astype(np.float32), el_deg=pack.el_deg.astype(np.float32),
            logmag_db=pack.logmag_db.astype(np.float16), itd_s=pack.itd_s.astype(np.float32),
            freqs_hz=pack.freqs_hz.astype(np.float32),
            df_mag_db=pack.df_mag_db.astype(np.float32),
            df_coherence=pack.df_coherence.astype(np.float32),
            meta_json=np.array(json.dumps(pack.meta, sort_keys=True)),
        )
    return sha256(path)


def read_pack(path: str | Path) -> HrtfPack:
    with np.load(str(path), allow_pickle=False) as z:
        meta = json.loads(str(z["meta_json"]))
        if meta.get("format") != PACK_FORMAT:
            raise ValueError(f"{path} is pack format {meta.get('format')}, expected {PACK_FORMAT}")
        return HrtfPack(
            az_deg=z["az_deg"].astype(np.float64), el_deg=z["el_deg"].astype(np.float64),
            logmag_db=z["logmag_db"].astype(np.float64), itd_s=z["itd_s"].astype(np.float64),
            freqs_hz=z["freqs_hz"].astype(np.float64),
            df_mag_db=z["df_mag_db"].astype(np.float64),
            df_coherence=z["df_coherence"].astype(np.float64), meta=meta,
        )


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
