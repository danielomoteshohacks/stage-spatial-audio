"""Ground-truth object songs: a mix built from leaves with known 3D positions.

Decision 0022. The v2 benchmark songs have four stems, so they cannot say whether a renderer
puts a double-tracked guitar at the right side or a hi-hat overhead. These songs do. Each leaf is
a mono synthetic source with a position (azimuth, elevation, distance) taken from how a music
mixer would place it in an object mix (see the placement record, decision 0024):

* the *truth* is every leaf rendered dry through the measured HRTF at its position and summed:
  what a listener of the object mix hears;
* the *release* is the stereo fold of the same leaves, each constant-power panned by the sine of
  its azimuth (rear sources fold to the front; height is lost), the way an object mix is folded
  to a stereo master;
* every leaf also exists as its own (2, n) stereo stem of the release, the reference for
  separation scores.

SoundStage is then run on the release alone, and what it recovers (stems, directions) is scored
against the truth. Everything is seeded and synthetic: no recordings, no licences.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from scipy.signal import butter, lfilter, sosfilt

from stage.testsongs import STRUCTURE, VOWELS, _resonator


@dataclass(frozen=True)
class LeafSpec:
    name: str
    az: float  # degrees, positive to the left (SOFA)
    el: float
    dist: float
    parent: str  # the four-stem class a separator would put it in
    role: str  # placement role, matches configs/templates


LEAVES: tuple[LeafSpec, ...] = (
    LeafSpec("lead_vocal", 0.0, 8.0, 1.0, "vocals", "lead_vocal"),
    LeafSpec("backing_l", 70.0, 10.0, 1.8, "vocals", "backing_vocal"),
    LeafSpec("backing_r", -70.0, 10.0, 1.8, "vocals", "backing_vocal"),
    LeafSpec("kick", 0.0, 0.0, 1.4, "drums", "kick"),
    LeafSpec("snare", 0.0, 0.0, 1.5, "drums", "snare"),
    LeafSpec("hats", 25.0, 40.0, 2.0, "drums", "cymbals"),
    LeafSpec("tom_hi", 45.0, 5.0, 1.8, "drums", "toms"),
    LeafSpec("tom_lo", -45.0, 5.0, 1.8, "drums", "toms"),
    LeafSpec("bass", 0.0, 0.0, 1.2, "bass", "bass"),
    LeafSpec("guitar_l", 65.0, 0.0, 2.0, "other", "guitar"),
    LeafSpec("guitar_r", -65.0, 0.0, 2.0, "other", "guitar"),
    LeafSpec("keys", 35.0, 5.0, 1.9, "other", "keys"),
    LeafSpec("pad_l", 125.0, 25.0, 2.5, "other", "pad"),
    LeafSpec("pad_r", -125.0, 25.0, 2.5, "other", "pad"),
    LeafSpec("fx", 0.0, 65.0, 2.5, "other", "fx"),
)


@dataclass
class ObjectSong:
    sample_rate: int
    tempo_bpm: float
    sections: list[tuple[str, float, float]]
    specs: tuple[LeafSpec, ...]
    mono: dict[str, NDArray[np.float64]]
    stereo: dict[str, NDArray[np.float64]] = field(default_factory=dict)

    @property
    def mix(self) -> NDArray[np.float64]:
        return np.sum(list(self.stereo.values()), axis=0)

    def four_stems(self) -> dict[str, NDArray[np.float64]]:
        out = {k: np.zeros_like(self.mix) for k in ("vocals", "drums", "bass", "other")}
        for s in self.specs:
            out[s.parent] += self.stereo[s.name]
        return out

    def truth_binaural(self, hrtf=None) -> NDArray[np.float64]:
        """Every leaf dry through the measured HRTF at its true position, summed."""
        from scipy.signal import oaconvolve

        from stage.spatial.hrtf import BASE_DELAY, get_hrtf

        hs = hrtf or get_hrtf(self.sample_rate)
        n = next(iter(self.mono.values())).size
        out = np.zeros((2, n))
        for s in self.specs:
            h = hs.hrirs(s.az, s.el)[0]
            y = oaconvolve(self.mono[s.name][np.newaxis], h, axes=-1)
            out += y[:, BASE_DELAY : BASE_DELAY + n] / max(s.dist, 0.5) ** 0.5
        return out


def pan_gains(az: float) -> tuple[float, float]:
    """Constant-power stereo gains (left, right) for a source at SOFA azimuth `az`."""
    pos = float(np.clip(-np.sin(np.radians(az)), -1.0, 1.0))  # -1 left .. +1 right
    a = (pos + 1.0) * np.pi / 4.0
    return float(np.cos(a)), float(np.sin(a))


def _voice(f0: NDArray, vowels: NDArray, sr: int) -> NDArray:
    phase = np.cumsum(f0) / sr
    src = lfilter([1.0], [1.0, -0.97], np.diff(np.floor(phase), prepend=0.0))
    v = vowels[0]
    return sum(_resonator(src, f, bw, sr) * g for f, bw, g in
               zip(v, (80, 90, 120), (1.0, 0.6, 0.3), strict=True))


def _pluck(freq: float, n: int, sr: int, rng: np.random.Generator, decay: float = 0.996
           ) -> NDArray:
    """A Karplus-Strong string (Karplus and Strong 1983): noise through a lossy delay loop."""
    period = max(2, int(round(sr / freq)))
    a = np.zeros(period + 2)
    a[0] = 1.0
    a[period] = -0.5 * decay
    a[period + 1] = -0.5 * decay
    burst = np.zeros(n)
    burst[:period] = rng.uniform(-1, 1, period)
    return lfilter([1.0], a, burst)


def make_object_song(seed: int = 0, tempo_bpm: float = 112.0, sample_rate: int = 44100,
                     bars: tuple = STRUCTURE, key_hz: float = 110.0) -> ObjectSong:
    rng = np.random.default_rng(seed)
    sr = sample_rate
    beat = 60.0 / tempo_bpm
    n = int(round(sum(b[1] for b in bars) * 4 * beat * sr)) + sr // 2
    t = np.arange(n) / sr
    mono = {s.name: np.zeros(n) for s in LEAVES}
    roots = key_hz * 2 ** (np.array([0, 5, 7, 3]) / 12)
    hp = butter(4, 6000, "highpass", fs=sr, output="sos")
    sections: list[tuple[str, float, float]] = []
    bar_i = 0
    for si, (label, n_bars, level) in enumerate(bars):
        sections.append((label, bar_i * 4 * beat, (bar_i + n_bars) * 4 * beat))
        for b in range(n_bars):
            bar0 = (bar_i + b) * 4 * beat
            root = roots[(bar_i + b) % 4]
            b0, b1 = int(bar0 * sr), min(n, int((bar0 + 4 * beat) * sr))
            tb = t[b0:b1] - bar0
            last_bar = b == n_bars - 1
            for k in range(4):
                t0 = int((bar0 + k * beat) * sr)
                m = min(int(0.35 * sr), n - t0)
                tt = np.arange(m) / sr
                if label != "intro" or k == 0:
                    mono["kick"][t0 : t0 + m] += 0.9 * level * np.sin(
                        2 * np.pi * (45 + 90 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 9)
                if k in (1, 3) and label != "intro":
                    mono["snare"][t0 : t0 + m] += 0.45 * level * (
                        rng.standard_normal(m) * 0.5 + np.sin(2 * np.pi * 190 * tt)
                    ) * np.exp(-tt * 18)
                if last_bar and label != "outro" and k >= 2:
                    # A fill down the toms at the end of each section.
                    for j, name in enumerate(("tom_hi", "tom_lo")):
                        for q in range(2):
                            o = t0 + int((j + 2 * q) * beat / 4 * sr)
                            mm = min(int(0.25 * sr), n - o)
                            if mm <= 0:
                                continue
                            tm = np.arange(mm) / sr
                            f = (210 if name == "tom_hi" else 140)
                            body = np.sin(2 * np.pi * f * (1 + 0.3 * np.exp(-tm * 25)) * tm)
                            mono[name][o : o + mm] += 0.6 * body * np.exp(-tm * 14)
                if label != "intro":
                    subdiv = 4 if level > 0.9 else 2
                    for s in range(subdiv):
                        h0 = t0 + int(s * beat / subdiv * sr)
                        hm = min(int(0.06 * sr), n - h0)
                        if hm > 0:
                            hat = sosfilt(hp, rng.standard_normal(hm)) * np.exp(
                                -np.arange(hm) / sr * 60)
                            mono["hats"][h0 : h0 + hm] += 0.3 * level * hat
            line = np.sin(2 * np.pi * root / 2 * tb) + 0.3 * np.sin(2 * np.pi * root * tb)
            env = np.minimum(1.0, tb * 40) * np.exp(-tb * 0.8)
            mono["bass"][b0:b1] += 0.45 * min(1.0, level + 0.2) * env * line
            # Pads: detuned saws, a different detune per side so the two are not copies.
            for ch, dets in (("pad_l", (-0.006, 0.003)), ("pad_r", (-0.003, 0.006))):
                chord = np.zeros(b1 - b0)
                for interval in (0, 4, 7):
                    f = root * 2 ** (interval / 12) * 2
                    for det in dets:
                        chord += 2.0 * (((f * (1 + det) * tb)) % 1.0) - 1.0
                mono[ch][b0:b1] += sosfilt(butter(2, 2200, fs=sr, output="sos"),
                                           chord) * 0.05 * level
            if label != "intro":
                # Two double-tracked guitars: the same chord, different picking patterns.
                for name, pattern in (("guitar_l", (0, 3, 6, 9, 12, 15)),
                                      ("guitar_r", (2, 5, 8, 11, 14))):
                    for sixteenth in pattern:
                        o = b0 + int(sixteenth * beat / 4 * sr)
                        for interval in (0, 7, 12):
                            f = root * 2 ** (interval / 12) * 2
                            ln = min(int(0.5 * sr), n - o)
                            if ln > 0:
                                mono[name][o : o + ln] += 0.2 * level * _pluck(f, ln, sr, rng)
                # Keys: short stabs on the off-beats.
                for k in (1, 3):
                    o = b0 + int((k + 0.5) * beat * sr)
                    ln = min(int(0.3 * sr), n - o)
                    if ln > 0:
                        tk = np.arange(ln) / sr
                        stab = sum(np.sin(2 * np.pi * root * 4 * 2 ** (i / 12) * tk)
                                   for i in (0, 4, 7)) * np.exp(-tk * 9)
                        mono["keys"][o : o + ln] += 0.15 * level * stab
            if label in ("verse", "chorus"):
                for half in range(2):
                    v0 = b0 + int(half * 2 * beat * sr)
                    v1 = min(n, v0 + int(1.8 * beat * sr))
                    tv = np.arange(v1 - v0) / sr
                    deg = (0, 3, 7, 5)[(bar_i + b + half) % 4]
                    f0 = root * 2 * 2 ** (deg / 12)
                    vow = np.array([VOWELS[(bar_i + b + half) % 3]])
                    env_v = np.minimum(1.0, tv * 30) * np.minimum(1.0, (tv[-1] - tv) * 30)
                    vib = 1 + 0.012 * np.sin(2 * np.pi * 5.5 * tv)
                    mono["lead_vocal"][v0:v1] += 0.3 * min(1.0, level + 0.3) * env_v * _voice(
                        f0 * vib, vow, sr)
                    if label == "chorus":
                        for name, ratio, shift in (("backing_l", 2 ** (4 / 12), 0.03),
                                                   ("backing_r", 2 ** (7 / 12), 0.05)):
                            vw = np.array([VOWELS[(bar_i + b + half + 1) % 3]])
                            mono[name][v0:v1] += 0.16 * env_v * _voice(
                                f0 * ratio * (1 + 0.01 * np.sin(2 * np.pi * 5.0 * tv + shift)),
                                vw, sr)
        # A riser into every chorus: filtered noise opening upward, overhead.
        if si + 1 < len(bars) and bars[si + 1][0] == "chorus":
            r_len = int(2 * 4 * beat * sr)
            e1 = int((bar_i + n_bars) * 4 * beat * sr)
            s1 = max(0, e1 - r_len)
            sweep = np.linspace(0, 1, e1 - s1)
            noise = rng.standard_normal(e1 - s1)
            mono["fx"][s1:e1] += 0.25 * sosfilt(butter(2, [600, 7000], "bandpass", fs=sr,
                                                       output="sos"), noise) * sweep**2
        bar_i += n_bars
    song = ObjectSong(sample_rate=sr, tempo_bpm=tempo_bpm, sections=sections, specs=LEAVES,
                      mono=mono)
    for s in LEAVES:
        gl, gr = pan_gains(s.az)
        song.stereo[s.name] = np.stack([gl * mono[s.name], gr * mono[s.name]])
    peak = max(float(np.max(np.abs(song.mix))), 1e-9)
    k = 0.7 / peak
    song.mono = {a: v * k for a, v in song.mono.items()}
    song.stereo = {a: v * k for a, v in song.stereo.items()}
    return song
