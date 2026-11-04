"""Reading audio into the array layout used everywhere in Stage: (channels, samples)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf


def to_stereo(x: np.ndarray) -> np.ndarray:
    """Return a (2, samples) array. Mono is duplicated; more than two channels is an error."""
    x = np.asarray(x)
    if x.ndim != 2:
        raise ValueError("expected an array of shape (channels, samples)")
    if x.shape[0] == 1:
        return np.repeat(x, 2, axis=0)
    if x.shape[0] == 2:
        return x
    raise ValueError(f"expected mono or stereo audio, got {x.shape[0]} channels")


def read_audio(
    path: str | Path,
    *,
    start_s: float = 0.0,
    duration_s: float | None = None,
) -> tuple[np.ndarray, int]:
    """Read a file as float64 with shape (channels, samples), plus its sample rate.

    Only the requested part is read, so a short excerpt of a long file is cheap.
    """
    info = sf.info(str(path))
    start = int(round(start_s * info.samplerate))
    frames = -1 if duration_s is None else int(round(duration_s * info.samplerate))
    data, sample_rate = sf.read(
        str(path), start=start, frames=frames, dtype="float64", always_2d=True
    )
    return data.T.copy(), sample_rate
