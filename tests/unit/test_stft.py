import numpy as np
import pytest

from stage.analysis import istft, sqrt_hann, stft


def test_window_squared_sums_to_one_at_half_overlap():
    n = 2048
    w2 = sqrt_hann(n) ** 2
    assert np.allclose(w2 + np.roll(w2, n // 2), 1.0)


@pytest.mark.parametrize("n_samples", [1, 100, 1024, 2047, 2048, 5000, 44100])
@pytest.mark.parametrize("hop", [1024, 512])
def test_perfect_reconstruction(n_samples, hop):
    rng = np.random.default_rng(n_samples + hop)
    x = rng.standard_normal((2, n_samples))
    spec = stft(x, n_fft=2048, hop=hop)
    y = istft(spec, n_samples, n_fft=2048, hop=hop)
    assert y.shape == x.shape
    assert np.max(np.abs(y - x)) < 1e-12


def test_shapes():
    x = np.zeros((2, 10000))
    spec = stft(x, n_fft=2048, hop=1024)
    assert spec.shape[0] == 2
    assert spec.shape[2] == 1025


def test_sine_energy_lands_in_the_right_bin():
    sr, n_fft = 44100, 2048
    freq = 20 * sr / n_fft  # exactly on bin 20
    t = np.arange(sr) / sr
    x = np.sin(2 * np.pi * freq * t)[None, :]
    spec = stft(x, n_fft=n_fft, hop=1024)
    middle = np.abs(spec[0, spec.shape[1] // 2])
    assert int(np.argmax(middle)) == 20


def test_rejects_wrong_shape_and_hop():
    with pytest.raises(ValueError):
        stft(np.zeros(100))
    with pytest.raises(ValueError):
        stft(np.zeros((1, 100)), n_fft=256, hop=512)
