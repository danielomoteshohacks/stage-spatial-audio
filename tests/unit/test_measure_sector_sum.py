"""The sector-sum measurement describes the real renderer, and the dips it finds are the comb
predicted by the sector delays. These test the measuring tool, not a target for the renderer:
nothing here pins today's dip depths, so a renderer fix would not make them fail."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from stage.render import ear_delays_s, sector_azimuths

_path = Path(__file__).resolve().parents[2] / "scripts" / "measure_sector_sum.py"
_spec = importlib.util.spec_from_file_location("measure_sector_sum", _path)
mss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mss)

BETA = 2.0


@pytest.mark.parametrize("theta", [2.5, 12.5, 27.5])
def test_computed_response_matches_a_real_render(theta):
    f = mss.freqs_hz()
    sel = (f >= 100.0) & (f <= 16000.0)
    measured = mss._db(mss.measured_response(theta, BETA))[:, sel]
    computed = mss._db(mss.sector_sum_response(theta, BETA) * mss._EAR_NORM)[:, sel]
    assert np.max(np.abs(measured - computed)) < 0.1


@pytest.mark.parametrize("theta", [0.0, 2.5, 13.0, 27.5])
def test_mirror_position_swaps_the_ears(theta):
    right = mss.sector_sum_response(theta, BETA)
    left = mss.sector_sum_response(-theta, BETA)
    assert np.allclose(left, right[::-1], atol=1e-12)


def test_unity_gain_at_low_frequency():
    # Below the head shadow and with delays far shorter than a period, the copies add in phase,
    # and the weights sum to 1.
    f = mss.freqs_hz()
    k = int(np.argmin(np.abs(f - 100.0)))
    for theta in mss.POSITIONS_DEG:
        assert np.all(np.abs(mss._db(mss.sector_sum_response(theta, BETA)[:, k])) < 0.1)


def test_far_ear_notch_is_at_half_the_inverse_delay_difference():
    """Midway between sectors 0 and +5 deg the two copies have equal weight, so the far (left)
    ear must notch where their delays differ by half a period: f = 1 / (2 * delta_tau)."""
    az = sector_azimuths(BETA)
    left_delay, _ = ear_delays_s(az[6:8])  # sectors at 0 and +5 deg
    expected = 1.0 / (2.0 * (left_delay[1] - left_delay[0]))
    dip, freq, ear = mss.worst_dip(2.5, BETA, band=(1000.0, 10000.0))
    assert ear == 0
    assert abs(freq - expected) < 2 * mss.freqs_hz()[1]  # within two bins
    assert dip < -6.0  # a real notch, not ripple


def test_near_ear_has_no_comb_once_every_weighty_sector_is_on_its_side():
    # Near-ear delays are zero for every sector on the source's side, so the copies stay in
    # phase there and only their magnitudes blend.
    for theta in (12.5, 17.5, 22.5, 27.5):
        f = mss.freqs_hz()
        sel = (f >= 100.0) & (f <= 20000.0)
        ratio = mss.sector_sum_response(theta, BETA) / mss.reference_response(theta, BETA)
        assert np.min(mss._db(ratio[1, sel])) > -0.5


def test_band_dips_have_one_value_per_band():
    ear, both = mss.band_dips(2.5, BETA)
    assert ear.shape == (2, mss.BANDS[0].size) and both.shape == (mss.BANDS[0].size,)
    # Power summed over the ears can never dip further than the worse ear alone.
    assert np.all(both >= ear.min(axis=0) - 1e-9)


def test_near_field_profile_is_refused():
    from dataclasses import replace

    from stage.render.profiles import V0

    with pytest.raises(ValueError):
        mss.reference_response(10.0, BETA, replace(V0, name="nf", nearfield=True))
