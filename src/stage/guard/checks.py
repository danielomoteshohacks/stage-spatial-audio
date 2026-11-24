"""Fidelity checks: compare a rendered binaural signal with the stereo it was rendered from.

Each check returns a frozen dataclass with its measurements and a `passed` field. The thresholds
are module constants so the report can print them; `configs/thresholds/` is meant to hold them
once they are tuned by listening.

All checks take (2, samples) float arrays of the same length at the same sample rate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.signal import welch

#: Alignment passes when |lag| is below this.
ALIGNMENT_MAX_MS = 1.0
#: Search range for the lag. The cross-correlation of music has side peaks at the beat period
#: (hundreds of ms), which a full-length search could pick when the render is not identical to
#: the original. A render-induced delay is a few ms, so 100 ms is generous; a larger delay lands
#: on the edge of the range and still fails.
ALIGNMENT_SEARCH_MS = 100.0

#: Loudness passes when the whole-clip RMS difference is within this.
LOUDNESS_MAX_DB = 0.5
LOUDNESS_WINDOW_S = 3.0

#: Timbre passes when every band deviates by at most this.
TIMBRE_MAX_DB = 1.5
TIMBRE_LOW_HZ = 50.0
TIMBRE_HIGH_HZ = 16000.0

#: Upper edge of the low-end check.
LOW_END_HZ = 120.0


def _check_pair(original: NDArray, rendered: NDArray) -> tuple[NDArray, NDArray]:
    original = np.asarray(original, dtype=np.float64)
    rendered = np.asarray(rendered, dtype=np.float64)
    for name, x in (("original", original), ("rendered", rendered)):
        if x.ndim != 2 or x.shape[0] != 2:
            raise ValueError(f"{name} must be stereo of shape (2, samples), got {x.shape}")
    if original.shape != rendered.shape:
        raise ValueError(f"shapes differ: original {original.shape}, rendered {rendered.shape}")
    if original.shape[1] == 0:
        raise ValueError("signals are empty")
    return original, rendered


def _power_ratio_db(num: float, den: float) -> float:
    """10 log10(num / den), with two silences counted as equal rather than as NaN."""
    if num == 0.0 and den == 0.0:
        return 0.0
    if den == 0.0:
        return float("inf")
    if num == 0.0:
        return float("-inf")
    return float(10.0 * np.log10(num / den))


def _mean_square(x: NDArray) -> float:
    return float(np.mean(np.square(x)))


# --------------------------------------------------------------------------------------------
# 1. Alignment


@dataclass(frozen=True)
class AlignmentResult:
    lag_samples: int  # positive: the render is late
    lag_ms: float
    peak_correlation: float  # normalised, in [-1, 1]; near 0 the lag is unreliable, < 0 inverted
    passed: bool


def _onset_function(x: NDArray, sample_rate: float, hop: int) -> NDArray[np.float64]:
    """Rise of the smoothed high-band (above 1 kHz) amplitude envelope, per hop.

    The amplitude envelope is averaged over 4 ms, so the noise of single short frames does not
    make false onsets; only its increases count, so reverberation (which only decays) adds
    nothing and each transient marks the time it starts.
    """
    from scipy.ndimage import uniform_filter1d
    from scipy.signal import butter, sosfiltfilt

    sos = butter(4, min(1000.0, 0.4 * sample_rate), btype="highpass", fs=sample_rate,
                 output="sos")
    y = np.abs(sosfiltfilt(sos, x))
    n = y.size // hop
    env = y[: n * hop].reshape(n, hop).mean(axis=1)
    env = uniform_filter1d(env, size=max(1, int(round(0.004 * sample_rate / hop))))
    return np.maximum(np.diff(env, prepend=env[:1]), 0.0)


def check_alignment(
    original: NDArray, rendered: NDArray, sample_rate: float,
    search_ms: float = ALIGNMENT_SEARCH_MS,
) -> AlignmentResult:
    """Lag between the original mid (L + R) / 2 and the rendered sum (L + R) / 2.

    The mid and the sum are compared because a binaural render moves energy between the ears
    (head shadow, ear delays) but keeps the sum close to the original's mid.

    Two steps. First the onset functions of both (the rise of high-band energy, 0.5 ms hops)
    are cross-correlated: transients mark time even in a reverberant render, where a waveform
    cross-correlation is dominated by reverberation and by the periodic, sign-alternating side
    peaks of bass notes and sustained chords. Then the 1 to 8 kHz waveforms are cross-correlated
    within +/-3 ms of that lag, and the earliest peak within 12 dB of the largest is taken (one
    before zero lag only if it is nearly the largest).
    Material without transients falls back to the
    waveform correlation over the whole range. The reported correlation is the normalised
    correlation at the lag, so an inverted render still shows a negative value.
    """
    original, rendered = _check_pair(original, rendered)
    mid = original.mean(axis=0)
    rsum = rendered.mean(axis=0)
    norm = np.sqrt(np.sum(mid**2) * np.sum(rsum**2))
    if norm == 0.0:
        # No lag can be estimated against silence. A silent render is caught by the loudness check.
        return AlignmentResult(0, 0.0, 0.0, True)
    nfft = 1 << int(np.ceil(np.log2(mid.size + rsum.size)))
    cross = np.fft.rfft(rsum, nfft) * np.conj(np.fft.rfft(mid, nfft))
    plain = np.fft.irfft(cross, nfft)
    # The fine search uses 1 to 8 kHz only: below that, the periods of notes are long enough
    # to put a correlation peak anywhere within the +/-1 ms window.
    # The fine search uses 1 to 8 kHz only: below that, the periods of notes are long enough
    # to put a correlation peak anywhere within the window.
    freqs = np.fft.rfftfreq(nfft, d=1.0 / sample_rate)
    banded = np.fft.irfft(cross * ((freqs >= 1000.0) & (freqs <= 8000.0)), nfft)
    max_lag = int(round(search_ms * 1e-3 * sample_rate))

    def best_in(lo: int, hi: int, values: NDArray, earliest: bool = False) -> int:
        lags = np.arange(lo, hi + 1)
        mag = np.abs(values[lags % nfft])
        if earliest:
            # The direct sound arrives before its reflections, so the earliest local peak within
            # 12 dB of the largest is taken (in a reverberant multi-source scene the reflection
            # cluster can outweigh the direct sound by more than 6 dB). A peak before zero lag
            # (a render ahead of the original) counts only when it is within 10 percent of the
            # largest: otherwise it is
            # a side peak of a sustained note, and a renderer cannot play a sound before it.
            peaks = np.zeros(mag.size, dtype=bool)
            peaks[1:-1] = (mag[1:-1] >= mag[:-2]) & (mag[1:-1] >= mag[2:])
            peaks[int(np.argmax(mag))] = True
            ok = peaks & (mag >= 0.25 * mag.max()) & ((lags >= 0) | (mag >= 0.9 * mag.max()))
            i = int(np.argmax(ok))
            # Snap to the largest value within 0.25 ms: a band-limited correlation has side
            # lobes a few samples either side of its true peak.
            w = max(1, int(round(0.00025 * sample_rate)))
            lo, hi = max(0, i - w), min(mag.size, i + w + 1)
            return int(lags[lo + int(np.argmax(mag[lo:hi]))])
        return int(lags[int(np.argmax(mag))])

    hop = max(1, int(round(0.0005 * sample_rate)))
    oo = _onset_function(mid, sample_rate, hop)
    orr = _onset_function(rsum, sample_rate, hop)
    lag = None
    if oo.size > 8 and oo.max() > 1e-9:
        m = 1 << int(np.ceil(np.log2(2 * oo.size)))
        xc = np.fft.irfft(np.fft.rfft(orr, m) * np.conj(np.fft.rfft(oo, m)), m)
        k = max_lag // hop
        cand = np.concatenate([np.arange(0, k + 1), np.arange(-k, 0)])
        coarse = int(cand[int(np.argmax(xc[cand % m]))]) * hop
        # Early reflections add their own onsets a few milliseconds after the direct sound and
        # pull the envelope correlation late, so the fine search reaches 3 ms either side.
        refine = int(round(0.003 * sample_rate)) + hop
        lag = best_in(max(-max_lag, coarse - refine), min(max_lag, coarse + refine), banded,
                      earliest=True)
    if lag is None:
        lag = best_in(-max_lag, max_lag, plain)
    peak = float(plain[lag % nfft] / norm)
    lag_ms = 1e3 * lag / sample_rate
    return AlignmentResult(lag, lag_ms, peak, abs(lag_ms) < ALIGNMENT_MAX_MS)


# --------------------------------------------------------------------------------------------
# 2. Loudness


@dataclass(frozen=True)
class LoudnessResult:
    original_db: float  # RMS over both channels, dBFS
    rendered_db: float
    difference_db: float  # rendered minus original
    window_starts_s: tuple[float, ...]
    window_difference_db: tuple[float, ...]
    max_window_difference_db: float  # largest |difference| over the windows
    passed: bool


def check_loudness(
    original: NDArray, rendered: NDArray, sample_rate: float,
    window_s: float = LOUDNESS_WINDOW_S,
) -> LoudnessResult:
    """RMS difference over the whole clip and per non-overlapping window.

    RMS, not LUFS: a K-weighted loudness needs a filter design that is not in the codebase yet,
    and for comparing a render with its own source a plain power ratio is what the renderer's
    level normalisation (decision 0006) is defined against. The last window is shorter when the
    clip is not a multiple of `window_s`; it is kept so the end of the clip is checked too.
    Only the whole-clip difference is gated; the windows show where a difference comes from.
    """
    original, rendered = _check_pair(original, rendered)
    ms_o, ms_r = _mean_square(original), _mean_square(rendered)
    diff = _power_ratio_db(ms_r, ms_o)

    hop = max(1, int(round(window_s * sample_rate)))
    starts = range(0, original.shape[1], hop)
    win_diff = tuple(
        _power_ratio_db(
            _mean_square(rendered[:, s : s + hop]), _mean_square(original[:, s : s + hop])
        )
        for s in starts
    )
    return LoudnessResult(
        original_db=_power_ratio_db(ms_o, 1.0),
        rendered_db=_power_ratio_db(ms_r, 1.0),
        difference_db=diff,
        window_starts_s=tuple(s / sample_rate for s in starts),
        window_difference_db=win_diff,
        max_window_difference_db=float(max(abs(d) for d in win_diff)),
        passed=abs(diff) <= LOUDNESS_MAX_DB,
    )


# --------------------------------------------------------------------------------------------
# 3. Timbre deviation


def third_octave_bands(
    low_hz: float = TIMBRE_LOW_HZ, high_hz: float = TIMBRE_HIGH_HZ
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Base-10 1/3-octave bands (IEC 61260): exact centres, lower and upper edges.

    Centres are 1000 * 10^(k/10), so 50 Hz is the k = -13 band (exact centre 50.1 Hz) and
    16 kHz is k = 12 (15.85 kHz). Bands whose nominal centre is within the range are returned.
    """
    k_low = int(np.ceil(10.0 * np.log10(low_hz / 1000.0) - 0.05))
    k_high = int(np.floor(10.0 * np.log10(high_hz / 1000.0) + 0.05))
    centres = 1000.0 * 10.0 ** (np.arange(k_low, k_high + 1) / 10.0)
    half = 10.0 ** (1.0 / 20.0)
    return centres, centres / half, centres * half


