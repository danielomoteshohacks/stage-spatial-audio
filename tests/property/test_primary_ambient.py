"""Properties that must hold for any input, checked on many random inputs."""

import numpy as np
import pytest

from stage.analysis import analyse_stereo

HOP = 1024


def _random_spectra(seed):
    rng = np.random.default_rng(seed)
    shape = (40, 129)
    scale = 10.0 ** rng.uniform(-3, 3)
    x_l = scale * (rng.standard_normal(shape) + 1j * rng.standard_normal(shape))
    x_r = scale * (rng.standard_normal(shape) + 1j * rng.standard_normal(shape))
    return x_l, x_r


@pytest.mark.parametrize("seed", range(25))
def test_primary_plus_ambient_equals_input(seed):
    x_l, x_r = _random_spectra(seed)
    res = analyse_stereo(x_l, x_r, hop=HOP, sample_rate=44100)
    total = res.primary + res.ambient
    assert np.allclose(total[0], x_l, rtol=1e-12, atol=1e-12 * np.abs(x_l).max())
    assert np.allclose(total[1], x_r, rtol=1e-12, atol=1e-12 * np.abs(x_r).max())


@pytest.mark.parametrize("seed", range(25))
def test_ambient_is_orthogonal_to_the_panning_direction(seed):
    x_l, x_r = _random_spectra(seed)
    res = analyse_stereo(x_l, x_r, hop=HOP, sample_rate=44100)
    along = res.gain_l * res.ambient[0] + res.gain_r * res.ambient[1]
    assert np.max(np.abs(along)) < 1e-9 * max(np.abs(x_l).max(), np.abs(x_r).max())


@pytest.mark.parametrize("seed", range(25))
def test_energy_splits_exactly_between_primary_and_ambient(seed):
    x_l, x_r = _random_spectra(seed)
    res = analyse_stereo(x_l, x_r, hop=HOP, sample_rate=44100)
    energy_in = np.abs(x_l) ** 2 + np.abs(x_r) ** 2
    energy_split = np.sum(np.abs(res.primary) ** 2, axis=0) + np.sum(
        np.abs(res.ambient) ** 2, axis=0
    )
    assert np.allclose(energy_in, energy_split, rtol=1e-10)


@pytest.mark.parametrize("seed", range(25))
def test_outputs_stay_in_range(seed):
    x_l, x_r = _random_spectra(seed)
    res = analyse_stereo(x_l, x_r, hop=HOP, sample_rate=44100)
    assert np.all(np.abs(res.position) <= 1.0 + 1e-12)
    assert np.all(np.abs(res.angle_deg) <= 30.0 + 1e-9)
    assert np.all((res.coherence >= 0) & (res.coherence <= 1))
    assert np.all((res.inphase_coherence >= 0) & (res.inphase_coherence <= 1))
