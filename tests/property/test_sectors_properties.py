"""
Property-based and invariant tests for spatial sectors.
"""

import numpy as np

from stage.render.sectors import (
    apply_sectors,
    sector_azimuths,
    sector_weights,
)


def test_weights_sum_to_one() -> None:
    """
    Test that weights always sum to exactly 1 for a partition of unity.
    Includes exactly -30, 0, +30 and random out-of-bounds angles.
    """
    rng = np.random.default_rng(seed=42)
    # Target values well outside [-30, 30] to verify clipping behaviour
    angles = rng.uniform(-60.0, 60.0, size=(10, 10))
    
    # Inject edge cases explicitly
    angles[0, 0] = -30.0
    angles[0, 1] = 0.0
    angles[0, 2] = 30.0

    weights = sector_weights(angles)

    # Spatial probabilities must be positive
    assert np.all(weights >= 0.0)

    # Weights must resolve to exactly 1 to prevent volume swells
    weight_sum = np.sum(weights, axis=0)
    assert np.allclose(weight_sum, 1.0, atol=1e-12)


def test_widen_azimuth_increasing_grid() -> None:
    """
    Test that widened azimuths are strictly increasing over the 13 sectors
    for every beta in a grid from 1.0 to 2.4, and remain bounded below 80.
    """
    betas = np.linspace(1.0, 2.4, num=15)

    for beta in betas:
        azimuths = sector_azimuths(beta)

        # Monotonicity preserves relative spatial placement
        diffs = np.diff(azimuths)
        assert np.all(diffs > 0.0)

        # Output cannot exceed maximum physical bounds
        assert np.max(np.abs(azimuths)) < 80.0


def test_apply_sectors_conserves_power() -> None:
    """
    Test that spreading power across sectors and summing them up
    returns the exact original power array.
    """
    rng = np.random.default_rng(seed=42)
    power = rng.uniform(0.0, 10.0, size=(16, 256)).astype(np.float64)
    angles = rng.uniform(-30.0, 30.0, size=(16, 256)).astype(np.float64)

    weights = sector_weights(angles)
    sectored_power = apply_sectors(power, weights)

    reconstructed_power = np.sum(sectored_power, axis=0)
    assert np.allclose(reconstructed_power, power, atol=1e-12)