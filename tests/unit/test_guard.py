"""Fidelity guard checks on synthetic signals with known impairments."""

import numpy as np
import pytest
from scipy.signal import lfilter

from stage.guard import (
    check_alignment,
    check_loudness,
    check_low_end,
    check_timbre,
    format_report,
    guard_report,
    third_octave_bands,
)

FS = 44100
N = 6 * FS


def _pink(rng, n):
    """Pink noise (1/f power), 0.1 RMS. Pink puts equal power in every 1/3-octave band, so no
    band's estimate is starved, and a high-shelf cut barely moves the broadband level."""
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, d=1.0 / FS)
    spec[0] = 0.0
    spec[1:] /= np.sqrt(f[1:])
    x = np.fft.irfft(spec, n)
    return 0.1 * x / np.std(x)


@pytest.fixture(scope="module")
def stereo():
    """A centred source plus an uncorrelated part per channel: partly correlated, like a mix."""
    rng = np.random.default_rng(1)
    centre = _pink(rng, N)
    return np.stack([centre + 0.5 * _pink(rng, N), centre + 0.5 * _pink(rng, N)])


def _delay(x, d):
    """Delay by d samples (negative: advance), keeping the length."""
    if d >= 0:
        return np.pad(x, ((0, 0), (d, 0)))[:, : x.shape[1]]
    return np.pad(x, ((0, 0), (0, -d)))[:, -d:]


def _fft_shelf(x, corner_hz, gain_db):
    """Exact high shelf: every bin at or above the corner scaled by gain_db."""
    spec = np.fft.rfft(x, axis=-1)
    f = np.fft.rfftfreq(x.shape[-1], d=1.0 / FS)
    spec[..., f >= corner_hz] *= 10.0 ** (gain_db / 20.0)
    return np.fft.irfft(spec, n=x.shape[-1], axis=-1)


def _rbj_high_shelf(x, f0, gain_db, s=1.0):
    """Audio EQ Cookbook (R. Bristow-Johnson) high shelf: a real filter, with phase shift."""
    a_ = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * f0 / FS
    alpha = np.sin(w0) / 2.0 * np.sqrt((a_ + 1.0 / a_) * (1.0 / s - 1.0) + 2.0)
    cw, sa = np.cos(w0), 2.0 * np.sqrt(a_) * alpha
    b = [a_ * ((a_ + 1) + (a_ - 1) * cw + sa), -2 * a_ * ((a_ - 1) + (a_ + 1) * cw),
         a_ * ((a_ + 1) + (a_ - 1) * cw - sa)]
    a = [(a_ + 1) - (a_ - 1) * cw + sa, 2 * ((a_ - 1) - (a_ + 1) * cw),
         (a_ + 1) - (a_ - 1) * cw - sa]
    return lfilter(b, a, x, axis=-1)


# --- the four required cases --------------------------------------------------------------


def test_identical_signals_pass_everything(stereo):
    r = guard_report(stereo, stereo.copy(), FS)
    assert r.alignment.lag_samples == 0 and r.alignment.passed
    assert r.loudness.difference_db == 0.0 and r.loudness.passed
    assert max(abs(d) for d in r.loudness.window_difference_db) == 0.0
    assert r.timbre.max_deviation_db < 1e-9 and r.timbre.passed and not r.timbre.failing_bands
    assert r.low_end.difference_db == 0.0
    assert r.low_end.rendered_correlation == pytest.approx(r.low_end.original_correlation)
    assert r.passed


def test_6db_gain_fails_loudness_only(stereo):
    r = guard_report(stereo, stereo * 10.0 ** (6.0 / 20.0), FS)
    assert r.loudness.difference_db == pytest.approx(6.0, abs=1e-9)
    assert not r.loudness.passed
    # The checks are independent: a gain is not a delay and not a change of colour.
    assert r.alignment.passed and r.timbre.passed
    assert not r.passed


def test_5ms_delay_fails_alignment(stereo):
    d = round(0.005 * FS)  # 220 samples
    r = guard_report(stereo, _delay(stereo, d), FS)
    assert r.alignment.lag_samples == d
    assert r.alignment.lag_ms == pytest.approx(1e3 * d / FS)
    assert not r.alignment.passed
    assert r.loudness.passed and r.timbre.passed
    assert not r.passed


def test_render_that_is_early_gives_a_negative_lag(stereo):
    r = check_alignment(stereo, _delay(stereo, -220), FS)
    assert r.lag_samples == -220 and not r.passed


def test_inverted_render_is_found_at_its_lag_with_negative_correlation(stereo):
    r = check_alignment(stereo, -_delay(stereo, 100), FS)
    assert r.lag_samples == 100
    assert r.peak_correlation == pytest.approx(-1.0, abs=0.01)


def test_delay_below_1ms_passes(stereo):
    d = round(0.0009 * FS)  # 39 samples, 0.88 ms
    r = check_alignment(stereo, _delay(stereo, d), FS)
    assert r.lag_samples == d and r.passed


