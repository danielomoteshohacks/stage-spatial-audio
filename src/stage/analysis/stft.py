"""Short-time Fourier transform with exact reconstruction.

This is the reference implementation. It is written for clarity first, so that the
Rust core can be checked against it bin for bin.

Conventions
-----------
* Signals have shape (channels, samples). Spectrograms have shape (channels, frames, bins).
* The window is a periodic square-root Hann window, used for both analysis and synthesis.
  Its square is a periodic Hann window, which sums to exactly 1 at 50 percent overlap,
  so analysis followed by synthesis returns the input unchanged.
* Frames are not centred. Zeros are padded so that every input sample is covered by
  enough overlapping frames, and the padding is removed again by `istft`.
"""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

DEFAULT_N_FFT = 2048
DEFAULT_HOP = 1024


def sqrt_hann(n_fft: int) -> np.ndarray:
    """Periodic square-root Hann window of length `n_fft`.

    Periodic (not symmetric) on purpose: the periodic form is the one whose overlap-added
    square is exactly constant, which is what makes reconstruction exact.
    """
    n = np.arange(n_fft)
    return np.sqrt(0.5 - 0.5 * np.cos(2.0 * np.pi * n / n_fft))


def _layout(n_samples: int, n_fft: int, hop: int) -> tuple[int, int, int]:
    """Return (left_pad, right_pad, n_frames) for a signal of `n_samples` samples."""
    left = n_fft - hop
    # Extra right padding of (n_fft - hop) gives the last real samples full overlap.
    total = left + n_samples + (n_fft - hop)
    n_frames = max(1, -(-(total - n_fft) // hop) + 1)  # ceiling division
    needed = (n_frames - 1) * hop + n_fft
    right = needed - left - n_samples
    return left, right, n_frames


def _check(n_fft: int, hop: int) -> None:
    if n_fft <= 0 or hop <= 0 or hop > n_fft:
        raise ValueError("need 0 < hop <= n_fft")


def stft(x: np.ndarray, n_fft: int = DEFAULT_N_FFT, hop: int = DEFAULT_HOP) -> np.ndarray:
    """Transform signals of shape (channels, samples) to (channels, frames, bins)."""
    _check(n_fft, hop)
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 2:
        raise ValueError("expected an array of shape (channels, samples)")
    left, right, _ = _layout(x.shape[1], n_fft, hop)
    padded = np.pad(x, ((0, 0), (left, right)))
    window = sqrt_hann(n_fft)
    frames = sliding_window_view(padded, n_fft, axis=1)[:, ::hop, :]
    return np.fft.rfft(frames * window, axis=-1)


def istft(
    spec: np.ndarray,
    n_samples: int,
    n_fft: int = DEFAULT_N_FFT,
    hop: int = DEFAULT_HOP,
) -> np.ndarray:
    """Inverse of `stft`. Returns signals of shape (channels, n_samples)."""
    _check(n_fft, hop)
    spec = np.asarray(spec)
    n_channels, n_frames, _ = spec.shape
    window = sqrt_hann(n_fft)
    frames = np.fft.irfft(spec, n=n_fft, axis=-1) * window

    length = (n_frames - 1) * hop + n_fft
    out = np.zeros((n_channels, length))
    norm = np.zeros(length)
    w2 = window**2
    for t in range(n_frames):
        start = t * hop
        out[:, start : start + n_fft] += frames[:, t, :]
        norm[start : start + n_fft] += w2

    left = n_fft - hop
    # Dividing by the overlapped window energy keeps the result exact for any hop.
    out = out[:, left : left + n_samples] / np.maximum(norm[left : left + n_samples], 1e-12)
    return out