#: IEC 61260 nominal mantissas, one per 1/3 octave in a decade. Rounding the exact centres would
#: give 79 Hz and 316 Hz where everyone reads 80 and 315, which makes failing-band lists confusing.
_NOMINAL_MANTISSA = (10.0, 12.5, 16.0, 20.0, 25.0, 31.5, 40.0, 50.0, 63.0, 80.0)


def _nominal_hz(fc: float) -> str:
    """Nominal label of an exact base-10 band centre, e.g. 79.4 -> "80", 3162 -> "3.15k"."""
    k = int(round(10.0 * np.log10(fc / 10.0)))  # bands above 10 Hz
    value = _NOMINAL_MANTISSA[k % 10] * 10.0 ** (k // 10)
    return f"{value:g}" if value < 1000.0 else f"{value / 1000.0:g}k"


@dataclass(frozen=True)
class TimbreResult:
    band_centres_hz: tuple[float, ...]
    band_labels: tuple[str, ...]
    band_difference_db: tuple[float, ...]  # after removing level_offset_db
    level_offset_db: float  # broadband power difference that was removed first
    max_deviation_db: float
    max_deviation_band: str
    failing_bands: tuple[str, ...]
    passed: bool


def _welch_segment(sample_rate: float, n_samples: int) -> int:
    """Welch segment length: about 2.7 Hz resolution at 44.1 kHz (16384 samples).

    The 50 Hz band is only 11.6 Hz wide; at this resolution it spans four bins, so its power is
    not decided by one or two bins at the window's skirt. Clips shorter than a segment use the
    whole clip as one segment.
    """
    target = 2 ** int(np.ceil(np.log2(sample_rate / 2.7)))
    return int(min(target, n_samples))


def check_timbre(original: NDArray, rendered: NDArray, sample_rate: float) -> TimbreResult:
    """Long-term average spectrum difference in 1/3-octave bands from 50 Hz to 16 kHz.

    The broadband level difference is removed first (the render is compared as if RMS-matched,
    which is how scripts/render_clip.py writes it and how 0007's P5 measures timbre), so a pure
    gain change is reported by the loudness check only. The two ears' powers are summed, because
    the question is the overall colour, not the inter-ear balance the head model creates on
    purpose. Bands above Nyquist are dropped.
    """
    original, rendered = _check_pair(original, rendered)
    nper = _welch_segment(sample_rate, original.shape[1])
    freqs, p_o = welch(original, fs=sample_rate, nperseg=nper, axis=-1)
    _, p_r = welch(rendered, fs=sample_rate, nperseg=nper, axis=-1)
    p_o, p_r = p_o.sum(axis=0), p_r.sum(axis=0)

    centres, lo, hi = third_octave_bands()
    keep = hi <= sample_rate / 2.0
    centres, lo, hi = centres[keep], lo[keep], hi[keep]
    offset = _power_ratio_db(_mean_square(rendered), _mean_square(original))
    diffs = []
    for f_lo, f_hi in zip(lo, hi, strict=True):
        band = (freqs >= f_lo) & (freqs < f_hi)
        d = _power_ratio_db(float(p_r[band].sum()), float(p_o[band].sum()))
        # A finite offset only: if either clip is silent overall the band values are inf anyway.
        diffs.append(d - offset if np.isfinite(offset) else d)
    diffs_arr = np.asarray(diffs)
    labels = tuple(_nominal_hz(fc) for fc in centres)
    worst = int(np.argmax(np.abs(diffs_arr)))
    failing = tuple(lab for lab, d in zip(labels, diffs_arr, strict=True) if abs(d) > TIMBRE_MAX_DB)
    return TimbreResult(
        band_centres_hz=tuple(float(c) for c in centres),
        band_labels=labels,
        band_difference_db=tuple(float(d) for d in diffs_arr),
        level_offset_db=offset,
        max_deviation_db=float(abs(diffs_arr[worst])),
        max_deviation_band=labels[worst],
        failing_bands=failing,
        passed=not failing,
    )


# --------------------------------------------------------------------------------------------
# 4. Low end


@dataclass(frozen=True)
class LowEndResult:
    original_db: float  # mean power below LOW_END_HZ over both channels, dBFS
    rendered_db: float
    difference_db: float
    rendered_correlation: float  # left/right correlation of the render below LOW_END_HZ
    original_correlation: float  # the same for the original, for context
    passed: bool | None  # None: no threshold has been set for this check yet


def _lowpass_fft(x: NDArray, sample_rate: float, cutoff_hz: float) -> NDArray:
    """Brick-wall low-pass by zeroing FFT bins, DC excluded.

    A brick wall makes "energy below 120 Hz" mean exactly that, with no filter-order choice to
    document. It is circular, which only matters within a few periods of the clip edges. DC is
    excluded because an offset is not bass and would dominate the correlation.
    """
    spec = np.fft.rfft(x, axis=-1)
    freqs = np.fft.rfftfreq(x.shape[-1], d=1.0 / sample_rate)
    spec[..., (freqs <= 0.0) | (freqs >= cutoff_hz)] = 0.0
    return np.fft.irfft(spec, n=x.shape[-1], axis=-1)


def _lr_correlation(x: NDArray) -> float:
    """Zero-lag normalised correlation of the two channels; 0 when either is silent."""
    den = np.sqrt(np.sum(x[0] ** 2) * np.sum(x[1] ** 2))
    return float(np.sum(x[0] * x[1]) / den) if den > 0 else 0.0


def check_low_end(original: NDArray, rendered: NDArray, sample_rate: float) -> LowEndResult:
    """Energy below 120 Hz in both signals, and the render's left/right correlation there.

    Not gated: the task that introduced it asks only for the numbers, and no threshold is in the
    specification or configs/thresholds yet. The original's correlation is reported next to the
    render's so a decorrelated bass can be told apart from one the renderer decorrelated.
    """
    original, rendered = _check_pair(original, rendered)
    lo_o = _lowpass_fft(original, sample_rate, LOW_END_HZ)
    lo_r = _lowpass_fft(rendered, sample_rate, LOW_END_HZ)
    ms_o, ms_r = _mean_square(lo_o), _mean_square(lo_r)
    return LowEndResult(
        original_db=_power_ratio_db(ms_o, 1.0),
        rendered_db=_power_ratio_db(ms_r, 1.0),
        difference_db=_power_ratio_db(ms_r, ms_o),
        rendered_correlation=_lr_correlation(lo_r),
        original_correlation=_lr_correlation(lo_o),
        passed=None,
    )


# --------------------------------------------------------------------------------------------
# Combined report


@dataclass(frozen=True)
class GuardReport:
    sample_rate: float
    duration_s: float
    alignment: AlignmentResult
    loudness: LoudnessResult
    timbre: TimbreResult
    low_end: LowEndResult

    @property
    def passed(self) -> bool:
        """True when every gated check passed; ungated checks (passed is None) do not count."""
        results = (self.alignment, self.loudness, self.timbre, self.low_end)
        return all(r.passed for r in results if r.passed is not None)


def guard_report(original: NDArray, rendered: NDArray, sample_rate: float) -> GuardReport:
    """Run every check on one render. See the individual `check_*` functions."""
    original, rendered = _check_pair(original, rendered)
    return GuardReport(
        sample_rate=float(sample_rate),
        duration_s=original.shape[1] / sample_rate,
        alignment=check_alignment(original, rendered, sample_rate),
        loudness=check_loudness(original, rendered, sample_rate),
        timbre=check_timbre(original, rendered, sample_rate),
        low_end=check_low_end(original, rendered, sample_rate),
    )


def _verdict(passed: bool | None) -> str:
    return "n/a" if passed is None else ("pass" if passed else "FAIL")


def format_report(report: GuardReport) -> str:
    """Plain-text table of a report, for the command line."""
    a, ld, t, le = report.alignment, report.loudness, report.timbre, report.low_end
    rows = [
        ("alignment",
         f"{a.lag_samples:+d} samples ({a.lag_ms:+.3f} ms), peak corr {a.peak_correlation:.3f}",
         f"|lag| < {ALIGNMENT_MAX_MS:g} ms", _verdict(a.passed)),
        ("loudness", f"{ld.difference_db:+.2f} dB (worst {LOUDNESS_WINDOW_S:g} s window "
         f"{ld.max_window_difference_db:.2f} dB)", f"within {LOUDNESS_MAX_DB:g} dB",
         _verdict(ld.passed)),
        ("timbre", f"max {t.max_deviation_db:.2f} dB at {t.max_deviation_band} Hz",
         f"<= {TIMBRE_MAX_DB:g} dB per band", _verdict(t.passed)),
        ("low end", f"{le.difference_db:+.2f} dB below {LOW_END_HZ:g} Hz, L/R corr "
         f"{le.rendered_correlation:.3f} (original {le.original_correlation:.3f})",
         "not gated", _verdict(le.passed)),
    ]
    head = ("check", "measured", "threshold", "result")
    widths = [max(len(r[i]) for r in (head, *rows)) for i in range(4)]
    line = "  ".join("{:<%d}" % w for w in widths)
    out = [line.format(*head), line.format(*("-" * w for w in widths))]
    out += [line.format(*r) for r in rows]
    if t.failing_bands:
        out.append("timbre failing bands (Hz): " + ", ".join(
            f"{lab} ({d:+.2f})" for lab, d in zip(t.band_labels, t.band_difference_db, strict=True)
            if lab in t.failing_bands))
    out.append(f"overall: {'pass' if report.passed else 'FAIL'}")
    return "\n".join(out)
