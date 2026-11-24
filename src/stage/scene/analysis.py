"""Song analysis for the mix plan: tempo, beat grid, downbeats, sections, energy, stem activity.

Decision 0016. Everything is deterministic numpy and scipy, so the same track always gives the
same plan.

* **Onset strength**: half-wave rectified spectral flux of a log-compressed mel-like spectrum
  (Bock and Widmer 2013 use the same "SuperFlux" family of detection functions).
* **Tempo**: the autocorrelation of the onset strength weighted by a log-normal prior centred
  at 120 BPM (Ellis 2007, "Beat tracking by dynamic programming", J. New Music Res. 36(1)).
* **Beats**: Ellis' dynamic programme, which trades onset strength against deviation from the
  tempo period.
* **Downbeats**: the beat phase (of four) whose beats carry the most low-frequency onset
  strength, which is where the kick and bass usually land in the styles SoundStage targets.
* **Sections**: Foote's novelty (2000, "Automatic audio segmentation using a measure of audio
  novelty", ICME): a checkerboard kernel slid along the diagonal of a beat-synchronous
  self-similarity matrix of timbre and energy features; peaks are boundaries, snapped to
  downbeats. Labels (intro, verse, chorus, drop, bridge, outro) come from each section's energy
  rank and position: a heuristic, recorded as such in the plan.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import maximum_filter1d, uniform_filter1d
from scipy.signal import find_peaks

from stage.analysis.stft import stft

HOP_S = 0.01  # 100 frames per second for the detection functions


@dataclass
class Section:
    start_s: float
    end_s: float
    label: str
    energy: float  # mean loudness relative to the track's loudest section, 0 to 1


@dataclass
class SongAnalysis:
    duration_s: float
    tempo_bpm: float
    beats_s: list[float]
    downbeats_s: list[float]
    sections: list[Section]
    energy_curve: list[float]  # per second, 0 to 1
    stem_activity: dict[str, list[float]] = field(default_factory=dict)  # per second, 0 to 1
    method: str = ("onset flux; autocorrelation tempo with a 120 BPM prior; Ellis DP beats; "
                   "low-band downbeats; Foote novelty sections; energy-rank labels")

    def as_dict(self) -> dict:
        d = asdict(self)
        d["tempo_bpm"] = round(self.tempo_bpm, 2)
        d["beats_s"] = [round(b, 3) for b in self.beats_s]
        d["downbeats_s"] = [round(b, 3) for b in self.downbeats_s]
        for s in d["sections"]:
            s["start_s"], s["end_s"] = round(s["start_s"], 3), round(s["end_s"], 3)
            s["energy"] = round(s["energy"], 3)
        d["energy_curve"] = [round(v, 3) for v in self.energy_curve]
        d["stem_activity"] = {k: [round(v, 3) for v in a] for k, a in self.stem_activity.items()}
        return d


def _bands(n_fft: int, sample_rate: int, n_bands: int = 40) -> NDArray[np.float64]:
    """Triangular log-spaced filterbank (n_bands, bins) from 40 Hz to 16 kHz."""
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    edges = np.geomspace(40.0, min(16000.0, sample_rate / 2.2), n_bands + 2)
    fb = np.zeros((n_bands, freqs.size))
    for i in range(n_bands):
        lo, c, hi = edges[i], edges[i + 1], edges[i + 2]
        fb[i] = np.clip(np.minimum((freqs - lo) / (c - lo), (hi - freqs) / (hi - c)), 0, None)
    return fb


def detection(mono: NDArray, sample_rate: int) -> tuple[NDArray, NDArray, NDArray]:
    """(onset strength, low-band onset strength, band log-energies (frames, bands)), 100 fps."""
    hop = int(round(HOP_S * sample_rate))
    n_fft = 2048
    spec = np.abs(stft(mono[np.newaxis], n_fft=n_fft, hop=hop)[0])  # (frames, bins)
    fb = _bands(n_fft, sample_rate)
    bands = np.log1p(100.0 * (spec**2) @ fb.T)
    # SuperFlux-style: compare with a frequency-maximum-filtered earlier frame, so vibrato does
    # not count as onsets.
    ref = maximum_filter1d(bands, size=3, axis=1)
    flux = np.maximum(bands[2:] - ref[:-2], 0.0)
    flux = np.concatenate([np.zeros((2, flux.shape[1])), flux])
    onset = flux.sum(axis=1)
    low = flux[:, :8].sum(axis=1)
    return onset, low, bands


def estimate_tempo(onset: NDArray, lo_bpm: float = 70.0, hi_bpm: float = 180.0) -> float:
    o = onset - onset.mean()
    ac = np.correlate(o, o, mode="full")[o.size - 1 :]
    lags = np.arange(ac.size)
    fps = 1.0 / HOP_S
    bpm = np.where(lags > 0, 60.0 * fps / np.maximum(lags, 1), 0.0)
    prior = np.exp(-0.5 * (np.log2(np.maximum(bpm, 1e-9) / 120.0) / 0.9) ** 2)
    valid = (bpm >= lo_bpm) & (bpm <= hi_bpm)
    score = np.where(valid, ac * prior, -np.inf)
    lag = int(np.argmax(score))
    # Parabolic refinement of the peak lag.
    if 1 <= lag < ac.size - 1:
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        den = a - 2 * b + c
        lag_f = lag + (0.5 * (a - c) / den if den != 0 else 0.0)
    else:
        lag_f = float(lag)
    return 60.0 * fps / lag_f if lag_f > 0 else 120.0


def track_beats(onset: NDArray, tempo_bpm: float, tightness: float = 100.0) -> NDArray:
    """Ellis' dynamic-programming beat tracker; returns beat frame indices."""
    period = 60.0 / tempo_bpm / HOP_S
    o = onset / (onset.std() + 1e-9)
    n = o.size
    score = o.copy()
    back = -np.ones(n, dtype=np.int64)
    lo, hi = int(round(period / 2)), int(round(2 * period))
    for t in range(hi, n):
        prev = np.arange(t - hi, t - lo + 1)
        cost = -tightness * np.log((t - prev) / period) ** 2
        cand = score[prev] + cost
        k = int(np.argmax(cand))
        score[t] = o[t] + cand[k]
        back[t] = prev[k]
    # Start from the best score in the last period and follow the back-pointers.
    t = int(np.argmax(score[max(0, n - int(period)) :]) + max(0, n - int(period)))
    beats = [t]
    while back[t] >= 0:
        t = int(back[t])
        beats.append(t)
    return np.array(beats[::-1], dtype=np.int64)


