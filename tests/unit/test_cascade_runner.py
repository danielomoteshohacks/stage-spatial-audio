import numpy as np
import pytest

from stage.separation.cascade.runner import (
    GpuTiming,
    chunk_plan,
    chunked_apply,
    crossfade_window,
)


def test_chunk_plan_covers_the_signal_and_ends_flush():
    for n in (1000, 5000, 5001, 12345):
        starts = chunk_plan(n, 2000, 500)
        assert starts[0] == 0
        assert starts[-1] + 2000 >= n or n <= 2000
        covered = np.zeros(max(n, 2000), bool)
        for s in starts:
            covered[s : s + 2000] = True
        assert covered[:n].all()


def test_crossfade_neighbours_sum_to_one():
    w = crossfade_window(2000, 500)
    assert w[:500] + w[-500:] == pytest.approx(np.ones(500), abs=1e-6)


@pytest.mark.parametrize("n", [900, 2000, 7001, 20000])
def test_identity_model_reproduces_the_input_exactly(n):
    rng = np.random.default_rng(n)
    x = rng.standard_normal((2, n)).astype(np.float32)
    y = chunked_apply(lambda c: c[None], x, chunk=2000, overlap=500, n_stems=1)
    assert y.shape == (1, 2, n)
    np.testing.assert_allclose(y[0], x, atol=1e-5)


def test_two_stem_model_whose_stems_sum_to_the_input_stays_consistent():
    rng = np.random.default_rng(1)
    x = rng.standard_normal((2, 9000)).astype(np.float32)
    # Each chunk is split by a smooth function of position inside the chunk (what a mask does at
    # a chunk edge): the cross-fade must still return stems that add up to the input.
    def forward(c):
        g = np.linspace(0.2, 0.8, c.shape[1], dtype=np.float32)
        return np.stack([c * g, c * (1 - g)])
    y = chunked_apply(forward, x, chunk=2000, overlap=500, n_stems=2)
    np.testing.assert_allclose(y.sum(axis=0), x, atol=1e-5)


def test_timing_per_minute():
    t = GpuTiming(seconds=6.0, audio_seconds=120.0)
    assert t.per_minute == pytest.approx(3.0)