def test_3db_high_shelf_fails_timbre_and_names_the_bands(stereo):
    # Corner at the lower edge of the 5 kHz band, so exactly the top six bands are cut.
    centres, lo, _ = third_octave_bands()
    corner = lo[np.argmin(np.abs(centres - 5000.0))]
    r = check_timbre(stereo, _fft_shelf(stereo, corner, -3.0), FS)
    assert not r.passed
    assert r.failing_bands == ("5k", "6.3k", "8k", "10k", "12.5k", "16k")
    # The cut bands read -3 dB plus the small broadband offset that RMS matching removes.
    cut = np.array(r.band_difference_db[-6:])
    assert np.allclose(cut, -3.0 - r.level_offset_db, atol=0.05)
    assert r.max_deviation_db > 2.5  # -3 dB less an RMS-matching offset of about 0.3 dB


def test_3db_biquad_high_shelf_fails_only_the_top_bands(stereo):
    """A real shelf filter: a gradual transition and phase shift instead of a brick wall."""
    r = guard_report(stereo, _rbj_high_shelf(stereo, 6000.0, -3.0), FS)
    assert not r.timbre.passed
    assert r.alignment.passed  # the shelf's phase shift is far below 1 ms
    labels = list(r.timbre.band_labels)
    failing = [labels.index(b) for b in r.timbre.failing_bands]
    assert failing == list(range(failing[0], len(labels)))  # contiguous, up to 16 kHz
    assert labels[failing[0]] in {"6.3k", "8k", "10k"}


def test_shelf_below_threshold_passes(stereo):
    centres, lo, _ = third_octave_bands()
    corner = lo[np.argmin(np.abs(centres - 5000.0))]
    assert check_timbre(stereo, _fft_shelf(stereo, corner, -1.0), FS).passed


# --- details of each check ----------------------------------------------------------------


def test_third_octave_bands_are_the_26_from_50hz_to_16khz():
    centres, lo, hi = third_octave_bands()
    assert centres.size == 26
    assert centres[0] == pytest.approx(50.12, abs=0.01)
    assert centres[-1] == pytest.approx(15849, abs=1)
    assert np.allclose(hi[:-1], lo[1:])  # contiguous, no gaps or overlaps


def test_loudness_windows_cover_the_whole_clip():
    rng = np.random.default_rng(3)
    x = np.stack([_pink(rng, 7 * FS), _pink(rng, 7 * FS)])  # 3 + 3 + a 1 s remainder
    y = x.copy()
    y[:, 6 * FS :] *= 2.0  # louder only in the last second
    r = check_loudness(x, y, FS)
    assert r.window_starts_s == (0.0, 3.0, 6.0)
    assert r.window_difference_db[:2] == (0.0, 0.0)
    assert r.window_difference_db[2] == pytest.approx(6.02, abs=0.01)
    assert r.max_window_difference_db == pytest.approx(6.02, abs=0.01)


def test_loudness_threshold_is_inclusive_at_half_a_db(stereo):
    assert check_loudness(stereo, stereo * 10.0 ** (0.49 / 20.0), FS).passed
    assert not check_loudness(stereo, stereo * 10.0 ** (0.51 / 20.0), FS).passed


def test_low_end_sees_a_bass_cut_and_decorrelation():
    rng = np.random.default_rng(2)
    mono = _pink(rng, N)
    x = np.stack([mono, mono])  # fully correlated bass
    lo = _fft_shelf(x, 120.0, -np.inf)  # everything above 120 Hz removed: the bass part
    r_same = check_low_end(x, x, FS)
    assert r_same.rendered_correlation == pytest.approx(1.0)
    # Halve the bass of the right ear and flip its sign: -6 dB in that ear, correlation -1.
    y = x.copy()
    y[1] -= 1.5 * lo[1]
    r = check_low_end(x, y, FS)
    assert r.rendered_correlation == pytest.approx(-1.0, abs=1e-9)
    assert r.original_correlation == pytest.approx(1.0)
    assert r.difference_db == pytest.approx(10 * np.log10((1 + 0.25) / 2), abs=1e-6)
    assert r.passed is None  # reported, not gated


def test_report_table_lists_checks_and_failing_bands(stereo):
    centres, lo, _ = third_octave_bands()
    corner = lo[np.argmin(np.abs(centres - 5000.0))]
    text = format_report(guard_report(stereo, _fft_shelf(stereo, corner, -3.0), FS))
    for word in ("alignment", "loudness", "timbre", "low end", "not gated"):
        assert word in text
    assert "timbre failing bands (Hz): 5k" in text
    assert text.splitlines()[-1] == "overall: FAIL"


@pytest.mark.parametrize("bad", [np.zeros((1, 100)), np.zeros((2, 99)), np.zeros(100)])
def test_shape_mismatch_is_an_error(bad):
    with pytest.raises(ValueError):
        guard_report(np.zeros((2, 100)), bad, FS)


def test_silent_pair_does_not_produce_nan():
    z = np.zeros((2, FS))
    r = guard_report(z, z, FS)
    assert r.loudness.difference_db == 0.0
    assert all(d == 0.0 for d in r.timbre.band_difference_db)
    assert r.passed