def novelty(features: NDArray, kernel: int) -> NDArray:
    """Foote novelty of beat-synchronous features (beats, dims) with a checkerboard kernel."""
    f = features - features.mean(axis=0)
    f = f / (np.linalg.norm(f, axis=1, keepdims=True) + 1e-9)
    ssm = f @ f.T
    k = kernel
    sign = np.ones((2 * k, 2 * k))
    sign[:k, k:] = -1
    sign[k:, :k] = -1
    g = np.outer(np.hanning(2 * k), np.hanning(2 * k))
    ker = sign * g
    n = ssm.shape[0]
    pad = np.pad(ssm, k, mode="edge")
    return np.array([np.sum(ker * pad[i : i + 2 * k, i : i + 2 * k]) for i in range(n)])


def _label(sections: list[Section]) -> None:
    """Energy labels, a heuristic: sections at 70 percent or more of the loudest section's energy
    are choruses (a single, much louder one with nothing near it is a drop), a quiet first
    section is the intro and a quiet last one the outro, a verse straight before a chorus is a
    pre-chorus when it is shorter than the verse before it, and a quiet section between two
    choruses after the first is a bridge. The rest are verses."""
    if not sections:
        return
    for s in sections:
        s.label = "chorus" if s.energy >= 0.7 else "verse"
    loud = [s for s in sections if s.label == "chorus"]
    if len(loud) == 1 and len(sections) > 2 and sorted(x.energy for x in sections)[-2] < 0.5:
        loud[0].label = "drop"
    if len(sections) > 2 and sections[0].label == "verse" and sections[0].energy < 0.4:
        sections[0].label = "intro"
    if len(sections) > 3 and sections[-1].label == "verse" and sections[-1].energy < 0.4:
        sections[-1].label = "outro"
    for i in range(1, len(sections) - 1):
        prev, cur, nxt = sections[i - 1], sections[i], sections[i + 1]
        if (cur.label == "verse" and nxt.label in ("chorus", "drop") and prev.label == "verse"
                and (cur.end_s - cur.start_s) < (prev.end_s - prev.start_s)):
            cur.label = "pre-chorus"
    first = next((i for i, s in enumerate(sections) if s.label == "chorus"), None)
    if first is not None:
        for i in range(first + 1, len(sections) - 1):
            s = sections[i]
            later = any(x.label == "chorus" for x in sections[i + 1 :])
            if s.label == "verse" and s.energy < 0.3 and later:
                s.label = "bridge"


