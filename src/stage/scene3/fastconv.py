"""Batched partitioned convolution with cached filter spectra, in float32.

The v2 renderer called `scipy.signal.oaconvolve` once per virtual source: every call transformed
the filter again, and every source was transformed and inverse-transformed on its own. Here the
whole scene is one overlap-add pass (decision 0027):

* the signal is cut into blocks of `block` samples; each block of each source is transformed
  once (real FFT of size N >= block + filter length - 1);
* each filter's spectrum is computed once per FFT size and cached (`spectrum`), keyed by the
  caller, so a position that comes back (the same kick every bar, the same chunk after chunk)
  costs nothing;
* when only the sum of the sources is wanted, the products are summed in the frequency domain
  and each block is inverse-transformed twice (left ear, right ear) however many sources there
  are; sources that share a filter are first summed in the time domain by the caller.
  When per-source outputs are wanted (the object stems), each source gets its own inverse.

Everything is float32 (complex64): half the memory traffic of v2's float64, and the FFT is about
twice as fast. The partitioning is uniform (one FFT size); a non-uniform scheme matters for
latency in real-time use, not for offline rendering.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Hashable, Sequence

import numpy as np
import scipy.fft as sfft
from numpy.typing import NDArray

_CACHE: OrderedDict[tuple[Hashable, int], NDArray[np.complex64]] = OrderedDict()
_CACHE_MAX = 4096


def fft_size(block: int, filter_len: int) -> int:
    return int(sfft.next_fast_len(block + filter_len - 1, real=True))


def spectrum(key: Hashable, h: NDArray, n_fft: int) -> NDArray[np.complex64]:
    """rfft of a (2, K) filter at `n_fft`, cached by (key, n_fft)."""
    k = (key, n_fft)
    got = _CACHE.get(k)
    if got is not None:
        _CACHE.move_to_end(k)
        return got
    out = sfft.rfft(np.asarray(h, dtype=np.float32), n_fft, axis=-1).astype(np.complex64)
    _CACHE[k] = out
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return out


def clear_cache() -> None:
    _CACHE.clear()


def convolve_feeds(signals: Sequence[NDArray], keys: Sequence[Hashable],
                   filters: Sequence[NDArray], n: int, block: int = 8192,
                   per_feed: bool = False) -> NDArray[np.float32] | list[NDArray[np.float32]]:
    """Convolve each (n,) signal with its (2, K) filter and sum: returns (2, n + K - 1).

    With `per_feed`, a list of (2, n + K - 1) outputs, one per source. Signals shorter than n are
    zero-padded. `keys` identify the filters for the spectrum cache.
    """
    if not signals:
        return [] if per_feed else np.zeros((2, n), dtype=np.float32)
    k_max = max(f.shape[-1] for f in filters)
    nfft = fft_size(block, k_max)
    total = n + k_max - 1
    n_blocks = -(-n // block)
    specs = np.stack([spectrum(k, f, nfft) for k, f in zip(keys, filters, strict=True)])  # F,2,K
    f_n = len(signals)
    sig = np.zeros((f_n, n_blocks * block), dtype=np.float32)
    for i, s in enumerate(signals):
        sig[i, : min(n, s.size)] = s[:n]
    blocks = sig.reshape(f_n, n_blocks, block)
    out_len = n_blocks * block + nfft
    if per_feed:
        outs = [np.zeros((2, out_len), dtype=np.float32) for _ in range(f_n)]
    else:
        out = np.zeros((2, out_len), dtype=np.float32)
    step = 16  # blocks per batch bounds memory: F x step x (nfft/2+1) complex64
    for b0 in range(0, n_blocks, step):
        b1 = min(n_blocks, b0 + step)
        xs = sfft.rfft(blocks[:, b0:b1], nfft, axis=-1).astype(np.complex64)  # F, B, K
        if per_feed:
            y = sfft.irfft(xs[:, :, None, :] * specs[:, None, :, :], nfft, axis=-1)  # F,B,2,N
            for i in range(f_n):
                for j, b in enumerate(range(b0, b1)):
                    outs[i][:, b * block : b * block + nfft] += y[i, j]
        else:
            acc = np.einsum("fbk,fck->cbk", xs, specs, optimize=True)  # 2, B, K
            y = sfft.irfft(acc, nfft, axis=-1)  # 2, B, N
            for j, b in enumerate(range(b0, b1)):
                out[:, b * block : b * block + nfft] += y[:, j]
    if per_feed:
        return [o[:, :total] for o in outs]
    return out[:, :total]
