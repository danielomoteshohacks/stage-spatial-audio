import numpy as np
import pytest

from stage.stream.segments import Assembler, chunk_spans

SR = 8000


@pytest.mark.parametrize("n_s", [3.0, 9.5, 20.0, 47.3, 61.0])
def test_spans_cover_the_song_overlap_and_end_flush(n_s):
    n = int(n_s * SR)
    spans = chunk_spans(n, SR, chunk_s=10.0, overlap_s=1.0, first_s=4.0)
    assert spans[0].start == 0 and spans[-1].end == n
    assert spans[0].first and spans[-1].last and sum(s.last for s in spans) == 1
    for a, b in zip(spans[:-1], spans[1:], strict=True):
        assert b.start == a.end - SR  # one second of overlap
    if len(spans) > 2:
        assert spans[0].end - spans[0].start <= 4.0 * SR + 1


@pytest.mark.parametrize("n_s", [3.0, 20.0, 47.3])
def test_identity_renderer_returns_the_input_exactly(n_s):
    rng = np.random.default_rng(0)
    n = int(n_s * SR)
    x = rng.standard_normal((2, n)).astype(np.float32)
    spans = chunk_spans(n, SR, chunk_s=10.0, overlap_s=1.0, first_s=4.0)
    asm = Assembler(n, SR)
    out = np.zeros_like(x)
    pos = 0
    for sp in spans:
        start, fin = asm.push(sp, x[:, sp.start : sp.end])
        assert start == pos  # segments are contiguous: nothing is released twice or skipped
        out[:, start : start + fin.shape[1]] = fin
        pos = start + fin.shape[1]
    assert pos == n
    np.testing.assert_allclose(out, x, atol=2e-6)


def test_chunks_that_differ_by_a_small_gain_are_blended_not_stepped():
    # Each chunk is the same tone at a slightly different level (what a per-chunk loudness match
    # does). The seam must be smooth: the largest sample-to-sample step at the cross-fades may
    # not exceed the tone's own steepest step by more than a rounding.
    n = 12 * SR
    t = np.arange(n) / SR
    tone = np.stack([np.sin(2 * np.pi * 220 * t)] * 2).astype(np.float32)
    spans = chunk_spans(n, SR, chunk_s=5.0, overlap_s=1.0, first_s=3.0)
    asm = Assembler(n, SR)
    parts = []
    for i, sp in enumerate(spans):
        gain = 1.0 + 0.04 * (-1) ** i  # +/- 0.35 dB, alternately
        parts.append(asm.push(sp, tone[:, sp.start : sp.end] * gain)[1])
    y = np.concatenate(parts, axis=1)
    assert y.shape[1] == n
    step_tone = np.abs(np.diff(tone[0])).max()
    assert np.abs(np.diff(y[0])).max() < step_tone * 1.06
    # And the level stays inside the two chunk gains everywhere.
    assert y[0].max() <= 1.041 and np.abs(y[0]).max() >= 0.95
