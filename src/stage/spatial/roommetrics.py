"""Room-acoustic parameters of impulse responses, after ISO 3382-1:2009.

Used three ways: to test that a room preset produces the RT60 it promises, to compare the
synthetic rooms with the measured SADIE II BRIRs, and in the spatial benchmark.

* Schroeder backward integration of the squared response gives the energy decay curve (EDC).
* T30 is the reverberation time from a line fitted to the EDC between -5 and -35 dB (T20 from -5
  to -25 dB when the decay range is too short), extrapolated to 60 dB.
* EDT is six times the time to fall from 0 to -10 dB.
* DRR is the energy within 2.5 ms of the direct-sound peak over the energy after it.
* IACC_E is the maximum of the normalised interaural cross-correlation within +/-1 ms over the
  first 80 ms (ISO 3382-1 Annex A).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.signal import butter, correlate, sosfiltfilt

OCTAVES_HZ = (125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0)


def octave_filter(x: NDArray, sample_rate: float, centre: float) -> NDArray[np.float64]:
    """Zero-phase fourth-order octave band, so the decay is not delayed by the filter."""
    lo, hi = centre / np.sqrt(2.0), min(centre * np.sqrt(2.0), 0.45 * sample_rate)
    sos = butter(4, [lo, hi], btype="bandpass", fs=sample_rate, output="sos")
    return sosfiltfilt(sos, np.asarray(x, dtype=np.float64), axis=-1)


def schroeder_db(ir: NDArray) -> NDArray[np.float64]:
    """Energy decay curve in dB re its start, of a mono response (or the sum over channels)."""
    e = np.square(np.asarray(ir, dtype=np.float64))
    if e.ndim > 1:
        e = e.sum(axis=0)
    edc = np.cumsum(e[::-1])[::-1]
    return 10.0 * np.log10(edc / max(edc[0], 1e-30) + 1e-30)


def _fit_time(edc_db: NDArray, sample_rate: float, top: float, bottom: float) -> float:
    idx = np.flatnonzero((edc_db <= top) & (edc_db >= bottom))
    if idx.size < 4:
        return float("nan")
    t = idx / sample_rate
    slope, _ = np.polyfit(t, edc_db[idx], 1)
    return float(-60.0 / slope) if slope < 0 else float("nan")


def rt60(ir: NDArray, sample_rate: float) -> float:
    """T30 (T20 if the decay range is too short), seconds."""
    edc = schroeder_db(ir)
    t30 = _fit_time(edc, sample_rate, -5.0, -35.0)
    return t30 if np.isfinite(t30) else _fit_time(edc, sample_rate, -5.0, -25.0)


def edt(ir: NDArray, sample_rate: float) -> float:
    """Early decay time: the 0 to -10 dB slope extrapolated to 60 dB (six times T10)."""
    return _fit_time(schroeder_db(ir), sample_rate, 0.0, -10.0)


def band_rt60(ir: NDArray, sample_rate: float,
              bands: tuple[float, ...] = OCTAVES_HZ) -> dict[str, float]:
    return {f"{int(fc)}": rt60(octave_filter(ir, sample_rate, fc), sample_rate)
            for fc in bands if fc * np.sqrt(2.0) < 0.5 * sample_rate}


def drr_db(ir: NDArray, sample_rate: float, window_ms: float = 2.5) -> float:
    """Direct-to-reverberant ratio of a (channels, n) or (n,) response, channels summed."""
    e = np.square(np.atleast_2d(np.asarray(ir, dtype=np.float64))).sum(axis=0)
    peak = int(np.argmax(e))
    w = int(round(window_ms * 1e-3 * sample_rate))
    direct = e[max(0, peak - w) : peak + w + 1].sum()
    rest = e[peak + w + 1 :].sum()
    return float(10.0 * np.log10(direct / max(rest, 1e-30)))


def iacc(ir: NDArray, sample_rate: float, t0_ms: float = 0.0, t1_ms: float = 80.0) -> float:
    """Max |normalised interaural cross-correlation| within +/-1 ms over [t0, t1] after onset."""
    x = np.asarray(ir, dtype=np.float64)
    onset = int(np.argmax(np.abs(x).max(axis=0) > 0.1 * np.abs(x).max()))
    a = onset + int(round(t0_ms * 1e-3 * sample_rate))
    b = onset + int(round(t1_ms * 1e-3 * sample_rate))
    left, right = x[0, a:b], x[1, a:b]
    den = np.sqrt(np.sum(left**2) * np.sum(right**2))
    if den == 0:
        return 0.0
    xc = correlate(left, right, mode="full", method="fft") / den
    lag = int(round(1e-3 * sample_rate))
    mid = left.size - 1
    return float(np.max(np.abs(xc[mid - lag : mid + lag + 1])))


def brir_metrics(ir: NDArray, sample_rate: float) -> dict[str, object]:
    """The parameters the synthetic rooms are compared on, for a binaural response (2, n)."""
    ir = np.asarray(ir, dtype=np.float64)
    return {
        "sample_rate": float(sample_rate),
        "drr_db": round(drr_db(ir, sample_rate), 2),
        "edt_s": round(edt(ir, sample_rate), 3),
        "rt60_s": {k: round(v, 3) for k, v in band_rt60(ir, sample_rate).items()},
        "iacc_early": round(iacc(ir, sample_rate, 0.0, 80.0), 3),
        "iacc_late": round(iacc(ir, sample_rate, 80.0, 500.0), 3),
    }
