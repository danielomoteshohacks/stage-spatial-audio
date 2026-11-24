"""Interpolated head-related filters (analytic fallback here; the measured pack when cached)."""

import numpy as np
import pytest

from stage.spatial.hrtf import (
    BASE_DELAY,
    MAX_DB_PER_DEGREE,
    HrtfSet,
    analytic_pack,
    find_pack,
    get_hrtf,
    max_band_gradient,
)
from stage.spatial.hrtfpack import read_pack


@pytest.fixture(scope="module")
def pack():
    return analytic_pack()


@pytest.fixture(scope="module")
def long_set(pack):
    return HrtfSet(pack, 48000, 4096, diffuse_eq=False)


def test_moving_in_azimuth_never_changes_a_band_by_more_than_half_a_db_per_degree(long_set):
    worst = max_band_gradient(long_set)
    assert worst["azimuth"]["db_per_degree"] <= MAX_DB_PER_DEGREE, worst


def test_elevation_sweeps_are_continuous_too(long_set):
    # No step anywhere: the elevation cue's notch may sweep faster than azimuth changes, but the
    # interpolation itself adds no jump (decision 0012 reports the measured value).
    assert max_band_gradient(long_set)["elevation"]["db_per_degree"] < 1.0


@pytest.mark.skipif(find_pack() is None, reason="the measured HRTF pack is not cached here")
def test_measured_pack_meets_the_azimuth_target():
    hs = HrtfSet(read_pack(find_pack()), 48000, 4096, diffuse_eq=False)
    assert max_band_gradient(hs)["azimuth"]["db_per_degree"] <= MAX_DB_PER_DEGREE


def test_interpolation_at_a_grid_point_returns_that_point(pack):
    hs = HrtfSet(pack, 48000, 512, diffuse_eq=False)
    i = 123
    m = hs.logmag_db(pack.az_deg[i], pack.el_deg[i])[0]
    assert np.allclose(m, hs.logmag[i], atol=1e-6)
    it = hs.interpolation(pack.az_deg[i], pack.el_deg[i])
    assert it.w.max() == pytest.approx(1.0, abs=1e-6)


def test_barycentric_weights_are_convex(pack):
    hs = HrtfSet(pack, 48000, 512)
    rng = np.random.default_rng(0)
    it = hs.interpolation(rng.uniform(-180, 180, 500), rng.uniform(-89, 89, 500))
    assert np.all(it.w >= 0) and np.allclose(it.w.sum(axis=1), 1.0)


def test_left_source_reaches_the_left_ear_first_and_louder():
    hs = get_hrtf(48000, prefer="analytic")
    ir = hs.hrirs([90.0, -90.0], [0.0, 0.0])
    assert hs.itd_s(90.0)[0] > 0.5e-3  # SOFA convention: positive azimuth is the left
    left_src = ir[0]
    assert np.argmax(np.abs(left_src[0])) < np.argmax(np.abs(left_src[1]))
    assert np.sum(left_src[0] ** 2) > 2 * np.sum(left_src[1] ** 2)
    # The near ear's onset sits at the constant base delay.
    assert abs(int(np.argmax(np.abs(left_src[0]))) - BASE_DELAY) <= 3
    assert np.all(np.isfinite(ir))


def test_diffuse_field_eq_flattens_the_average_over_the_sphere(pack):
    hs = HrtfSet(pack, 48000, 512, diffuse_eq=True)
    w = np.ones(pack.n_directions) / pack.n_directions
    avg = 10 * np.log10(np.sum(w[:, None, None] * 10 ** (hs.logmag / 10), axis=0))
    band = (hs.freqs > 200) & (hs.freqs < 12000)
    assert np.max(np.abs(avg[:, band].mean(axis=0))) < 2.0


def test_resampling_to_44k_keeps_the_response(pack):
    a = HrtfSet(pack, 48000, 512, diffuse_eq=False).logmag_db(30, 10)[0]
    b = HrtfSet(pack, 44100, 512, diffuse_eq=False)
    fa = np.fft.rfftfreq(512, 1 / 48000)
    m = b.logmag_db(30, 10)[0]
    for ear in range(2):
        assert np.allclose(np.interp(b.freqs, fa, a[ear]), m[ear], atol=0.5)
