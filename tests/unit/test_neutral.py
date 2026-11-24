"""Timbre matcher and loudness match: tone back to the record, image and bass untouched."""

import numpy as np
import pytest
from scipy.signal import lfilter

from stage.guard.checks import check_timbre
from stage.guard.loudness import integrated_loudness
from stage.spatial.neutral import (
    correction_filter,
    match_loudness_upper,
    match_timbre,
    split_low_high,
    timbre_correction_db,
)

FS = 44100


def _pink(n, seed=0):
    rng = np.random.default_rng(seed)
    w = rng.standard_normal((2, n))
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1, -2.494956002, 2.017265875, -0.522189400]
    return 0.1 * lfilter(b, a, w, axis=-1)


def test_a_coloured_render_is_pulled_back_to_the_original():
    x = _pink(8 * FS)
    _, high = split_low_high(x, FS)
    # Colour the render: a broad +6 dB presence bump and a -5 dB dip, both ears.
    centres = np.array([500.0, 1000.0, 3000.0, 8000.0])
    bump = correction_filter(centres, np.array([0.0, -5.0, 6.0, 0.0]), FS)
    coloured = np.stack([np.convolve(c, bump)[: c.size] for c in high])
    before = check_timbre(high, coloured, FS).max_deviation_db
    fixed, info = match_timbre(high, coloured, FS)
    after = check_timbre(high, fixed, FS).max_deviation_db
    assert before > 4.0 and after < 1.5 and info["max_correction_db"] > 4.0


def test_the_correction_is_identical_for_both_ears_so_the_image_is_kept():
    x = _pink(4 * FS)
    _, high = split_low_high(x, FS)
    render = np.stack([high[0], 0.5 * np.roll(high[0], 20)])  # an interaural level and delay
    fixed, _ = match_timbre(high, render, FS)
    for y in (render, fixed):
        assert np.sum(y[1] ** 2) / np.sum(y[0] ** 2) == pytest.approx(
            np.sum(render[1] ** 2) / np.sum(render[0] ** 2), rel=0.05)
    lag = np.argmax(np.correlate(fixed[1][:4096], fixed[0][:4096], "full")) - 4095
    assert lag == 20


def test_the_correction_is_flat_below_the_crossover():
    h = correction_filter(np.array([125.0, 1000.0]), np.array([8.0, 8.0]), FS)
    spec = np.abs(np.fft.rfft(h, 1 << 16))
    f = np.fft.rfftfreq(1 << 16, 1 / FS)
    assert np.max(np.abs(20 * np.log10(spec[(f > 5) & (f < 60)]))) < 0.3


def test_corrections_change_shape_not_level():
    x = _pink(4 * FS)
    _, high = split_low_high(x, FS)
    _, corr = timbre_correction_db(high, 2.0 * high, FS)
    assert np.max(np.abs(corr)) < 0.05


def test_loudness_match_moves_only_the_upper_band():
    x = _pink(6 * FS)
    low, high = split_low_high(x, FS)
    upper, gain = match_loudness_upper(x, low, 3.0 * high, FS)
    assert integrated_loudness(low + upper, FS) == pytest.approx(integrated_loudness(x, FS),
                                                                 abs=0.02)
    assert gain == pytest.approx(1 / 3, rel=0.02)
