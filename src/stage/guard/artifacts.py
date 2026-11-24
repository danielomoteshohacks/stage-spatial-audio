"""Artifact detectors with timestamps: clipping runs, band dropouts, pre-echo and musical noise.

Each detector compares the render with the original wherever the defect could already be in the
record, so a clipped master or a gated synth is not blamed on the renderer. They are detectors,
not perceptual models: each flag is a place to listen, and each threshold is documented in
configs/thresholds/guard.json.

All take (2, samples) float arrays of equal length at one sample rate and return a list of
`Flag`, merged so one long event is one flag.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import maximum_filter
from scipy.signal import butter, sosfiltfilt

from stage.analysis.stft import stft


@dataclass(frozen=True)
class Flag:
    kind: str  # clipping, dropout, pre_echo, musical_noise
    start_s: float
    end_s: float
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "start_s": round(self.start_s, 3),
                "end_s": round(self.end_s, 3), "detail": self.detail}


def _runs(mask: NDArray[np.bool_]) -> list[tuple[int, int]]:
    """(start, stop) index pairs of the True runs of a 1-D mask."""
    if not mask.any():
        return []
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist(), strict=True))


def _merge(flags: list[Flag], gap_s: float = 0.25) -> list[Flag]:
    """Join flags of one kind closer than `gap_s`, so a dense event is reported once."""
    out: list[Flag] = []
    for f in sorted(flags, key=lambda f: (f.kind, f.start_s)):
        if out and out[-1].kind == f.kind and f.start_s - out[-1].end_s <= gap_s:
            last = out[-1]
            out[-1] = Flag(f.kind, last.start_s, max(last.end_s, f.end_s), last.detail)
        else:
            out.append(f)
    return sorted(out, key=lambda f: f.start_s)


def detect_clipping(render: NDArray, sample_rate: int, *, level: float, min_run: int,
                    original: NDArray | None = None) -> list[Flag]:
    """Runs of at least `min_run` consecutive samples at or above `level` in either channel."""
    flags = []
    for ch in range(render.shape[0]):
        for a, b in _runs(np.abs(render[ch]) >= level):
            if b - a < min_run:
                continue
            in_orig = original is not None and bool(
                np.any(np.abs(original[:, a:b]) >= level))
            flags.append(Flag("clipping", a / sample_rate, b / sample_rate,
                              f"{b - a} samples at full scale in channel {ch}"
                              + (" (also clipped in the original)" if in_orig else "")))
    return _merge(flags, gap_s=0.05)


#: Octave bands for the dropout detector, 63 Hz to 16 kHz.
DROPOUT_BANDS_HZ = (63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)


def _band_levels(x: NDArray, sample_rate: int, n_fft: int, hop: int) -> tuple[NDArray, NDArray]:
    """Per-frame octave-band power (dB) with both channels summed: (frames, bands), band list."""
    spec = stft(x, n_fft=n_fft, hop=hop)
    power = np.sum(np.abs(spec) ** 2, axis=0)  # (frames, bins)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    bands = [fc for fc in DROPOUT_BANDS_HZ if fc * np.sqrt(2) <= sample_rate / 2]
    levels = np.empty((power.shape[0], len(bands)))
    for i, fc in enumerate(bands):
        sel = (freqs >= fc / np.sqrt(2)) & (freqs < fc * np.sqrt(2))
        levels[:, i] = 10.0 * np.log10(power[:, sel].sum(axis=1) + 1e-20)
    return levels, np.asarray(bands)


def detect_dropouts(original: NDArray, render: NDArray, sample_rate: int, *, drop_db: float,
                    min_ms: float, floor_db: float) -> list[Flag]:
    """Octave bands that fall `drop_db` below the original for at least `min_ms`.

    The overall level offset is removed first (a quieter render is the loudness check's job),
    and only bands within `floor_db` of the loudest band of that frame in the original count.
    """
    n_fft, hop = 2048, 512
    lo, bands = _band_levels(original, sample_rate, n_fft, hop)
    lr, _ = _band_levels(render, sample_rate, n_fft, hop)
    offset = 10.0 * np.log10((np.mean(render**2) + 1e-20) / (np.mean(original**2) + 1e-20))
    diff = lr - offset - lo
    audible = lo >= (lo.max(axis=1, keepdims=True) + floor_db)
    frame_s = hop / sample_rate
    min_frames = max(1, int(np.ceil(min_ms * 1e-3 / frame_s)))
    flags = []
    for j, fc in enumerate(bands):
        for a, b in _runs((diff[:, j] < -drop_db) & audible[:, j]):
            if b - a >= min_frames:
                worst = float(diff[a:b, j].min())
                # Frame t covers samples from (t * hop - (n_fft - hop)); report its centre.
                t0 = max(0.0, (a * hop - (n_fft - hop) + n_fft / 2) / sample_rate)
                flags.append(Flag("dropout", t0, t0 + (b - a) * frame_s,
                                  f"{fc} Hz octave {worst:.0f} dB below the original"))
    return _merge(flags)


def _hf_envelope(x: NDArray, sample_rate: int, frame: int) -> NDArray[np.float64]:
    """Energy per `frame` samples of the signal above 2 kHz, both channels summed."""
    sos = butter(4, 2000.0, btype="highpass", fs=sample_rate, output="sos")
    y = sosfiltfilt(sos, x, axis=-1)
    n = y.shape[-1] // frame
    return np.square(y[:, : n * frame]).reshape(y.shape[0], n, frame).mean(axis=-1).sum(axis=0)


def detect_pre_echo(original: NDArray, render: NDArray, sample_rate: int, *, excess_db: float,
                    audible_db: float) -> list[Flag]:
    """Energy smeared ahead of the original's transients.

    Onsets are found in the original's high band (where transients carry their energy): a rise of
    at least 15 dB over the previous 20 ms. For each, the ratio of the 20 ms before to the peak
    after is measured in both signals. A frequency-domain renderer with long frames spreads a
    transient over the whole frame, which raises that ratio; zero-phase filters do the same.
    The window matches backward masking, which hides weaker energy up to about 20 ms ahead.
    Energy that is already there 20 to 40 ms before the onset (a reverb tail, a sustained note)
    is not counted: a pre-echo rises toward the transient it belongs to.
    """
    frame = max(1, int(round(0.0025 * sample_rate)))
    eo = _hf_envelope(original, sample_rate, frame) + 1e-20
    er = _hf_envelope(render, sample_rate, frame) + 1e-20
    pre_n = 8  # 20 ms
    lo_db = 10.0 * np.log10(eo)
    flags = []
    t = pre_n
    while t < eo.size - 4:
        before = lo_db[t - pre_n : t].mean()
        if lo_db[t] - before >= 15.0 and lo_db[t] >= lo_db.max() - 40.0:
            post_o, post_r = eo[t : t + 4].max(), er[t : t + 4].max()
            pre_o, pre_r = eo[t - pre_n : t - 1].mean(), er[t - pre_n : t - 1].mean()
            ratio_o = 10.0 * np.log10(pre_o / post_o)
            ratio_r = 10.0 * np.log10(pre_r / post_r)
            # A pre-echo grows toward the transient; the decaying tail of an earlier note or of
            # reverberation does not. The render's pre-window must exceed the 20 ms before it.
            earlier = er[max(0, t - 2 * pre_n) : t - pre_n].mean() if t >= 2 * pre_n else 0.0
            rising = pre_r > 2.0 * earlier  # 3 dB
            if ratio_r - ratio_o > excess_db and ratio_r > audible_db and rising:
                start = (t - pre_n) * frame / sample_rate
                flags.append(Flag("pre_echo", start, t * frame / sample_rate,
                                  f"{ratio_r - ratio_o:.0f} dB more energy before the transient"))
            t += pre_n  # one onset per 20 ms
        else:
            t += 1
    return _merge(flags, gap_s=0.1)


def _isolated_peaks(x: NDArray, sample_rate: int, n_fft: int, hop: int) -> NDArray[np.float64]:
    """Isolated spectral peaks above 1 kHz per frame: musical-noise "birdies".

    A bin counts when it is the maximum of its 5 x 5 time-frequency neighbourhood and stands
    at least 12 dB above that neighbourhood's median. Real tonal partials last longer than five
    frames and fail the isolation test against their own neighbours in time, so this picks the
    short-lived specks a mask or a Wiener gain leaves behind.
    """
    spec = stft(x, n_fft=n_fft, hop=hop)
    mag_db = 10.0 * np.log10(np.sum(np.abs(spec) ** 2, axis=0) + 1e-20)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    mag_db = mag_db[:, freqs >= 1000.0]
    local_max = maximum_filter(mag_db, size=(5, 5), mode="nearest") == mag_db
    # The median of a 5 x 5 patch, computed with a sorted stack: faster than a generic filter.
    pad = np.pad(mag_db, 2, mode="edge")
    patches = np.stack([pad[i : i + mag_db.shape[0], j : j + mag_db.shape[1]]
                        for i in range(5) for j in range(5)])
    median = np.median(patches, axis=0)
    # Only peaks within 60 dB of the frame's loudest bin can be heard over the rest of it.
    loud = mag_db >= mag_db.max(axis=1, keepdims=True) - 60.0
    # Peaks that last: a partial is still at least half as strong two frames on either side.
    lasting = np.zeros_like(local_max)
    lasting[2:-2] = (mag_db[:-4] > mag_db[2:-2] - 6.0) | (mag_db[4:] > mag_db[2:-2] - 6.0)
    isolated = local_max & loud & ~lasting & (mag_db - median >= 12.0)
    return isolated.sum(axis=1).astype(np.float64)


def detect_musical_noise(original: NDArray, render: NDArray, sample_rate: int, *, ratio: float,
                         min_per_s: float) -> list[Flag]:
    """One-second windows where the render has far more isolated peaks than the original."""
    n_fft, hop = 1024, 256
    po = _isolated_peaks(original, sample_rate, n_fft, hop)
    pr = _isolated_peaks(render, sample_rate, n_fft, hop)
    per_window = max(1, int(round(sample_rate / hop)))
    flags = []
    for w0 in range(0, pr.size, per_window):
        dur = min(per_window, pr.size - w0) * hop / sample_rate
        if dur < 0.5:
            break
        r_rate = pr[w0 : w0 + per_window].sum() / dur
        o_rate = po[w0 : w0 + per_window].sum() / dur
        if r_rate >= min_per_s and r_rate > ratio * max(o_rate, 1.0):
            t0 = max(0.0, (w0 * hop - (n_fft - hop)) / sample_rate)
            flags.append(Flag("musical_noise", t0, t0 + dur,
                              f"{r_rate:.0f} isolated peaks per second against {o_rate:.0f}"))
    return _merge(flags, gap_s=0.01)


def detect_all(original: NDArray, render: NDArray, sample_rate: int,
               t: dict[str, float]) -> list[Flag]:
    """Every detector with the thresholds in `t` (see configs/thresholds/guard.json)."""
    flags = detect_clipping(render, sample_rate, level=t["clip_level"],
                            min_run=int(t["clip_run_samples"]), original=original)
    flags += detect_dropouts(original, render, sample_rate, drop_db=t["dropout_drop_db"],
                             min_ms=t["dropout_min_ms"], floor_db=t["dropout_floor_db"])
    flags += detect_pre_echo(original, render, sample_rate, excess_db=t["pre_echo_excess_db"],
                             audible_db=t["pre_echo_audible_db"])
    flags += detect_musical_noise(original, render, sample_rate,
                                  ratio=t["musical_noise_ratio"],
                                  min_per_s=t["musical_noise_min_per_s"])
    return sorted(flags, key=lambda f: f.start_s)
