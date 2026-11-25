"""Chunk spans and the overlap-add assembler that turns rendered chunks into final segments.

A song is rendered in chunks that overlap by `overlap_s`. Each chunk is rendered alone (so the
first can be played while the rest are still being made), and neighbouring chunks are joined with
sin^2 cross-fades over the overlap: the two ramps sum to exactly one, so a renderer that returned
its input unchanged would give back the input exactly, and one whose chunks differ slightly (the
timbre match and the loudness match are computed per chunk, a few tenths of a dB apart) is
blended instead of stepped. The first chunk is shorter (`first_s`) so the first sound arrives
sooner.

`Assembler.push` takes a rendered chunk and returns the samples that are final: everything before
the overlap with the next chunk, which has to wait for it. The last chunk finalises the rest.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from stage.separation.cascade.runner import crossfade_window


@dataclass(frozen=True)
class Span:
    index: int
    start: int  # first sample of the chunk in the song
    end: int  # one past the last
    first: bool
    last: bool


def chunk_spans(n: int, sample_rate: int, chunk_s: float = 20.0, overlap_s: float = 1.5,
                first_s: float = 8.0) -> list[Span]:
    """Spans covering `n` samples. The first is `first_s` long, the others `chunk_s`; each
    overlaps the previous by `overlap_s`; a short remainder is absorbed by the last span."""
    ov = int(overlap_s * sample_rate)
    first = max(int(first_s * sample_rate), 2 * ov)
    chunk = max(int(chunk_s * sample_rate), 2 * ov)
    if n <= first + ov:
        return [Span(0, 0, n, True, True)]
    spans: list[tuple[int, int]] = [(0, first)]
    while spans[-1][1] < n:
        start = spans[-1][1] - ov
        end = min(start + chunk, n)
        spans.append((start, end))
    # A last span shorter than twice the overlap is merged into its predecessor.
    if len(spans) > 1 and spans[-1][1] - spans[-1][0] < 2 * ov:
        s0, _ = spans[-2]
        spans[-2:] = [(s0, n)]
    return [Span(i, s, e, i == 0, i == len(spans) - 1) for i, (s, e) in enumerate(spans)]


class Assembler:
    """Cross-fades rendered chunks into one signal and releases samples as they become final."""

    def __init__(self, n: int, overlap: int, channels: int = 2) -> None:
        self.overlap = overlap
        self.n = n
        self.channels = channels
        self.released = 0  # samples handed out so far
        self._tail: NDArray | None = None  # faded-down end of the previous chunk
        self._tail_start = 0

    def push(self, span: Span, chunk: NDArray) -> tuple[int, NDArray]:
        """Add a rendered chunk; returns (start sample, final samples) newly released."""
        chunk = np.asarray(chunk, dtype=np.float32)
        m = chunk.shape[1]
        ov = min(self.overlap, m // 2)
        w = crossfade_window(m, ov) if ov else np.ones(m, np.float32)
        if span.first:
            w = w.copy()
            w[:ov] = 1.0
        if span.last:
            w = w.copy()
            w[m - ov :] = 1.0
        y = chunk * w
        if self._tail is not None:
            k = self._tail.shape[1]
            y[:, :k] += self._tail  # the previous chunk's faded-down end, over the same samples
        if span.last:
            out_start = self.released
            self.released = span.end
            return out_start, y[:, out_start - span.start :]
        cut = m - ov  # the last `ov` samples wait for the next chunk
        self._tail = y[:, cut:].copy()
        self._tail_start = span.start + cut
        out_start = self.released
        self.released = span.start + cut
        return out_start, y[:, out_start - span.start : cut]
