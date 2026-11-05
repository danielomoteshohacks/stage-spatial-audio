"""
Spatial rendering sector definition and mapping.
"""

import numpy as np

# 13 sectors from -30 to +30 degrees in 5-degree increments
SECTOR_CENTRES_DEG = np.array(
    [-30.0, -25.0, -20.0, -15.0, -10.0, -5.0, 0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0],
    dtype=np.float64,
)


def sector_weights(angle_deg: np.ndarray, sigma_deg: float = 2.5) -> np.ndarray:
    """
    Calculate normalised Gaussian weights for each sector given per-bin angles.
    """
    angles = np.clip(np.asarray(angle_deg), -30.0, 30.0).astype(np.float64)

    # Reshape centres to broadcast against (..., frames, bins) input shapes
    centres = SECTOR_CENTRES_DEG.reshape((13,) + (1,) * angles.ndim)

    diff = angles - centres
    weights = np.exp(-(diff * diff) / (2.0 * sigma_deg * sigma_deg), dtype=np.float64)

    # Partition of unity guarantees spatial spread conserves original total energy
    weight_sum = np.sum(weights, axis=0, keepdims=True)

    # Failsafe for degenerate inputs to maintain determinism across all platforms
    weight_sum[weight_sum == 0.0] = 1.0

    return weights / weight_sum


def widen_azimuth(
    theta_deg: np.ndarray | float, beta: float, a_max_deg: float = 80.0
) -> np.ndarray:
    """
    Apply an order-preserving non-linear widening warp to an angle.
    """
    if not (1.0 <= beta <= 2.4):
        raise ValueError(f"beta must be between 1.0 and 2.4, got {beta}")

    theta = np.asarray(theta_deg, dtype=np.float64)
    return a_max_deg * np.tanh((beta * theta) / a_max_deg)


def sector_azimuths(beta: float) -> np.ndarray:
    """
    Calculate the widened azimuth for each of the 13 sector centres.
    """
    return widen_azimuth(SECTOR_CENTRES_DEG, beta)


def apply_sectors(power: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """
    Distribute bin power across sectors according to their spatial weights.
    """
    # NumPy broadcasting aligns trailing (frames, bins) dimensions implicitly
    return power.astype(np.float64) * weights.astype(np.float64)