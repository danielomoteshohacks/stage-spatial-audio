"""
Unit tests for spatial sector rendering components.
"""

import numpy as np
import pytest

from stage.render.sectors import (
    sector_weights,
    widen_azimuth,
)


def test_widen_azimuth_specific_values() -> None:
    """
    Test the widening function against known expected values at beta 2.4.
    """
    beta = 2.4
    assert np.isclose(widen_azimuth(30.0, beta), 57.3, atol=0.05)
    assert np.isclose(widen_azimuth(15.0, beta), 33.75, atol=0.05)
    assert np.isclose(widen_azimuth(5.0, beta), 11.9, atol=0.05)


def test_widen_azimuth_odd_symmetry() -> None:
    """
    Test that widening produces odd symmetry f(-x) = -f(x).
    """
    beta = 2.0
    pos = widen_azimuth(20.0, beta)
    neg = widen_azimuth(-20.0, beta)
    assert np.isclose(pos, -neg, atol=1e-12)


def test_widen_azimuth_invalid_beta() -> None:
    """
    Test that beta outside [1.0, 2.4] raises ValueError.
    """
    with pytest.raises(ValueError):
        widen_azimuth(30.0, 0.9)

    with pytest.raises(ValueError):
        widen_azimuth(30.0, 2.5)


def test_sector_weights_centres() -> None:
    """
    Test that an angle directly on a sector centre yields the maximum weight for that sector.
    """
    # Test lower bound centre (-30.0, index 0)
    weights = sector_weights(np.array([[-30.0]]))
    assert np.argmax(weights[:, 0, 0]) == 0

    # Test middle centre (0.0, index 6)
    weights = sector_weights(np.array([[0.0]]))
    assert np.argmax(weights[:, 0, 0]) == 6