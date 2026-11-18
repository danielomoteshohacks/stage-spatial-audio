import numpy as np
import pytest

from stage.analysis import angle_to_position
from stage.render import ear_delays_s, render_stereo, sector_filters, widen_azimuth

FS = 44100
RNG_SEED = 12345


def _white(n, seed=RNG_SEED):
    return np.random.default_rng(seed).standard_normal(n)


def _pink(n, seed=RNG_SEED):
    """1/f power noise from shaped white noise, unit variance."""
    spec = np.fft.rfft(_white(n, seed))
    f = np.fft.rfftfreq(n)
    f[0] = f[1]
    x = np.fft.irfft(spec / np.sqrt(f), n=n)
    return x / x.std()


def _panned(mono, angle_deg):
    """Stereo pair that the tangent law places at `angle_deg`, constant power."""
    pos = float(angle_to_position(angle_deg))
    ratio = (1.0 + pos) / (1.0 - pos)  # gR / gL
    g_l = 1.0 / np.sqrt(1.0 + ratio**2)
    return np.stack([g_l * mono, g_l * ratio * mono])


def _power(x):
    return float(np.sum(x**2))


def _level_diff_db(out):
    """Right minus left level in dB."""
    return 10.0 * np.log10(_power(out[1]) / _power(out[0]))


def _lag_samples(left, right):
    """Samples by which `left` lags `right`, from the cross-correlation peak (sub-sample)."""
    n = left.size
    spec = np.fft.rfft(left, 2 * n) * np.conj(np.fft.rfft(right, 2 * n))
    xc = np.fft.fftshift(np.fft.irfft(spec))
    centre = n
    window = slice(centre - 60, centre + 61)
    k = int(np.argmax(xc[window])) + centre - 60
    y0, y1, y2 = xc[k - 1], xc[k], xc[k + 1]
    return (k - centre) + 0.5 * (y0 - y2) / (y0 - 2.0 * y1 + y2)


def test_centred_mono_source_has_equal_ears():
    out = render_stereo(np.stack([_pink(4 * FS)] * 2), FS)
    assert abs(_level_diff_db(out)) < 1e-6
    # Mirror symmetry must hold sample by sample, not just in total level.
    assert np.max(np.abs(out[0] - out[1])) < 1e-9 * np.max(np.abs(out))


def test_hard_right_source_is_louder_right_and_leads_by_woodworth_delay():
    beta = 2.0
    out = render_stereo(np.stack([np.zeros(3 * FS), _white(3 * FS)]), FS, beta=beta)
    assert _level_diff_db(out) > 3.0

    # Hard right is 30 degrees on the stereo scale; it is rendered at its widened azimuth.
    expected = float(ear_delays_s(widen_azimuth(30.0, beta))[0]) * FS
    lag = _lag_samples(out[0], out[1])  # positive: the left (far) ear is late
    assert lag > 0.0
    # Measured 0.1 samples off at beta 1.0, 2.0 and 2.4; 0.5 leaves room for platform rounding.
    assert abs(lag - expected) < 0.5, (lag, expected)


def test_widening_pushes_a_source_outward():
    mono = _white(3 * FS)
    stereo = _panned(mono, 15.0)
    ild = {b: _level_diff_db(render_stereo(stereo, FS, beta=b)) for b in (1.0, 2.0, 2.4)}
    assert ild[1.0] < ild[2.0] < ild[2.4]

    # Reference: the same noise placed at the un-widened 15 degrees by the same head model.
    h = sector_filters([15.0], n_fft=2048, sample_rate=FS)[0]
    ref = 10.0 * np.log10(np.mean(np.abs(h[1]) ** 2) / np.mean(np.abs(h[0]) ** 2))
    assert ild[2.0] > ref + 1.0, (ild, ref)


@pytest.mark.parametrize("kind", ["uncorrelated", "centred", "panned", "mixed"])
def test_total_power_is_within_1p5_db_on_pink_noise(kind):
    n = 4 * FS
    a, b = _pink(n, 1), _pink(n, 2)
    stereo = {
        "uncorrelated": np.stack([a, b]),
        "centred": np.stack([a, a]),
        "panned": _panned(a, 15.0),
        "mixed": np.stack([0.7 * a + 0.3 * b, 0.7 * a - 0.3 * b]),
    }[kind]
    out = render_stereo(stereo, FS)
    change_db = 10.0 * np.log10(_power(out) / _power(stereo))
    assert abs(change_db) < 1.5, change_db


def test_length_finite_and_deterministic():
    stereo = np.stack([_pink(2 * FS + 37, 1), _pink(2 * FS + 37, 2)])
    first = render_stereo(stereo, FS)
    second = render_stereo(stereo, FS)
    assert first.shape == stereo.shape
    assert first.dtype == np.float64
    assert np.all(np.isfinite(first))
    assert np.array_equal(first, second)


@pytest.mark.parametrize("block_frames", [1, 7, 256])
def test_block_size_does_not_change_the_output(block_frames):
    stereo = np.stack([_pink(3 * FS, 1), _pink(3 * FS, 2)])
    stereo[0] += 0.5 * _pink(3 * FS, 3)  # some correlated content as well
    whole = render_stereo(stereo, FS, block_frames=10**9)
    blocked = render_stereo(stereo, FS, block_frames=block_frames)
    assert np.max(np.abs(whole - blocked)) < 1e-9


def test_silence_stays_silent_and_short_input_works():
    assert np.all(render_stereo(np.zeros((2, FS)), FS) == 0.0)
    out = render_stereo(np.stack([_white(100), _white(100, 7)]), FS)
    assert out.shape == (2, 100) and np.all(np.isfinite(out))


def test_rejects_bad_input():
    with pytest.raises(ValueError):
        render_stereo(np.zeros((1, 1000)), FS)
    with pytest.raises(ValueError):
        render_stereo(np.zeros((2, 1000)), FS, beta=3.0)
    with pytest.raises(ValueError):
        render_stereo(np.zeros((2, 1000)), FS, block_frames=0)
