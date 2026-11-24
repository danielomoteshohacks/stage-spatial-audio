"""The guard's report: BS.1770 loudness, true peak, artifact detectors and the verdict."""

import json
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from stage.config import threshold_values
from stage.guard.artifacts import (
    detect_clipping,
    detect_dropouts,
    detect_musical_noise,
    detect_pre_echo,
)
from stage.guard.loudness import (
    K_HIGHPASS_48K,
    K_SHELF_48K,
    design_k_weighting,
    integrated_loudness,
    loudest_window,
    short_term_loudness,
    true_peak_dbtp,
)
from stage.guard.report import build_report, mono_gain_db

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas" / "report.schema.json").read_text())
FS = 44100
T = threshold_values()


def _music(seconds=6.0, fs=FS, seed=0):
    """Kick, bass, panned hats and a chord: enough structure for every detector."""
    rng = np.random.default_rng(seed)
    n = int(seconds * fs)
    t = np.arange(n) / fs
    kick = np.zeros(n)
    hats = np.zeros(n)
    for k in range(0, n, fs // 2):
        m = min(4000, n - k)
        kick[k : k + m] += np.sin(2 * np.pi * 55 * np.arange(m) / fs) * np.exp(-np.arange(m) / 800)
    for k in range(fs // 4, n, fs // 2):
        m = min(1500, n - k)
        hats[k : k + m] += rng.standard_normal(m) * np.exp(-np.arange(m) / 200) * 0.3
    chord = sum(np.sin(2 * np.pi * f * t) for f in (261.6, 329.6, 392.0)) * 0.1
    return 0.3 * np.stack([kick + 0.7 * hats + 0.8 * chord, kick + 0.3 * hats + 1.1 * chord])


def test_parametric_k_weighting_reproduces_the_standard_table_at_48k():
    shelf, hp = design_k_weighting(48000)
    assert np.allclose(shelf[0], K_SHELF_48K[0], atol=1e-8)
    assert np.allclose(shelf[1], K_SHELF_48K[1], atol=1e-8)
    assert np.allclose(hp[1], K_HIGHPASS_48K[1], atol=1e-8)


def test_full_scale_1k_sine_in_one_channel_reads_minus_3_lufs():
    # BS.1770-4: a 0 dBFS 997 Hz sine in one channel reads -3.01 LKFS.
    fs = 48000
    s = np.sin(2 * np.pi * 997 * np.arange(5 * fs) / fs)
    assert integrated_loudness(np.stack([s, 0 * s]), fs) == pytest.approx(-3.01, abs=0.01)


@pytest.mark.parametrize("fs", [44100, 48000, 96000])
def test_integrated_loudness_matches_pyloudnorm_within_0_1_lu(fs):
    pyln = pytest.importorskip("pyloudnorm")
    x = _music(8.0, fs)
    x[:, : fs] *= 0.001  # a near-silent second, so both gates do some work
    ours = integrated_loudness(x, fs)
    # Both implementations of the standard: De Man's filters (exact) and the RBJ default.
    for cls in ("DeMan", "K-weighting"):
        theirs = pyln.Meter(fs, filter_class=cls).integrated_loudness(x.T)
        assert abs(ours - theirs) < 0.1, (cls, ours, theirs)


def test_silence_has_no_loudness():
    assert integrated_loudness(np.zeros((2, FS)), FS) == float("-inf")


def test_true_peak_finds_the_inter_sample_peak():
    # A sine at fs/4 with a 45 degree phase: samples sit at 0.707 of the true peak (-3 dB).
    n = np.arange(4096)
    x = np.sin(2 * np.pi * n / 4 + np.pi / 4)[np.newaxis]
    assert 20 * np.log10(np.max(np.abs(x))) == pytest.approx(-3.01, abs=0.01)
    assert true_peak_dbtp(x, FS) == pytest.approx(0.0, abs=0.2)


def test_short_term_and_loudest_window():
    x = 0.01 * np.random.default_rng(1).standard_normal((2, 20 * FS))
    x[:, 12 * FS : 16 * FS] *= 20
    times, lufs = short_term_loudness(x, FS)
    assert times[np.argmax(lufs)] == pytest.approx(12.5, abs=0.6)
    steps = [float(np.mean(x[:, i : i + FS // 10] ** 2)) for i in range(0, x.shape[1], FS // 10)]
    start, _ = loudest_window(steps, 4.0)
    assert start == pytest.approx(12.0, abs=0.11)


def test_identity_passes_with_no_flags():
    x = _music()
    r = build_report(x, x.copy(), FS, {"engine": "test"})
    Draft202012Validator(SCHEMA).validate(r)
    assert r["verdict"] == "pass" and r["artifact_flags"] == []
    assert r["low_end_corr"] == pytest.approx(1.0)
    assert r["alignment_ms"] == 0.0


def test_mono_gain_of_identical_uncorrelated_and_opposite_channels():
    s = np.random.default_rng(2).standard_normal((2, FS))
    assert mono_gain_db(np.stack([s[0], s[0]])) == pytest.approx(0.0, abs=1e-9)
    assert mono_gain_db(s) == pytest.approx(-3.0, abs=0.2)
    assert mono_gain_db(np.stack([s[0], -s[0]])) == -120.0


def test_clipping_runs_are_flagged_with_their_time():
    x = _music()
    y = x.copy()
    y[0, FS * 2 : FS * 2 + 10] = 1.0
    flags = detect_clipping(y, FS, level=T["clip_level"], min_run=3)
    assert len(flags) == 1 and flags[0].start_s == pytest.approx(2.0, abs=1e-3)
    assert detect_clipping(x, FS, level=T["clip_level"], min_run=3) == []
    r = build_report(x, y, FS, {"engine": "test"})
    assert r["verdict"] == "fail" and any("clipped" in m for m in r["reasons"])


def test_a_band_hole_is_a_dropout():
    x = _music()
    spec = np.fft.rfft(x, axis=-1)
    f = np.fft.rfftfreq(x.shape[1], 1 / FS)
    held = spec.copy()
    held[:, (f > 230) & (f < 420)] = 0.0  # the chord's band, whole clip
    y = np.fft.irfft(held, n=x.shape[1], axis=-1)
    flags = detect_dropouts(x, y, FS, drop_db=T["dropout_drop_db"], min_ms=T["dropout_min_ms"],
                            floor_db=T["dropout_floor_db"])
    assert flags and flags[0].kind == "dropout" and "250 Hz" in flags[0].detail


def test_pre_echo_is_found_when_a_transient_is_smeared_backwards():
    x = _music()
    # Smear every sample over 15 ms centred on itself, as a long zero-phase filter or a long
    # STFT frame does: half of each transient's energy lands before it.
    k = int(0.015 * FS)
    y = np.stack([np.convolve(c, np.ones(k) / np.sqrt(k), mode="same") for c in x])
    flags = detect_pre_echo(x, y, FS, excess_db=T["pre_echo_excess_db"],
                            audible_db=T["pre_echo_audible_db"])
    assert len(flags) >= 5
    assert detect_pre_echo(x, x, FS, excess_db=T["pre_echo_excess_db"],
                           audible_db=T["pre_echo_audible_db"]) == []


def test_random_spectral_specks_are_musical_noise():
    x = _music()
    rng = np.random.default_rng(5)
    from stage.analysis.stft import istft, stft

    spec = stft(x, n_fft=1024, hop=256)
    # A noisy binary mask above 1 kHz, the classic cause of birdies.
    f = np.fft.rfftfreq(1024, 1 / FS)
    mask = np.ones(spec.shape[1:])
    hi = f > 1000
    mask[:, hi] = rng.random((spec.shape[1], hi.sum())) > 0.6
    y = istft(spec * mask, x.shape[1], n_fft=1024, hop=256)
    y += 0.02 * istft(stft(rng.standard_normal(x.shape), n_fft=1024, hop=256)
                      * (rng.random(spec.shape) > 0.97), x.shape[1], n_fft=1024, hop=256)
    flags = detect_musical_noise(x, y, FS, ratio=T["musical_noise_ratio"],
                                 min_per_s=T["musical_noise_min_per_s"])
    assert flags and flags[0].kind == "musical_noise"


def test_a_loud_and_bassless_render_fails_with_reasons():
    x = _music()
    spec = np.fft.rfft(x, axis=-1)
    f = np.fft.rfftfreq(x.shape[1], 1 / FS)
    spec[:, f < 120] *= 0.1
    y = 1.5 * np.fft.irfft(spec, n=x.shape[1], axis=-1)
    r = build_report(x, y, FS, {"engine": "test"})
    Draft202012Validator(SCHEMA).validate(r)
    assert r["verdict"] == "fail"
    text = " ".join(r["reasons"])
    assert "Loudness" in text and "bass" in text


def test_every_threshold_has_a_reason():
    raw = json.loads((ROOT / "configs" / "thresholds" / "guard.json").read_text())
    for key, entry in raw.items():
        if key.startswith("_"):
            continue
        assert set(entry) == {"value", "why"} and len(entry["why"]) > 30, key