def analyse_song(audio: NDArray, sample_rate: int,
                 stems: dict[str, NDArray] | None = None) -> SongAnalysis:
    """Analyse a stereo excerpt (2, n) and, if given, the activity of each stem."""
    audio = np.asarray(audio, dtype=np.float64)
    mono = audio.mean(axis=0)
    duration = mono.size / sample_rate
    onset, low, bands = detection(mono, sample_rate)
    onset = uniform_filter1d(onset, 3)
    tempo = estimate_tempo(onset)
    beat_frames = track_beats(onset, tempo)
    beats = beat_frames * HOP_S
    # Downbeats: the phase of four with the most low-band onset strength.
    low_s = uniform_filter1d(low, 5)
    phase_scores = [low_s[beat_frames[p::4]].sum() for p in range(min(4, beat_frames.size))]
    phase = int(np.argmax(phase_scores)) if phase_scores else 0
    downbeats = beats[phase::4]
    # Energy per second (mean band log energy), normalised.
    per_s = int(round(1.0 / HOP_S))
    frame_energy = bands.mean(axis=1)
    secs = [float(frame_energy[i : i + per_s].mean()) for i in range(0, frame_energy.size, per_s)]
    e = np.asarray(secs)
    curve = ((e - e.min()) / (e.max() - e.min() + 1e-9)).tolist() if e.size else []
    # Sections from beat-synchronous timbre and energy features.
    sections: list[Section] = []
    if beat_frames.size >= 16:
        feats = np.stack([bands[a:b].mean(axis=0) for a, b in
                          zip(beat_frames[:-1], beat_frames[1:], strict=True)])
        feats = np.concatenate([feats, frame_energy[beat_frames[:-1], None] * 2.0], axis=1)
        nov = novelty(feats, kernel=16)
        peaks, _ = find_peaks(nov, distance=16, prominence=np.std(nov) * 0.5 if nov.size else 0)
        bounds_s = sorted({0.0, duration, *[float(beats[p]) for p in peaks]})
        # Snap to the nearest downbeat, drop sections shorter than four beats.
        snapped = [0.0]
        for b in bounds_s[1:-1]:
            if downbeats.size:
                b = float(downbeats[np.argmin(np.abs(downbeats - b))])
            if b - snapped[-1] >= 4 * 60.0 / tempo:
                snapped.append(b)
        snapped.append(duration)
        loud = []
        for a, b in zip(snapped[:-1], snapped[1:], strict=True):
            fa, fb = int(a / HOP_S), max(int(a / HOP_S) + 1, int(b / HOP_S))
            loud.append(float(frame_energy[fa:fb].mean()))
        lo, hi = min(loud), max(loud)
        for (a, b), lv in zip(zip(snapped[:-1], snapped[1:], strict=True), loud, strict=True):
            rel = (lv - lo) / (hi - lo + 1e-9) if hi > lo else 1.0
            sections.append(Section(a, b, "verse", rel))
        _label(sections)
    else:
        sections.append(Section(0.0, duration, "verse", 1.0))
    activity: dict[str, list[float]] = {}
    for name, stem in (stems or {}).items():
        m = np.asarray(stem).mean(axis=0)
        n = int(sample_rate)
        rms = np.array([np.sqrt(np.mean(m[i : i + n] ** 2)) for i in range(0, m.size, n)])
        activity[name] = (rms / (rms.max() + 1e-12)).tolist() if rms.size else []
    return SongAnalysis(duration_s=duration, tempo_bpm=float(tempo), beats_s=beats.tolist(),
                        downbeats_s=downbeats.tolist(), sections=sections, energy_curve=curve,
                        stem_activity=activity)
