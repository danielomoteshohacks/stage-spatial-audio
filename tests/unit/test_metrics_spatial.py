"""The spatial metrics (decision 0022): the numbers must mean what their names say."""

import numpy as np
import pytest

from stage.groundtruth import LEAVES, make_object_song, pan_gains
from stage.metrics.separation import (
    best_stem_for,
    map_distance_deg,
    match_leaves,
    sdr_db,
)
from stage.metrics.spatial import (
    DirectionMap,
    angular_distance_deg,
    iacc,
    measured_drr_db,
    object_spread,
    sector_shares,
    v2_feeds,
)
from stage.scene.plan import get_template

SR = 44100


def dmap(points: list[tuple[float, float, float]]) -> DirectionMap:
    az, el, d = (np.array(v) for v in zip(*points, strict=True))
    z = np.zeros(len(d))
    return DirectionMap(az=az, el=el, direct=d, room=z, late=z, objects=["a"], owner=["a"] * len(d))


def test_angular_distance_basics():
    assert angular_distance_deg(0, 0, 0, 0) == pytest.approx(0)
    assert angular_distance_deg(0, 0, 90, 0) == pytest.approx(90)
    assert angular_distance_deg(0, 0, 180, 0) == pytest.approx(180)
    assert angular_distance_deg(10, 90, -170, 90) == pytest.approx(0, abs=1e-6)  # the pole
    assert angular_distance_deg(-179, 0, 179, 0) == pytest.approx(2)  # wraps


def test_sectors_partition_the_energy():
    m = dmap([(0, 0, 4), (20, 10, 1), (60, 0, 2), (-90, 0, 1), (150, 0, 1), (0, 60, 1)])
    s = sector_shares(m)
    assert s["front"] + s["side"] + s["rear"] + s["height"] == pytest.approx(1.0)
    assert s["front"] == pytest.approx(0.5)
    assert s["side"] == pytest.approx(0.3)
    assert s["rear"] == pytest.approx(0.1)
    assert s["height"] == pytest.approx(0.1)
    # A front object raised into the height layer is not "outside the front" by azimuth.
    assert s["outside_front_az"] == pytest.approx(0.4)


def test_object_spread_merges_close_directions_and_ignores_quiet_ones():
    # Two feeds 10 degrees apart are one place; a 2 percent feed is not independent.
    m = dmap([(0, 0, 10), (10, 0, 10), (90, 0, 10), (-90, 0, 10), (180, 0, 0.8)])
    assert object_spread(m) == 3
    assert object_spread(dmap([(0, 0, 1)])) == 1
    assert object_spread(dmap([(0, 0, 0)])) == 0


def test_iacc_of_identical_and_independent_channels():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(SR * 2)
    assert iacc(np.stack([x, x]), SR) > 0.99
    y = rng.standard_normal(SR * 2)
    assert iacc(np.stack([x, y]), SR) < 0.1


def test_measured_drr_recovers_a_known_response():
    rng = np.random.default_rng(1)
    src = rng.standard_normal(SR * 4)
    n_tail = int(0.4 * SR)
    tail = rng.standard_normal((2, n_tail)) * np.exp(-np.arange(n_tail) / SR * 12)
    tail *= 0.5 / np.sqrt(np.sum(tail**2) / 2)  # tail energy 0.25 per ear, direct energy 1
    h = np.zeros((2, n_tail))
    h[:, 100] = 1.0
    h[:, 200:] += tail[:, 200:]
    render = np.stack([np.convolve(src, h[e])[: src.size] for e in range(2)])
    got = measured_drr_db(src, render, SR)
    expected = 10 * np.log10(1.0 / (np.sum(h[:, 200:] ** 2) / 2))
    assert got["drr_db"] == pytest.approx(expected, abs=0.7)
    assert got["late_share"] > 0.0


def test_map_distance_is_zero_for_equal_maps_and_grows_with_the_move():
    a = dmap([(15, 0, 1)])
    assert map_distance_deg(a, a) == pytest.approx(0.0, abs=1e-6)
    near = map_distance_deg(a, dmap([(45, 0, 1)]))
    far = map_distance_deg(a, dmap([(105, 0, 1)]))
    assert near == pytest.approx(30, abs=1e-3)
    assert far == pytest.approx(90, abs=1e-3)


