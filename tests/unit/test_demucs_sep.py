import importlib.util

import numpy as np
import pytest

from stage.separation import demucs_sep
from stage.separation.demucs_sep import (
    SeparationUnavailable,
    fit_length,
    pick_device,
    residual_snr_db,
)


def test_fit_length_trims_and_pads_to_the_exact_length():
    x = np.ones((2, 10))
    assert fit_length(x, 7).shape == (2, 7)
    padded = fit_length(x, 13)
    assert padded.shape == (2, 13) and np.all(padded[:, 10:] == 0)


def test_residual_snr_is_infinite_for_a_perfect_split_and_finite_otherwise():
    rng = np.random.default_rng(0)
    mix = rng.standard_normal((2, 1000))
    exact = {"a": 0.5 * mix, "b": 0.5 * mix}
    assert residual_snr_db(mix, exact) == float("inf")
    # Stems that sum to 90 percent of the mix leave a 10 percent residual: 20 dB.
    lossy = {"a": 0.45 * mix, "b": 0.45 * mix}
    assert residual_snr_db(mix, lossy) == pytest.approx(20.0)


@pytest.mark.parametrize(
    "device,cuda,expected",
    [
        ("auto", True, "cuda"),
        ("auto", False, "cpu"),
        ("cpu", True, "cpu"),
        ("cuda:1", False, "cuda:1"),
    ],
)
def test_pick_device(device, cuda, expected):
    assert pick_device(device, cuda) == expected


def test_pick_device_rejects_unknown_names():
    with pytest.raises(ValueError):
        pick_device("tpu", False)


def test_mono_input_is_rejected():
    with pytest.raises(ValueError):
        demucs_sep.separate(np.zeros((1, 100)), 44100)


_HAVE_DEPS = all(importlib.util.find_spec(m) is not None for m in ("torch", "demucs"))


@pytest.mark.skipif(_HAVE_DEPS, reason="torch and demucs are installed")
def test_missing_dependencies_raise_a_clear_error():
    with pytest.raises(SeparationUnavailable, match=r"\.\[separation\]"):
        demucs_sep.separate(np.zeros((2, 4410)), 44100)
