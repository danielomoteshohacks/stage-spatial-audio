"""Training data: MUSDB18-HQ tracks and teacher pseudo-labels, with Demucs-style augmentation.

Folder layout (MUSDB18-HQ's own, and the same for pseudo-labelled music):

    <root>/<track>/{mixture,vocals,drums,bass,other}.wav

Augmentation, each applied per example (Defossez et al. 2019; HT Demucs):
* remix: every stem of an example may come from a different track (the largest single gain in
  Demucs v2), so the network cannot learn a song's arrangement instead of its sources;
* random gain per stem (-3 to +3 dB), channel swap, sign flip;
* tempo and pitch: a common speed change of -/+ 6 percent by resampling, which shifts pitch and
  tempo together (Demucs' "repitch" without the separate time stretch).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

STEMS = ("vocals", "drums", "bass", "other")


@dataclass
class Track:
    name: str
    folder: Path
    frames: int
    sample_rate: int
    #: Stems from the teacher for distillation (MUSDB18-HQ gives ground truth; other music only
    #: teacher stems). None when the folder has ground truth only.
    teacher: Path | None = None


def list_tracks(root: str | Path, teacher_root: str | Path | None = None) -> list[Track]:
    root = Path(root)
    out = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        if not all((folder / f"{s}.wav").is_file() for s in STEMS):
            continue
        info = sf.info(str(folder / "vocals.wav"))
        t = Path(teacher_root) / folder.name if teacher_root else None
        out.append(Track(folder.name, folder, info.frames, info.samplerate,
                         t if t is not None and t.is_dir() else None))
    return out


def read_segment(path: Path, start: int, frames: int) -> np.ndarray:
    x, _ = sf.read(str(path), start=start, frames=frames, dtype="float32", always_2d=True)
    x = x.T
    if x.shape[0] == 1:
        x = np.repeat(x, 2, axis=0)
    if x.shape[1] < frames:
        x = np.pad(x, ((0, 0), (0, frames - x.shape[1])))
    return x


class Augment:
    def __init__(self, seed: int | None = None, remix: bool = True, gain_db: float = 3.0,
                 speed: float = 0.06) -> None:
        self.rng = random.Random(seed)
        self.remix = remix
        self.gain_db = gain_db
        self.speed = speed

    def example(self, tracks: list[Track], seconds: float, sample_rate: int
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        """(mixture (2, n), stems (4, 2, n), teacher stems (4, 2, n) or None)."""
        rate = 1.0 + self.rng.uniform(-self.speed, self.speed) if self.speed else 1.0
        n = int(seconds * sample_rate)
        read_n = int(round(n * rate)) + 8
        base = self.rng.choice(tracks)
        stems, teach = [], []
        use_teacher = base.teacher is not None
        for s in STEMS:
            tr = self.rng.choice(tracks) if self.remix and not use_teacher else base
            start = self.rng.randrange(0, max(1, tr.frames - read_n))
            x = read_segment(tr.folder / f"{s}.wav", start, read_n)
            if use_teacher:
                teach.append(read_segment(tr.teacher / f"{s}.wav", start, read_n))
            stems.append(x)
        y = np.stack(stems)
        t = np.stack(teach) if use_teacher else None
        if rate != 1.0:
            up, down = 100, int(round(100 * rate))
            y = resample_poly(y, up, down, axis=-1)
            t = resample_poly(t, up, down, axis=-1) if t is not None else None
        y, t = y[..., :n], (t[..., :n] if t is not None else None)
        g = 10.0 ** (np.array([self.rng.uniform(-self.gain_db, self.gain_db) for _ in STEMS])
                     / 20.0)[:, None, None]
        y = y * g
        t = t * g if t is not None else None
        if self.rng.random() < 0.5:
            y = y[:, ::-1]
            t = t[:, ::-1] if t is not None else None
        if self.rng.random() < 0.5:
            y = -y
            t = -t if t is not None else None
        y = np.ascontiguousarray(y, dtype=np.float32)
        return y.sum(axis=0), y, (np.ascontiguousarray(t, dtype=np.float32)
                                  if t is not None else None)


def synthetic_multitrack(n_examples: int, seconds: float, sample_rate: int, seed: int = 0
                         ) -> tuple[np.ndarray, np.ndarray]:
    """A deterministic toy multitrack for tests: (mixtures (B, 2, n), stems (B, 4, 2, n)).

    vocals: a vibrato tone with harmonics, centred; drums: decaying noise bursts, wide; bass: a
    low sine, centred; other: a chord panned left. Each source has its own spectrum, rhythm and
    stereo position, which is what the separator's features are built to use.
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * sample_rate)
    t = np.arange(n) / sample_rate
    mixes, all_stems = [], []
    for _ in range(n_examples):
        f0 = rng.uniform(180, 320)
        vib = np.sin(2 * np.pi * 5.5 * t) * 6
        phase = 2 * np.pi * np.cumsum(f0 + vib) / sample_rate
        voc = sum(0.5 ** h * np.sin((h + 1) * phase) for h in range(4)) * 0.3
        voc = np.stack([voc, voc])
        drums = np.zeros((2, n))
        period = int(sample_rate * rng.uniform(0.2, 0.35))
        for k in range(0, n, period):
            m = min(2000, n - k)
            burst = rng.standard_normal((2, m)) * np.exp(-np.arange(m) / 300)
            drums[:, k : k + m] += 0.5 * burst
        bass = 0.4 * np.sin(2 * np.pi * rng.uniform(45, 70) * t)
        bass = np.stack([bass, bass])
        chord = sum(np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) for f in
                    rng.uniform(400, 900, 3)) * 0.12
        other = np.stack([chord, 0.3 * chord])
        stems = np.stack([voc, drums, bass, other]).astype(np.float32)
        mixes.append(stems.sum(axis=0))
        all_stems.append(stems)
    return np.stack(mixes), np.stack(all_stems)
