"""Write a generated stereo test track: sine tones and noise bursts panned left, centre and right.

Usage:
    python scripts/make_test_signal.py out.flac [--seconds 10] [--sample-rate 44100]

Generated, so it is free of any rights question and can be shared in bug reports. It is not
music: use it to check that the pipeline and the backend run end to end, never to judge how a
render sounds. Write it outside the repository, or let .gitignore keep it out (it ignores *.wav
and *.flac).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

#: Constant-power pan positions, in the 0 (left) to 1 (right) convention.
PANS = {"left": 0.1, "centre": 0.5, "right": 0.9}


def _pan(mono: np.ndarray, position: float) -> np.ndarray:
    theta = position * np.pi / 2.0
    return np.stack([np.cos(theta) * mono, np.sin(theta) * mono])


def make_test_signal(seconds: float = 10.0, sample_rate: int = 44100, seed: int = 0) -> np.ndarray:
    """Return (2, n) float64: a tone and a train of noise bursts at each of the three pans.

    Deterministic for a given seed, so tests and measurements are repeatable.
    """
    n = int(round(seconds * sample_rate))
    t = np.arange(n) / sample_rate
    rng = np.random.default_rng(seed)
    out = np.zeros((2, n))
    tones = {"left": 220.0, "centre": 440.0, "right": 660.0}
    for i, (name, pos) in enumerate(PANS.items()):
        out += _pan(0.12 * np.sin(2 * np.pi * tones[name] * t), pos)
        # 150 ms bursts every 0.75 s, staggered per position so each one is heard on its own.
        bursts = np.zeros(n)
        burst_len = int(0.15 * sample_rate)
        env = np.hanning(burst_len)
        for onset in np.arange(0.25 * i, seconds, 0.75):
            a = int(onset * sample_rate)
            b = min(a + burst_len, n)
            bursts[a:b] += 0.2 * env[: b - a] * rng.standard_normal(b - a)
        out += _pan(bursts, pos)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("path")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--sample-rate", type=int, default=44100)
    args = parser.parse_args()
    x = make_test_signal(args.seconds, args.sample_rate)
    out = Path(args.path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), x.T, args.sample_rate, subtype="PCM_24")
    print(f"wrote {out}: {args.seconds:.1f} s, {args.sample_rate} Hz, peak {np.max(np.abs(x)):.3f}")


if __name__ == "__main__":
    main()
