import numpy as np
import pytest
from scipy.signal import fftconvolve

from stage.metrics.separation import sdr_db
from stage.separation.cascade import adress, ensemble, post
from stage.separation.cascade.dereverb import dereverb_dsp, estimate_rt60, guard

SR = 22050


def stereo_pan(x, pan):
    a = (pan + 1.0) * np.pi / 4.0
    return np.stack([np.cos(a) * x, np.sin(a) * x])


def tonal(seed, seconds=3.0, f0=220.0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    x = sum(np.sin(2 * np.pi * f0 * k * (1 + 0.003 * seed) * t) / k for k in range(1, 8))
    return x * (1 + 0.4 * np.sin(2 * np.pi * (1.5 + seed) * t)) + 0.01 * rng.standard_normal(t.size)


def test_pan_map_recovers_known_pans_and_confidence():
    for pan in (-0.8, 0.0, 0.5):
        x = stereo_pan(tonal(0), pan)
        spec = adress.stft(x, 2048, 512)
        p, c = adress.pan_map(spec[0], spec[1])
        loud = np.abs(spec[0]) > 0.2 * np.abs(spec[0]).max()
        # The map's pan is (R - L) / (R + L) of the channel gains: tan(pan * pi / 4).
        assert np.median(p[loud]) == pytest.approx(np.tan(pan * np.pi / 4), abs=0.03)
        assert np.median(c[loud]) > 0.95


def test_azimuth_split_separates_two_panned_sources_and_sums_back():
    a, b = stereo_pan(tonal(1, f0=200), -0.8), stereo_pan(tonal(2, f0=313), 0.8)
    mix = a + b
    outs, centres, _ = adress.azimuth_split(mix)
    assert len(centres) == 2 and centres[0] < 0 < centres[1]
    assert np.abs(sum(outs) - mix).max() < 1e-9
    assert sdr_db(a, outs[0]) > 8.0
    assert sdr_db(b, outs[1]) > 8.0
    # A single-cluster stem comes back whole.
    one, c1, _ = adress.azimuth_split(stereo_pan(tonal(3), 0.3))
    assert len(one) == 1


def test_soft_masks_sum_to_one():
    rng = np.random.default_rng(0)
    pan = rng.uniform(-1, 1, (20, 30))
    conf = rng.uniform(0, 1, (20, 30))
    m = adress.soft_masks(pan, conf, [-0.5, 0.4])
    assert m.sum(axis=0) == pytest.approx(np.ones((20, 30)))


def test_multichannel_wiener_and_consistency_sum_to_the_mix():
    a, b = stereo_pan(tonal(1, f0=200), -0.8), stereo_pan(tonal(2, f0=313), 0.8)
    mix = a + b
    rng = np.random.default_rng(0)
    noisy = {"a": a + 0.3 * b + 0.02 * rng.standard_normal(a.shape), "b": b + 0.3 * a}
    out = post.multichannel_wiener(mix, noisy, iterations=2)
    assert np.abs(sum(out.values()) - mix).max() < 5e-3
    assert sdr_db(a, out["a"]) > sdr_db(a, noisy["a"])
    cons = post.mixture_consistency(mix, noisy)
    assert np.abs(sum(cons.values()) - mix).max() < 1e-9


def test_flicker_detector_separates_clean_masks_from_random_ones():
    a, b = stereo_pan(tonal(1, f0=200), -0.8), stereo_pan(tonal(2, f0=313), 0.8)
    mix = a + b
    _, clean = post.detect_musical_noise(a, mix)
    spec = post.stft(mix, 2048, 512)
    rng = np.random.default_rng(0)
    m = (rng.random(spec.shape[1:]) < 0.5).astype(float)
    bad = post.istft(spec * m[None], mix.shape[1], 2048, 512)
    _, speckled = post.detect_musical_noise(bad, mix)
    assert clean < 20.0
    assert speckled > 5 * max(clean, 5.0)


def test_repair_only_touches_leaves_that_fire():
    a, b = stereo_pan(tonal(1, f0=200), -0.8), stereo_pan(tonal(2, f0=313), 0.8)
    mix = a + b
    out, rates = post.repair_musical_noise(mix, {"a": a, "b": b})
    assert max(rates.values()) < 25.0
    # Nothing fired: the leaves are still a split of the mix.
    assert np.abs(sum(out.values()) - mix).max() < 1e-6


def test_leaf_quality_penalises_a_speckled_leaf_and_merge_folds_it_into_its_parent():
    a, b = stereo_pan(tonal(1, f0=200), -0.8), stereo_pan(tonal(2, f0=313), 0.8)
    mix = a + b
    spec = post.stft(a, 2048, 512)
    rng = np.random.default_rng(1)
    bad = post.istft(spec * (rng.random(spec.shape[1:]) < 0.5)[None], a.shape[1], 2048, 512)
    q = post.leaf_quality({"good": b, "bad": bad}, mix)
    assert q["good"].score > 80
    assert q["bad"].score < 40
    merged, moved = post.merge_poor_leaves({"good": b, "bad": bad}, {"bad": "good"}, q)
    assert moved == {"bad": "good"} and set(merged) == {"good"}
    np.testing.assert_allclose(merged["good"], b + bad)


def test_dereverb_splits_exactly_and_removes_late_energy():
    dry = tonal(4, seconds=4.0) * (np.arange(int(4.0 * SR)) % (SR // 2) < SR // 8)  # short notes
    n = int(0.5 * SR)
    ir = np.random.default_rng(0).standard_normal(n) * np.exp(-6.9 * np.arange(n) / (0.5 * SR))
    ir[0] = 5.0
    wet = fftconvolve(dry, ir)[: dry.size]
    x = np.stack([wet, wet])
    d, r, rt = dereverb_dsp(x, SR, rt60=0.5)
    assert np.abs(d + r - x).max() < 1e-9
    # Energy between the notes (where only reverb is left) must drop clearly.
    gap = (np.arange(dry.size) % (SR // 2)) > SR // 3
    assert np.mean(d[0][gap] ** 2) < 0.6 * np.mean(x[0][gap] ** 2)


def test_rt60_estimate_is_in_range_and_guard_follows_the_ten_db_rule():
    t = np.arange(4 * SR) / SR
    env = np.exp(-6.9 * (t % 1.0) / 0.6)
    x = np.stack([env * np.random.default_rng(0).standard_normal(t.size)] * 2)
    assert 0.2 <= estimate_rt60(x, SR) <= 2.0
    assert guard(x * 0.5, x) and not guard(x * 0.1, x)


def test_band_ensemble_prefers_the_better_model_per_band():
    ref = stereo_pan(tonal(1, 4.0) + 0.5 * tonal(5, 4.0, f0=1500), 0.0)
    from stage.analysis.stft import istft, stft
    f = np.fft.rfftfreq(4096, 1.0 / SR)

    def noise_in(band_mask, seed):
        z = np.random.default_rng(seed).standard_normal(ref.shape)
        return istft(stft(z, 4096, 1024) * band_mask[None, None], ref.shape[1], 4096, 1024)

    # Model 0 is clean below 1 kHz and noisy above; model 1 the opposite, each with its own noise.
    e0 = ref + 1.0 * noise_in((f >= 1000).astype(float), 1)
    e1 = ref + 1.0 * noise_in((f < 1000).astype(float), 2)
    edges = [0, 1000, 5000]
    w = ensemble.fit_band_weights([[e0, e1]], [ref], SR, edges)
    assert w[0, 0] > 0.8  # low band: model 0
    assert w[2, 1] > 0.8  # top band: model 1
    comb = ensemble.combine([e0, e1], w, SR, edges)
    equal = ensemble.combine([e0, e1], None, SR, edges)
    assert sdr_db(ref, comb) > sdr_db(ref, equal) + 3
