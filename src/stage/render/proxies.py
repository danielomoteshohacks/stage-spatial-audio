"""Objective proxies for the spatialisation spike (decision 0007). Measurements, not judgements.

These show whether a cue is physically present in a render. None of them shows that a listener
hears it; the blind test decides that. The timbre bands are inlined here because the fidelity
guard is not merged yet; move them there when it is.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.signal import butter, sosfilt, sosfiltfilt

from stage.analysis import stft
from stage.render.pinna import FRONT_BANDS, REAR_BANDS

OCTAVES_HZ = (125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0)


def _octave_sos(fc: float, fs: int, order: int = 4):
    return butter(order, [fc / np.sqrt(2.0), fc * np.sqrt(2.0)], btype="band", fs=fs, output="sos")


def octave_powers(x: NDArray[np.float64], fs: int, centres=OCTAVES_HZ) -> NDArray[np.float64]:
    """Power of (channels, n) summed over channels, per octave band (zero-phase Butterworth)."""
    return np.array([np.sum(sosfiltfilt(_octave_sos(fc, fs), x, axis=-1) ** 2) for fc in centres])


def rms_db_change(reference: NDArray, test: NDArray) -> float:
    """Level of `test` relative to `reference`, both summed over channels (dB)."""
    return float(10.0 * np.log10(np.sum(test**2) / np.sum(reference**2)))


def match_rms(reference: NDArray, test: NDArray) -> NDArray:
    return test * np.sqrt(np.sum(reference**2) / np.sum(test**2))


def timbre_deviation_db(reference: NDArray, test: NDArray, fs: int) -> NDArray[np.float64]:
    """Per-octave level of `test` minus `reference` after matching overall RMS (dB)."""
    matched = match_rms(reference, test)
    return 10.0 * np.log10(octave_powers(matched, fs) / octave_powers(reference, fs))


def band_level_db(ears: NDArray[np.complex128], freqs: NDArray, centre: float) -> float:
    """Mean power of a two-ear response (2, bins) over the 1/3-octave around `centre` (dB)."""
    sel = (freqs >= centre * 2 ** (-1 / 6)) & (freqs <= centre * 2 ** (1 / 6))
    return float(10.0 * np.log10(np.mean(np.sum(np.abs(ears[:, sel]) ** 2, axis=0))))


def directional_tilt_db(ears: NDArray[np.complex128], freqs: NDArray) -> float:
    """Mean level in Blauert's front bands minus mean level in the rear bands (dB)."""
    front = np.mean([band_level_db(ears, freqs, fc) for fc, _ in FRONT_BANDS])
    rear = np.mean([band_level_db(ears, freqs, fc) for fc, _ in REAR_BANDS])
    return float(front - rear)


def drr_db(direct: NDArray, reverberant: NDArray) -> float:
    """Direct-to-reverberant energy ratio (dB), both ears summed."""
    return float(10.0 * np.log10(np.sum(direct**2) / np.sum(reverberant**2)))


def iacc(left: NDArray, right: NDArray, fs: int, max_lag_s: float = 0.001) -> float:
    """Maximum |normalised cross-correlation| over lags within +/-1 ms (ISO 3382-1 style)."""
    n = left.size
    spec = np.fft.rfft(left, 2 * n) * np.conj(np.fft.rfft(right, 2 * n))
    xc = np.fft.irfft(spec)
    lag = int(round(max_lag_s * fs))
    window = np.concatenate([xc[: lag + 1], xc[-lag:]])
    return float(np.max(np.abs(window)) / np.sqrt(np.sum(left**2) * np.sum(right**2)))


def band_coherence(
    left: NDArray, right: NDArray, fs: int, centres=OCTAVES_HZ, n_fft: int = 4096
) -> NDArray[np.float64]:
    """Real part of the interaural coherence per octave, from time-averaged cross spectra."""
    spec = stft(np.stack([left, right]), n_fft=n_fft, hop=n_fft // 2)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / fs)
    out = []
    for fc in centres:
        sel = (freqs >= fc / np.sqrt(2.0)) & (freqs < fc * np.sqrt(2.0))
        cross = np.sum(spec[0][:, sel] * np.conj(spec[1][:, sel]))
        p_l = np.sum(np.abs(spec[0][:, sel]) ** 2)
        p_r = np.sum(np.abs(spec[1][:, sel]) ** 2)
        out.append(float(np.real(cross) / np.sqrt(p_l * p_r)))
    return np.array(out)


def rt60_t30(ir: NDArray[np.float64], fs: int, centre: float) -> float:
    """RT60 from T30 in one octave: Schroeder backward integral, line fit from -5 to -35 dB."""
    band = sosfilt(_octave_sos(centre, fs, order=3), ir)
    edc = np.cumsum(band[::-1] ** 2)[::-1]
    edc_db = 10.0 * np.log10(edc / edc[0] + 1e-300)
    sel = (edc_db <= -5.0) & (edc_db >= -35.0)
    t = np.arange(ir.size) / fs
    slope = np.polyfit(t[sel], edc_db[sel], 1)[0]  # dB per second, negative
    return float(-60.0 / slope)


def echo_density(ir: NDArray[np.float64], fs: int, window_s: float = 0.020) -> NDArray[np.float64]:
    """Normalised echo density per sample (Abel and Huang 2006). 1 means Gaussian-like.

    Fraction of samples in a Hann window lying outside one windowed standard deviation, divided
    by erfc(1/sqrt 2) = 0.3173, the fraction expected for Gaussian noise.
    """
    from math import erfc, sqrt

    n_win = int(window_s * fs) | 1
    w = np.hanning(n_win)
    w /= w.sum()
    half = n_win // 2
    padded = np.pad(ir, half)
    # Windowed variance via convolution, then the weighted count of samples above it.
    sigma = np.sqrt(np.convolve(padded**2, w, mode="valid"))
    out = np.empty(ir.size)
    for i in range(ir.size):
        seg = padded[i : i + n_win]
        out[i] = np.sum(w * (np.abs(seg) > sigma[i]))
    return out / erfc(1.0 / sqrt(2.0))
