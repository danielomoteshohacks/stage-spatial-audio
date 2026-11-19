"""A rotatable soundfield: ear filters tabulated on an azimuth grid (hypothesis H17, decision 0008).

The sectors already sit at fixed directions around the listener, so turning the head by `yaw`
only changes which table entry each sector reads: an index offset plus one interpolation weight
per sector. The per-bin work does not change at all, which is why head tracking is nearly free.

Each entry is stored as a delay per ear plus the residual response with that delay removed.
Interpolating the delay and the residual separately avoids the comb filtering that interpolating
two complex responses with different delays causes (noted in decision 0006).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

from stage.render.headmodel import ear_delays_s
from stage.render.pinna import ear_filters


class AzimuthFilterBank:
    """Ear filters on a uniform grid of `n_steps` azimuths covering the full circle."""

    def __init__(
        self,
        step_deg: float = 1.0,
        *,
        n_fft: int = 2048,
        sample_rate: int = 44100,
        pinna: bool = False,
        steering_db: float = 0.0,
    ) -> None:
        n = round(360.0 / step_deg)
        if not np.isclose(n * step_deg, 360.0):
            raise ValueError(f"step_deg must divide 360, got {step_deg}")
        self.step_deg = 360.0 / n
        self.grid_deg = np.arange(n) * self.step_deg
        self.freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
        h = ear_filters(
            self.grid_deg, n_fft=n_fft, sample_rate=sample_rate, pinna=pinna,
            steering_db=steering_db,
        )
        left, right = ear_delays_s(self.grid_deg)
        self.delay_s = np.stack([left, right], axis=1)  # (n, 2)
        self.residual = h * np.exp(2j * np.pi * self.freqs * self.delay_s[..., np.newaxis])

    def indices(self, az_deg: ArrayLike) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
        """Lower grid index and interpolation weight toward the next index, per azimuth."""
        pos = np.mod(np.asarray(az_deg, dtype=np.float64), 360.0) / self.step_deg
        lo = np.floor(pos).astype(np.int64) % self.grid_deg.size
        return lo, pos - np.floor(pos)

    def lookup(self, az_deg: ArrayLike, yaw_deg: float = 0.0) -> NDArray[np.complex128]:
        """Filters (n_az, 2, bins) for sources at world azimuth `az_deg` with the head at `yaw`."""
        lo, frac = self.indices(np.atleast_1d(np.asarray(az_deg, dtype=np.float64)) - yaw_deg)
        hi = (lo + 1) % self.grid_deg.size
        w = frac[:, np.newaxis]
        delay = (1.0 - w) * self.delay_s[lo] + w * self.delay_s[hi]
        wr = w[..., np.newaxis]
        res = (1.0 - wr) * self.residual[lo] + wr * self.residual[hi]
        return res * np.exp(-2j * np.pi * self.freqs * delay[..., np.newaxis])
