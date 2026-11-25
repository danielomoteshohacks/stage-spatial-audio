import numpy as np
import pytest

from stage.stream import codec


def music_like(seconds=6.0, sr=44100, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr)) / sr
    tones = ((110, 0.3), (220, 0.2), (440, 0.15), (1760, 0.05))
    x = sum(np.sin(2 * np.pi * f * t) * a for f, a in tones)
    x = x * (1 + 0.3 * np.sin(2 * np.pi * 2 * t)) + 0.01 * rng.standard_normal(t.size)
    return np.stack([x, 0.8 * x + 0.02 * rng.standard_normal(t.size)]).astype(np.float32) * 0.6


def resample_to_48k(x, sr):
    from math import gcd

    from scipy.signal import resample_poly
    g = gcd(48000, sr)
    return resample_poly(x, 48000 // g, sr // g, axis=1)


def test_flac_roundtrip_is_lossless_to_24_bits():
    x = music_like(2.0)
    e = codec.encode_segment(x, 44100, "flac")
    y, sr = codec.decode(e.data)
    assert sr == 44100 and y.shape == x.shape
    assert np.abs(y - x).max() < 2e-7


def test_opus_is_small_and_close_to_the_source():
    x = music_like(6.0)
    e = codec.encode_segment(x, 44100, "opus")
    kbps = len(e.data) * 8 / 6.0 / 1000
    assert e.fmt == "opus" and e.sample_rate == 48000 and kbps < 230
    y, sr = codec.decode(e.data)
    ref = resample_to_48k(x, 44100)
    m = min(ref.shape[1], y.shape[1])
    # Opus has an algorithmic delay; the decoder trims it, so the signals line up closely.
    lag = np.argmax(np.correlate(ref[0, 4800:9600], y[0, 4800:9600], "full")) - 4799
    assert abs(lag) <= 2
    err = ref[:, 2000:m - 2000] - y[:, 2000:m - 2000]
    snr = 10 * np.log10(np.sum(ref[:, 2000:m - 2000] ** 2) / np.sum(err**2))
    assert snr > 14.0  # a perceptual codec is not waveform-exact: a floor, not a quality claim


def test_two_independently_encoded_segments_meet_without_a_click():
    sr = 44100
    x = music_like(8.0, sr)
    cut = 4 * sr
    pad = int(codec.PAD_S * sr)
    a = codec.encode_segment(x[:, : cut + pad], sr, "opus", pre=0, post=pad)
    b = codec.encode_segment(x[:, cut - pad :], sr, "opus", pre=pad, post=0)
    ya, _ = codec.decode(a.data)
    yb, _ = codec.decode(b.data)
    ya = ya[:, : ya.shape[1] - a.post]
    yb = yb[:, b.pre :]
    joined = np.concatenate([ya, yb], axis=1)
    ref = resample_to_48k(x, sr)
    k = ya.shape[1]
    # The step across the joint is no larger than the signal's own steepest step plus codec noise.
    step_at_joint = np.abs(joined[:, k] - joined[:, k - 1]).max()
    typical = np.abs(np.diff(ref, axis=1)).max()
    assert step_at_joint < 1.5 * typical
    assert abs(joined.shape[1] - ref.shape[1]) <= 2


def test_formats_offered_and_aac_needs_ffmpeg():
    fm = codec.available_formats()
    assert "opus" in fm and "flac" in fm
    if "aac" not in fm:
        with pytest.raises(RuntimeError):
            codec.encode_segment(music_like(1.0), 44100, "aac")


def test_whole_song_guard_checks_windows_and_says_what_it_covered():
    from stage.stream.guard import guard_windows

    sr = 22050
    rng = np.random.default_rng(3)
    t = np.arange(70 * sr) / sr
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 1.7 * t) ** 2  # a beat for the alignment check
    x = (rng.standard_normal((2, t.size)) * env * 0.1).astype(np.float32)
    rep = guard_windows(x, x * 0.98, sr, {"engine": "test"}, n_windows=3, window_s=10.0)
    assert rep["verdict"] == "pass" and rep["coverage"]["full"] is False
    assert rep["coverage"]["analysed_s"] == 30.0 and rep["coverage"]["song_s"] == 70.0
    assert len(rep["coverage"]["windows"]) == 3
    short = guard_windows(x[:, : 20 * sr], x[:, : 20 * sr], sr, {"engine": "test"})
    assert short["coverage"]["full"] is True
    bad = guard_windows(x, x * 0.3, sr, {"engine": "test"}, n_windows=3, window_s=10.0)
    assert bad["verdict"] == "fail" and any("whole song" in r for r in bad["reasons"])
