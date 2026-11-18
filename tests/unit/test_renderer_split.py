"""Measures the two ways of turning power weights into amplitude gains: w and sqrt(w).

The sector weights sum to 1 in power. sqrt(w) keeps the per-sector powers summing to the primary's
power, which is the obvious reading of that. But the sectors are copies of one signal, so at the
ear they add as amplitudes, and then it is the weights themselves that sum to 1. The tests below
record both measurements; the renderer uses whichever the numbers support.
"""

import numpy as np
import pytest

from stage.render import sector_azimuths, sector_filters, sector_weights, widen_azimuth
from stage.render.renderer import _DEFAULT_SPLIT, _split_gains

N = 200_000
FS = 44100
N_FFT = 2048


@pytest.fixture(scope="module")
def spectra():
    rng = np.random.default_rng(0)
    p = rng.standard_normal(N) + 1j * rng.standard_normal(N)
    angle = rng.uniform(-30.0, 30.0, N)
    bins = rng.integers(0, N_FFT // 2 + 1, N)
    return p, angle, bins


def _db(ratio):
    return 10.0 * np.log10(ratio)


def _measure(mode, spectra):
    """Power ratios (output / primary) at three points in the signal path."""
    p, angle, bins = spectra
    gains = _split_gains(sector_weights(angle), mode)  # (13, N)
    total = np.sum(np.abs(p) ** 2)

    before_filtering = np.sum(np.abs(gains * p) ** 2) / total  # sectors as separate signals
    summed_in_amplitude = np.sum(np.abs(gains.sum(axis=0) * p) ** 2) / total  # as they reach an ear
    filters = sector_filters(sector_azimuths(2.0), n_fft=N_FFT, sample_rate=FS)[:, :, bins]
    ears = np.einsum("sn,sen->en", gains, filters) * p
    through_head = np.sum(np.abs(ears) ** 2) / total
    return before_filtering, summed_in_amplitude, through_head


def _ideal_head_power(spectra, n=2000):
    """Reference: each bin through one filter at its exact widened azimuth, no sectors."""
    p, angle, bins = spectra
    az = widen_azimuth(angle[:n], 2.0)
    h = np.stack([sector_filters(a, n_fft=N_FFT, sample_rate=FS)[0] for a in az])
    ears = h[np.arange(n), :, bins[:n]] * p[:n, None]
    return np.sum(np.abs(ears) ** 2) / np.sum(np.abs(p[:n]) ** 2)


def test_sqrt_conserves_power_only_when_sectors_are_incoherent(spectra):
    before, summed, head = _measure("sqrt", spectra)
    print(f"sqrt(w): before {_db(before):+.2f} dB, summed {_db(summed):+.2f} dB, "
          f"head {_db(head):+.2f} dB")
    assert abs(_db(before)) < 1e-9  # exact: the sum of w is 1
    assert _db(summed) > 3.0  # but the sectors do not add in power


def test_linear_conserves_amplitude_sum_but_not_incoherent_power(spectra):
    before, summed, head = _measure("linear", spectra)
    print(f"w:       before {_db(before):+.2f} dB, summed {_db(summed):+.2f} dB, "
          f"head {_db(head):+.2f} dB")
    assert abs(_db(summed)) < 1e-9  # exact: the sum of w is 1
    assert _db(before) < -2.0  # the pre-filter figure the sqrt split is built to fix


def test_default_split_is_the_one_closest_to_the_ideal_head_power(spectra):
    ideal = _ideal_head_power(spectra)
    error = {m: abs(_db(_measure(m, spectra)[2]) - _db(ideal)) for m in ("sqrt", "linear")}
    print(f"ideal {_db(ideal):+.2f} dB, error vs ideal: {error}")
    assert error["linear"] < 0.5
    assert error["sqrt"] > 3.0
    assert min(error, key=error.get) == _DEFAULT_SPLIT


def test_unknown_split_is_rejected():
    with pytest.raises(ValueError):
        _split_gains(np.ones(3), "cube")  # type: ignore[arg-type]
