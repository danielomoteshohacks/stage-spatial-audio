import numpy as np
import pytest

from stage.render import (
    SECTOR_CENTRES_DEG,
    apply_sectors,
    sector_azimuths,
    sector_weights,
    widen_azimuth,
)

# Literal list, not derived from the implementation, so a wrong grid cannot pass.
EXPECTED_CENTRES = [-30, -25, -20, -15, -10, -5, 0, 5, 10, 15, 20, 25, 30]


def test_centres_are_the_specified_grid():
    assert np.allclose(SECTOR_CENTRES_DEG, EXPECTED_CENTRES)


@pytest.mark.parametrize("index", range(13))
def test_each_centre_peaks_in_its_own_sector(index):
    w = sector_weights(float(EXPECTED_CENTRES[index]))
    assert w.shape == (13,)
    assert int(np.argmax(w)) == index


@pytest.mark.parametrize("angle", [-30.0, 30.0, -29.99, 29.99])
def test_weights_sum_to_one_at_edges(angle):
    assert abs(sector_weights(angle).sum() - 1.0) < 1e-12


def test_weights_sum_to_one_on_dense_sweep():
    angles = np.linspace(-30.0, 30.0, 6001)
    w = sector_weights(angles)
    assert w.shape == (13, 6001)
    assert np.max(np.abs(w.sum(axis=0) - 1.0)) < 1e-12
    assert np.all(w >= 0.0)


def test_weights_stay_finite_and_normalised_far_outside_range():
    w = sector_weights(np.array([-170.0, 90.0, 1e4]))
    assert np.all(np.isfinite(w))
    assert np.allclose(w.sum(axis=0), 1.0, atol=1e-12)
    assert int(np.argmax(w[:, 1])) == 12


def test_halfway_between_centres_is_shared_equally():
    w = sector_weights(2.5)
    assert abs(w[6] - w[7]) < 1e-12
    assert w[6] > w[5] and w[6] > w[8]


@pytest.mark.parametrize(
    ("theta", "expected"), [(30.0, 57.3), (15.0, 33.75), (5.0, 11.9)]
)
def test_widen_reference_values(theta, expected):
    assert abs(float(widen_azimuth(theta, 2.4)) - expected) < 0.05


def test_widen_zero_maps_to_zero():
    assert float(widen_azimuth(0.0, 2.4)) == 0.0


@pytest.mark.parametrize("beta", [1.0, 1.7, 2.4])
def test_widen_odd_and_strictly_monotonic(beta):
    theta = np.linspace(0.0, 90.0, 901)
    pos = widen_azimuth(theta, beta)
    assert np.allclose(widen_azimuth(-theta, beta), -pos, atol=1e-12)
    assert np.all(np.diff(pos) > 0.0)
    assert np.all(pos < 80.0)


@pytest.mark.parametrize("beta", [0.99, 2.41, -1.0])
def test_widen_rejects_beta_out_of_range(beta):
    with pytest.raises(ValueError):
        widen_azimuth(10.0, beta)


def test_sector_azimuths_are_ordered_and_symmetric():
    az = sector_azimuths(2.4)
    assert az.shape == (13,)
    assert np.all(np.diff(az) > 0.0)
    assert np.allclose(az, -az[::-1], atol=1e-12)
    assert abs(az[-1] - 57.3) < 0.05


def test_apply_sectors_shape_and_energy_conserved():
    rng = np.random.default_rng(0)
    power = rng.random((40, 129)) * 10.0
    angle = rng.uniform(-30.0, 30.0, power.shape)
    out = apply_sectors(power, angle)
    assert out.shape == (13, 40, 129)
    assert out.dtype == np.float64
    assert np.max(np.abs(out.sum(axis=0) - power)) < 1e-12
    assert np.all(out >= 0.0)


def test_apply_sectors_silent_input_is_zero_not_nan():
    power = np.zeros((5, 16))
    angle = np.full(power.shape, 12.0)
    out = apply_sectors(power, angle)
    assert np.all(out == 0.0)
    assert not np.any(np.isnan(out))


def test_apply_sectors_energy_goes_to_the_matching_sector():
    power = np.ones((2, 3))
    out = apply_sectors(power, np.full(power.shape, 10.0))
    assert int(np.argmax(out[:, 0, 0])) == 8  # centre +10 is index 8


def test_apply_sectors_rejects_bad_shapes():
    with pytest.raises(ValueError):
        apply_sectors(np.zeros((2, 3, 4)), np.zeros((2, 3, 4)))
    with pytest.raises(ValueError):
        apply_sectors(np.zeros((2, 3)), np.zeros((3, 3)))
