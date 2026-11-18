import numpy as np
import pytest

from stage.render import ear_delays_s, head_shadow, sector_filters

FS = 44100


def _itd_ms(az):
    left, right = ear_delays_s(az)
    return float(left + right) * 1e3  # one of them is always 0


@pytest.mark.parametrize(
    ("az", "expected_ms"), [(90.0, 0.656), (30.0, 0.261), (150.0, 0.261), (0.0, 0.0)]
)
def test_itd_reference_values(az, expected_ms):
    assert abs(_itd_ms(az) - expected_ms) < 0.01


def test_far_ear_is_delayed_near_ear_is_zero():
    left, right = ear_delays_s(60.0)  # source on the right: left ear is far
    assert float(right) == 0.0 and float(left) > 0.0
    left, right = ear_delays_s(-60.0)
    assert float(left) == 0.0 and float(right) > 0.0
    left, right = ear_delays_s(150.0)  # rear right is still the right side
    assert float(right) == 0.0 and float(left) > 0.0


def test_delays_are_non_negative_and_vectorised():
    az = np.linspace(-180.0, 180.0, 361)
    left, right = ear_delays_s(az)
    assert left.shape == right.shape == az.shape
    assert np.all(left >= 0.0) and np.all(right >= 0.0)
    assert np.all(np.minimum(left, right) == 0.0)


@pytest.mark.parametrize(
    ("theta", "f", "expected_db"),
    [(0.0, 8000.0, 5.94), (180.0, 8000.0, -9.95), (0.0, 1000.0, 3.37), (180.0, 1000.0, -1.94)],
)
def test_head_shadow_reference_magnitudes(theta, f, expected_db):
    db = 20.0 * np.log10(np.abs(head_shadow(theta, f)))
    assert abs(float(db) - expected_db) < 0.05


def test_head_shadow_is_unity_at_dc():
    assert np.allclose(head_shadow(np.array([0.0, 90.0, 180.0]), 0.0), 1.0)


def test_sector_filters_shape_dtype_and_finite():
    h = sector_filters([-30.0, 0.0, 30.0], n_fft=2048, sample_rate=FS)
    assert h.shape == (3, 2, 1025)
    assert h.dtype == np.complex128
    assert np.all(np.isfinite(h))
    for k in (0, -1):  # DC and Nyquist
        assert not np.any(np.isnan(h[:, :, k]))


def test_sector_filters_respects_n_fft():
    assert sector_filters([10.0], n_fft=512).shape == (1, 2, 257)


@pytest.mark.parametrize("az", [10.0, 45.0, 90.0, 150.0])
def test_mirror_symmetry_swaps_ears(az):
    h = sector_filters([az, -az])
    assert np.allclose(h[0, 0], h[1, 1], atol=1e-12)
    assert np.allclose(h[0, 1], h[1, 0], atol=1e-12)


def test_centre_magnitude_equal_for_both_ears():
    h = sector_filters([0.0])
    assert np.allclose(np.abs(h[0, 0]), np.abs(h[0, 1]), atol=1e-12)


def test_inter_ear_lag_at_90_degrees_is_about_29_samples():
    n_fft = 2048
    h = sector_filters([90.0], n_fft=n_fft, sample_rate=FS)
    ir_left = np.fft.irfft(h[0, 0], n=n_fft)
    ir_right = np.fft.irfft(h[0, 1], n=n_fft)
    # Magnitude-only shadow is zero phase, so each response peaks at its own delay.
    lag = int(np.argmax(ir_left)) - int(np.argmax(ir_right))
    assert abs(lag - 29) <= 1


def test_far_ear_is_quieter_at_high_frequency():
    h = sector_filters([90.0])
    f = np.fft.rfftfreq(2048, 1 / FS)
    k = int(np.argmin(np.abs(f - 8000.0)))
    near, far = np.abs(h[0, 1, k]), np.abs(h[0, 0, k])
    assert 20 * np.log10(near) > 0 > 20 * np.log10(far)
