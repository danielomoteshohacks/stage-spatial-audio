"""Deterministic generated multitrack songs for tests and the spatial benchmark. No recordings.

Each song has a tempo, a bar structure of intro, verse, chorus, verse, chorus, outro, and four
stems that sum exactly to the mix:

* drums: a kick (pitch-swept sine), a snare (noise plus a tone), hi-hats (high-passed noise) and
  shakers, panned across the kit, with the choruses denser;
* bass: a sine-and-octave line on the root of each bar, centred;
* other: a three-voice chord pad (detuned saws, low-passed), spread wide, plus a room-like
  ambience made of decorrelated noise-excited resonances;
* vocals: a formant-synthesised voice (a glottal pulse train through three formant resonators,
  Klatt 1980 style) singing a melody, centred, with vibrato.

Everything is seeded, so a song is the same on every machine.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.signal import butter, lfilter, sosfilt

STRUCTURE = (("intro", 4, 0.35), ("verse", 8, 0.55), ("chorus", 8, 1.0), ("verse", 8, 0.55),
             ("chorus", 8, 1.0), ("outro", 4, 0.3))
#: Formants (Hz) of the vowels the voice sings: a, e, o (Peterson and Barney 1952 averages).
VOWELS = ((730, 1090, 2440), (530, 1840, 2480), (570, 840, 2410))


@dataclass
class Song:
    sample_rate: int
    tempo_bpm: float
    mix: NDArray[np.float64]
    stems: dict[str, NDArray[np.float64]]
    sections: list[tuple[str, float, float]]  # label, start s, end s


def _pan(x: NDArray, pos: float) -> NDArray:
    """Constant-power pan, pos -1 (left) to +1 (right)."""
    a = (pos + 1.0) * np.pi / 4.0
    return np.stack([np.cos(a) * x, np.sin(a) * x])


def _resonator(x: NDArray, f: float, bw: float, sr: int) -> NDArray:
    r = np.exp(-np.pi * bw / sr)
    a = [1.0, -2.0 * r * np.cos(2 * np.pi * f / sr), r * r]
    return lfilter([1.0 - r], a, x)


def make_song(seed: int = 0, tempo_bpm: float = 112.0, sample_rate: int = 44100,
              bars: tuple = STRUCTURE, key_hz: float = 110.0) -> Song:
    rng = np.random.default_rng(seed)
    sr = sample_rate
    beat = 60.0 / tempo_bpm
    total_bars = sum(b[1] for b in bars)
    n = int(round(total_bars * 4 * beat * sr)) + sr // 2
    t = np.arange(n) / sr
    drums = np.zeros((2, n))
    bass = np.zeros((2, n))
    other = np.zeros((2, n))
    vocals = np.zeros((2, n))
    sections = []
    roots = key_hz * 2 ** (np.array([0, 5, 7, 3]) / 12)  # i, iv, v, bIII
    hp = butter(4, 6000, "highpass", fs=sr, output="sos")
    bar_i = 0
    for label, n_bars, level in bars:
        start_s = bar_i * 4 * beat
        sections.append((label, start_s, start_s + n_bars * 4 * beat))
        for b in range(n_bars):
            bar0 = (bar_i + b) * 4 * beat
            root = roots[(bar_i + b) % 4]
            for k in range(4):  # beats
                t0 = int((bar0 + k * beat) * sr)
                m = min(int(0.35 * sr), n - t0)
                tt = np.arange(m) / sr
                if label != "intro" or k == 0:
                    kick = np.sin(2 * np.pi * (45 + 90 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 9)
                    drums[:, t0 : t0 + m] += _pan(0.9 * level * kick, 0.0)
                if k in (1, 3) and label != "intro":
                    sn = (rng.standard_normal(m) * 0.5 + np.sin(2 * np.pi * 190 * tt)) * np.exp(
                        -tt * 18)
                    drums[:, t0 : t0 + m] += _pan(0.45 * level * sn, -0.1)
                subdiv = 4 if level > 0.9 else 2
                for s in range(subdiv):
                    h0 = t0 + int(s * beat / subdiv * sr)
                    hm = min(int(0.06 * sr), n - h0)
                    if hm <= 0:
                        continue
                    hat = sosfilt(hp, rng.standard_normal(hm)) * np.exp(-np.arange(hm) / sr * 60)
                    drums[:, h0 : h0 + hm] += _pan(0.25 * level * hat, 0.45)
                    shaker = sosfilt(hp, rng.standard_normal(hm)) * np.exp(
                        -np.arange(hm) / sr * 25)
                    drums[:, h0 : h0 + hm] += _pan(0.12 * level * shaker, -0.6)
            b0, b1 = int(bar0 * sr), min(n, int((bar0 + 4 * beat) * sr))
            tb = t[b0:b1] - bar0
            env = np.minimum(1.0, tb * 40) * np.exp(-tb * 0.8)
            line = np.sin(2 * np.pi * root / 2 * tb) + 0.3 * np.sin(2 * np.pi * root * tb)
            bass[:, b0:b1] += _pan(0.45 * min(1.0, level + 0.2) * env * line, 0.0)
            chord = np.zeros(b1 - b0)
            for interval in (0, 4, 7):
                f = root * 2 ** (interval / 12) * 2
                for det in (-0.004, 0.004):
                    ph = 2 * np.pi * f * (1 + det) * tb
                    chord += 2.0 * ((ph / (2 * np.pi)) % 1.0) - 1.0
            chord = sosfilt(butter(2, 2500, fs=sr, output="sos"), chord) * 0.05 * level
            other[:, b0:b1] += np.stack([chord, 0.6 * chord])
            other[:, b0:b1] += np.stack([0.5 * chord[::-1] * 0, chord * 0.4])
            if label in ("verse", "chorus"):
                # The voice: two notes per bar on the melody, vowels cycling.
                for half in range(2):
                    v0 = b0 + int(half * 2 * beat * sr)
                    v1 = min(n, v0 + int(1.8 * beat * sr))
                    tv = np.arange(v1 - v0) / sr
                    f0 = root * 2 * 2 ** ((0, 3, 7, 5)[(bar_i + b + half) % 4] / 12)
                    f0t = f0 * (1 + 0.012 * np.sin(2 * np.pi * 5.5 * tv))
                    phase = np.cumsum(f0t) / sr
                    pulses = np.diff(np.floor(phase), prepend=0.0)
                    src = lfilter([1.0], [1.0, -0.97], pulses)
                    vow = VOWELS[(bar_i + b + half) % 3]
                    voice = sum(_resonator(src, f, bw, sr) * g for f, bw, g in
                                zip(vow, (80, 90, 120), (1.0, 0.6, 0.3), strict=True))
                    voice *= np.minimum(1.0, tv * 30) * np.minimum(1.0, (tv[-1] - tv) * 30)
                    vocals[:, v0:v1] += _pan(0.3 * min(1.0, level + 0.3) * voice, 0.0)
        bar_i += n_bars
    # Ambience: decorrelated noise through slow resonances, quiet, in "other".
    amb = np.stack([sosfilt(butter(2, [300, 3000], "bandpass", fs=sr, output="sos"),
                            rng.standard_normal(n)) for _ in range(2)]) * 0.01
    other += amb
    stems = {"vocals": vocals, "drums": drums, "bass": bass, "other": other}
    peak = max(float(np.max(np.abs(sum(stems.values())))), 1e-9)
    stems = {k: v * (0.7 / peak) for k, v in stems.items()}
    return Song(sample_rate=sr, tempo_bpm=tempo_bpm, mix=sum(stems.values()), stems=stems,
                sections=sections)
