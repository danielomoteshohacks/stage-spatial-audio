"""The fidelity report written as report.json next to every render (schemas/report.schema.json).

It compares what the listener hears (the leveled render) with the original excerpt and gives a
verdict with plain-language reasons. "pass" means every measure is inside its review threshold,
"review" means at least one should be listened to, and "fail" means the render must not be
presented as faithful to the record. Thresholds and their reasoning are in
configs/thresholds/guard.json.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from numpy.typing import NDArray

from stage.config import threshold_values
from stage.guard.artifacts import Flag, detect_all
from stage.guard.checks import _lowpass_fft, check_alignment, check_timbre
from stage.guard.loudness import integrated_loudness, true_peak_dbtp

#: Broad bands of the downmix check (Hz): bass, the voice and instrument body, and the air.
DOWNMIX_BANDS = {"low": (20.0, 250.0), "mid": (250.0, 4000.0), "high": (4000.0, 16000.0)}
LOW_END_HZ = 120.0


def _db_ratio(num: float, den: float) -> float:
    if num <= 0.0 and den <= 0.0:
        return 0.0
    if den <= 0.0 or num <= 0.0:
        return -120.0 if num <= 0.0 else 120.0
    return 10.0 * math.log10(num / den)


def _band_power(x: NDArray, sample_rate: int, lo: float, hi: float) -> float:
    spec = np.fft.rfft(x, axis=-1)
    freqs = np.fft.rfftfreq(x.shape[-1], d=1.0 / sample_rate)
    sel = (freqs >= lo) & (freqs < min(hi, sample_rate / 2))
    return float(np.sum(np.abs(spec[..., sel]) ** 2))


def downmix_difference(original: NDArray, render: NDArray, sample_rate: int) -> dict[str, float]:
    """Mid (L + R) band level of the render minus the original's, after the overall offset.

    The mid is what a mono phone speaker, a Bluetooth speaker in mono, or a club sum plays. A
    binaural render moves energy between the ears on purpose, but its sum should keep the
    record's balance between bass, body and air.
    """
    mo, mr = original.sum(axis=0), render.sum(axis=0)
    offset = _db_ratio(float(np.sum(mr**2)), float(np.sum(mo**2)))
    return {name: round(_db_ratio(_band_power(mr, sample_rate, lo, hi),
                                  _band_power(mo, sample_rate, lo, hi)) - offset, 3)
            for name, (lo, hi) in DOWNMIX_BANDS.items()}


def mono_gain_db(x: NDArray) -> float:
    """Power of the mono fold (L + R) / 2 relative to the mean channel power, in dB.

    0 dB for identical channels, -3 dB for uncorrelated ones, minus infinity for anti-phase.
    """
    mono = float(np.mean(((x[0] + x[1]) / 2.0) ** 2))
    chans = float(np.mean(x**2))
    return max(-120.0, _db_ratio(mono, chans))


def low_end(original: NDArray, render: NDArray, sample_rate: int, lag: int) -> dict[str, float]:
    """Identity of the bass: correlation of the two low ends (mono, < 120 Hz) near zero lag.

    Also the level change there and the render's L/R correlation, which should stay near the
    original's: a decorrelated bass smears the kick and loses power in a mono fold.
    """
    lo_o = _lowpass_fft(original, sample_rate, LOW_END_HZ)
    lo_r = _lowpass_fft(render, sample_rate, LOW_END_HZ)
    mo, mr = lo_o.sum(axis=0), lo_r.sum(axis=0)
    # The best correlation within the measured lag (or 1 ms, whichever is larger) either way:
    # a renderer may delay its upper band slightly while passing the bass straight through, and
    # the bass's identity must not be judged at the upper band's lag.
    reach = max(abs(lag), int(round(0.001 * sample_rate)))
    den = math.sqrt(float(np.sum(mo**2)) * float(np.sum(mr**2)))
    if den > 0:
        nfft = 1 << int(np.ceil(np.log2(2 * mo.size)))
        xc = np.fft.irfft(np.fft.rfft(mr, nfft) * np.conj(np.fft.rfft(mo, nfft)), nfft)
        lags = np.arange(-reach, reach + 1)
        corr = float(np.max(xc[lags % nfft]) / den)
    else:
        corr = 1.0

    def lr(x: NDArray) -> float:
        d = math.sqrt(float(np.sum(x[0] ** 2)) * float(np.sum(x[1] ** 2)))
        return float(np.sum(x[0] * x[1]) / d) if d > 0 else 1.0

    return {
        "identity_corr": round(max(-1.0, min(1.0, corr)), 4),
        "level_db": round(_db_ratio(float(np.mean(lo_r**2)), float(np.mean(lo_o**2))), 3),
        "render_lr_corr": round(lr(lo_r), 4),
        "original_lr_corr": round(lr(lo_o), 4),
    }


def _finite(x: float, floor: float = -120.0) -> float:
    return round(x if math.isfinite(x) else floor, 3)


def build_report(original: NDArray, render: NDArray, sample_rate: int,
                 versions: dict[str, str], thresholds: dict[str, float] | None = None
                 ) -> dict[str, Any]:
    """Measure, flag and judge one render. Both are (2, n) at `sample_rate`."""
    t = thresholds or threshold_values()
    original = np.asarray(original, dtype=np.float64)
    render = np.asarray(render, dtype=np.float64)
    if original.shape != render.shape or original.ndim != 2 or original.shape[0] != 2:
        raise ValueError(f"need two (2, n) arrays of one shape, got {original.shape} and "
                         f"{render.shape}")
    align = check_alignment(original, render, sample_rate)
    timbre = check_timbre(original, render, sample_rate)
    lufs_o = integrated_loudness(original, sample_rate)
    lufs_r = integrated_loudness(render, sample_rate)
    tp = true_peak_dbtp(render, sample_rate)
    mono = mono_gain_db(render) - mono_gain_db(original)
    downmix = downmix_difference(original, render, sample_rate)
    bass = low_end(original, render, sample_rate, align.lag_samples)
    flags: list[Flag] = detect_all(original, render, sample_rate, t)

    fails: list[str] = []
    reviews: list[str] = []
    if abs(align.lag_ms) > t["alignment_fail_ms"]:
        fails.append(f"The render is {align.lag_ms:+.1f} ms out of time with the original.")
    elif abs(align.lag_ms) > t["alignment_review_ms"]:
        reviews.append(f"The render is {align.lag_ms:+.2f} ms out of time with the original.")
    if math.isfinite(lufs_o) and math.isfinite(lufs_r):
        d = lufs_r - lufs_o
        if abs(d) > t["loudness_fail_lu"]:
            fails.append(f"Loudness differs by {d:+.1f} LU, so an A/B would not be fair.")
        elif abs(d) > t["loudness_review_lu"]:
            reviews.append(f"Loudness differs by {d:+.1f} LU.")
    if tp > t["true_peak_fail_dbtp"]:
        fails.append(f"The true peak is {tp:+.1f} dBTP, which can clip after conversion.")
    if timbre.max_deviation_db > t["timbre_fail_db"]:
        fails.append(f"The tone changes by {timbre.max_deviation_db:.1f} dB around "
                     f"{timbre.max_deviation_band} Hz.")
    elif timbre.max_deviation_db > t["timbre_review_db"]:
        reviews.append(f"The tone changes by {timbre.max_deviation_db:.1f} dB around "
                       f"{timbre.max_deviation_band} Hz.")
    worst_band = max(downmix, key=lambda k: abs(downmix[k]))
    if abs(downmix[worst_band]) > t["downmix_review_db"]:
        reviews.append(f"In mono the {worst_band} band is {downmix[worst_band]:+.1f} dB off the "
                       "original.")
    if mono < t["mono_cancel_review_db"]:
        reviews.append(f"The mono fold loses {-mono:.1f} dB more than the original's.")
    if bass["identity_corr"] < t["low_end_corr_fail"]:
        fails.append(f"The bass is not the record's bass (correlation {bass['identity_corr']:.2f}"
                     " below 120 Hz).")
    elif bass["identity_corr"] < t["low_end_corr_review"]:
        reviews.append(f"The bass differs a little from the record's (correlation "
                       f"{bass['identity_corr']:.2f} below 120 Hz).")
    if abs(bass["level_db"]) > t["low_end_level_review_db"]:
        reviews.append(f"The bass level changes by {bass['level_db']:+.1f} dB.")
    kinds = sorted({f.kind for f in flags})
    words = {"clipping": "clipped samples", "dropout": "band dropouts", "pre_echo": "pre-echo",
             "musical_noise": "musical noise"}
    for kind in kinds:
        n = sum(f.kind == kind for f in flags)
        first = next(f for f in flags if f.kind == kind)
        msg = f"{n} {words[kind]} flag{'s' if n > 1 else ''}, first at {first.start_s:.1f} s."
        (fails if kind == "clipping" else reviews).append(msg)

    verdict = "fail" if fails else ("review" if reviews else "pass")
    reasons = fails + reviews or ["Every measure is inside its threshold."]
    return {
        "alignment_ms": round(align.lag_ms, 4),
        "downmix_db": downmix,
        "low_end_corr": bass["identity_corr"],
        "low_end": bass,
        "loudness_lufs": {"original": _finite(lufs_o), "render": _finite(lufs_r)},
        "timbre_deviation_db": round(timbre.max_deviation_db, 3),
        "timbre_bands_db": {lab: round(d, 2) for lab, d in
                            zip(timbre.band_labels, timbre.band_difference_db, strict=True)},
        "true_peak_db": _finite(tp),
        "mono_cancel_db": round(mono, 3),
        "artifact_flags": [f.as_dict() for f in flags],
        "verdict": verdict,
        "reasons": reasons,
        "versions": dict(versions),
    }
