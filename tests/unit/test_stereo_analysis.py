import numpy as np

from stage.analysis import (
    analyse_stereo,
    angle_to_position,
    position_to_angle_deg,
    stft,
)

SR = 44100
HOP = 1024
WARMUP = 15  # frames to skip while the smoothing settles


def _analyse(left, right):
    spec = stft(np.stack([left, right]), n_fft=2048, hop=HOP)
    return analyse_stereo(spec[0], spec[1], hop=HOP, sample_rate=SR)


def _panned(phi_deg, seconds=4.0, noise_db=-40.0, seed=0):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    s = rng.standard_normal(n)
    amp = 10 ** (noise_db / 20)
    left = np.cos(np.radians(phi_deg)) * s + amp * rng.standard_normal(n)
    right = np.sin(np.radians(phi_deg)) * s + amp * rng.standard_normal(n)
    return left, right


def test_tangent_law_example_from_the_specification():
    # k = 3 means position (3 - 1) / (3 + 1) = 0.5, which is about 16.1 degrees to the right.
    assert abs(float(position_to_angle_deg(0.5)) - 16.1) < 0.05


def test_angle_position_round_trip():
    angles = np.linspace(-30, 30, 13)
    assert np.allclose(position_to_angle_deg(angle_to_position(angles)), angles)


def test_recovers_the_position_of_a_panned_source():
    phi = 60.0  # more energy on the right
    expected = (np.sin(np.radians(phi)) - np.cos(np.radians(phi))) / (
        np.sin(np.radians(phi)) + np.cos(np.radians(phi))
    )
    res = _analyse(*_panned(phi))
    pos = res.position[WARMUP:]
    assert abs(float(np.median(pos)) - expected) < 0.03
    assert float(np.median(res.inphase_coherence[WARMUP:])) > 0.95


def test_hard_left_and_hard_right():
    left_only = _analyse(*_panned(0.0))
    right_only = _analyse(*_panned(90.0))
    assert float(np.median(left_only.position[WARMUP:])) < -0.97
    assert float(np.median(right_only.position[WARMUP:])) > 0.97
    assert abs(float(np.median(left_only.angle_deg[WARMUP:])) + 30) < 0.5


def test_centre_source_is_centred():
    res = _analyse(*_panned(45.0))
    assert abs(float(np.median(res.position[WARMUP:]))) < 0.02


def test_independent_noise_has_low_coherence():
    rng = np.random.default_rng(3)
    n = 4 * SR
    res = _analyse(rng.standard_normal(n), rng.standard_normal(n))
    assert float(np.mean(res.inphase_coherence[WARMUP:])) < 0.4


def test_antiphase_content_is_coherent_but_not_in_phase():
    rng = np.random.default_rng(4)
    s = rng.standard_normal(4 * SR)
    res = _analyse(s, -s)
    assert float(np.mean(res.coherence[WARMUP:])) > 0.95
    assert float(np.mean(res.inphase_coherence[WARMUP:])) < 0.05


def test_time_delayed_content_is_not_treated_as_amplitude_panned():
    # A spaced-microphone style pair: the right channel is a delayed copy of the left.
    rng = np.random.default_rng(5)
    s = rng.standard_normal(4 * SR + 40)
    left, right = s[40:], s[:-40]
    res = _analyse(left, right)
    assert float(np.mean(res.coherence[WARMUP:])) > 0.9
    assert float(np.mean(res.inphase_coherence[WARMUP:])) < 0.5


def test_silence_is_centred_and_finite():
    res = _analyse(np.zeros(SR), np.zeros(SR))
    assert np.all(np.isfinite(res.position))
    assert np.all(res.position == 0.0)
    assert np.all(res.primary == 0)