def test_sdr_and_permutation_match():
    rng = np.random.default_rng(2)
    refs = {"a": rng.standard_normal((2, 4000)), "b": rng.standard_normal((2, 4000))}
    ests = {"x": refs["b"] + 0.01 * rng.standard_normal((2, 4000)),
            "y": refs["a"] + 0.01 * rng.standard_normal((2, 4000))}
    assert match_leaves(refs, ests) == {"a": "y", "b": "x"}
    assert sdr_db(refs["a"], refs["a"]) > 100
    assert sdr_db(refs["a"], ests["y"]) == pytest.approx(40, abs=1.5)
    assert best_stem_for(refs["a"], ests) == "y"


def test_v2_feed_weights_sum_to_one_for_every_template_object():
    plan = {"space": "studio", "sections": [], "bed": {"ambience": 1.0, "heights": 0.5},
            "analysis_sample_rate": 22050}
    for genre in ("pop", "house", "classical"):
        for obj in get_template(genre)["objects"]:
            obj.pop("why", None)
            feeds = v2_feeds(obj, plan)
            assert sum(f.weight for f in feeds) == pytest.approx(1.0)
            assert all(0.0 <= f.direct <= 1.0 and f.direct + f.early <= 1.0 + 1e-9 for f in feeds)


def test_pan_gains_fold_the_rear_to_the_front_and_keep_power():
    for az in (-170, -90, 0, 45, 125, 180):
        gl, gr = pan_gains(az)
        assert gl**2 + gr**2 == pytest.approx(1.0)
    assert pan_gains(0)[0] == pytest.approx(pan_gains(0)[1])
    assert pan_gains(90)[0] > 0.99 and pan_gains(-90)[1] > 0.99
    assert pan_gains(125) == pytest.approx(pan_gains(55))  # a rear source folds to the same pan


SHORT = (("verse", 2, 0.55), ("chorus", 2, 1.0))


def test_object_song_leaves_sum_to_the_mix_and_are_seeded():
    a = make_object_song(seed=3, bars=SHORT)
    b = make_object_song(seed=3, bars=SHORT)
    assert set(a.stereo) == {s.name for s in LEAVES}
    np.testing.assert_array_equal(a.mix, b.mix)
    assert float(np.max(np.abs(a.mix))) == pytest.approx(0.7, abs=1e-6)
    four = a.four_stems()
    np.testing.assert_allclose(sum(four.values()), a.mix, atol=1e-9)
    # The two guitars are double-tracked, not copies.
    c = np.corrcoef(a.mono["guitar_l"], a.mono["guitar_r"])[0, 1]
    assert abs(c) < 0.5


def test_truth_binaural_places_a_left_leaf_louder_in_the_left_ear():
    song = make_object_song(seed=0, bars=SHORT)
    y = song.truth_binaural()
    assert y.shape == song.mix.shape
    gl = song.stereo["guitar_l"]  # az +65, to the left
    only = type(song)(song.sample_rate, song.tempo_bpm, song.sections, song.specs,
                      {k: (v if k == "guitar_l" else v * 0) for k, v in song.mono.items()})
    yl = only.truth_binaural()
    assert np.sum(yl[0] ** 2) > 2 * np.sum(yl[1] ** 2)
    assert gl[0].std() > gl[1].std()


def test_bleedless_and_fullness_follow_their_definitions():
    from stage.metrics.separation import bleed_full, mel_filterbank

    sr = 22050
    rng = np.random.default_rng(0)
    t = np.arange(sr * 2) / sr
    ref = np.stack([np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 660 * t)]) * 0.5
    ref = ref + 0.01 * rng.standard_normal(ref.shape)
    b0, f0 = bleed_full(ref, ref, sr=sr, n_fft=2048, hop=512, n_mels=128)
    assert b0 == pytest.approx(100.0) and f0 == pytest.approx(100.0)
    # Bleed: another source added on top lowers bleedless and leaves fullness near 100.
    other = 0.3 * np.stack([np.sin(2 * np.pi * 3000 * t)] * 2)
    b1, f1 = bleed_full(ref, ref + other, sr=sr, n_fft=2048, hop=512, n_mels=128)
    assert b1 < 60 and f1 > 90
    # Missing content: a lowpassed estimate lowers fullness and leaves bleedless high.
    from scipy.signal import butter, sosfiltfilt
    low = sosfiltfilt(butter(4, 500, "lowpass", fs=sr, output="sos"), ref, axis=-1)
    b2, f2 = bleed_full(ref, low, sr=sr, n_fft=2048, hop=512, n_mels=128)
    assert f2 < 60 and b2 > f2
    fb = mel_filterbank(sr, 2048, 128)
    assert fb.shape == (128, 1025) and (fb >= 0).all() and fb.sum(axis=1).min() > 0
