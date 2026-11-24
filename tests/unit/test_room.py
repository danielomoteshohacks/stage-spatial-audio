"""Binaural rooms: presets hit their RT60, air absorption, image sources, coherence, v2 render."""

import numpy as np
import pytest

from stage.engines import DEFAULT_PROFILE, profile_names, render
from stage.guard.report import build_report
from stage.spatial.hrtf import get_hrtf
from stage.spatial.neutral import split_low_high
from stage.spatial.room import (
    OCTAVES,
    air_absorption_db_per_m,
    brir,
    get_space,
    image_sources,
    late_field,
    source_position,
    spaces,
    surface_absorption,
)
from stage.spatial.roommetrics import band_rt60

FS = 48000


@pytest.fixture(scope="module")
def hs():
    return get_hrtf(FS)


def test_six_documented_spaces_with_generic_names():
    sp = spaces()
    assert set(sp) == {"studio", "living_room", "car", "club", "concert_hall", "cinema"}
    for s in sp.values():
        assert len(s.rt60_s) == OCTAVES.size and len(s.why) > 60
        assert all(0 < v < s.size_m[i] for i, v in enumerate(s.listener_m))


@pytest.mark.parametrize("name", ["studio", "living_room", "car", "club", "concert_hall",
                                  "cinema"])
def test_measured_rt60_follows_the_preset(name, hs):
    # Schroeder T30 of the whole response, per octave. An octave filter's own ringing sets a
    # floor on the decay it can measure: the band-width times RT60 product must exceed about 16
    # (Jacobsen 1987, "A note on acoustic decay measurements", J. Sound Vib. 115). Below that the
    # measurement only bounds the decay, so it is checked as an upper bound.
    sp = get_space(name)
    measured = band_rt60(brir(sp, hs, 30.0, 0.0, sp.speaker_distance_m).total, FS)
    for fc, target in zip(OCTAVES, sp.rt60_s, strict=True):
        got = measured[str(int(fc))]
        if 0.707 * fc * target < 16.0:
            assert got < target + 0.1, (name, fc, target, got)
        else:
            assert abs(got - target) <= 0.15 * target + 0.03, (name, fc, target, got)


def test_iso_9613_air_absorption_values():
    # ISO 9613-1 Table 1, 20 C, 50 % relative humidity: about 4.7 dB/km at 1 kHz and
    # about 105 dB/km at 8 kHz.
    a = air_absorption_db_per_m(np.array([1000.0, 8000.0])) * 1000.0
    assert a[0] == pytest.approx(4.66, abs=0.1) and a[1] == pytest.approx(105.0, rel=0.03)


def test_eyring_absorption_is_in_range_and_rises_where_rt60_falls():
    sp = get_space("living_room")
    alpha = surface_absorption(sp)
    for table in alpha.values():
        assert np.all((table > 0) & (table < 1))
    assert alpha["walls"][-1] > alpha["walls"][0]


def test_image_sources_have_their_own_directions_and_order():
    sp = get_space("studio")
    src = source_position(sp, 30.0, 0.0, 1.8)
    imgs = image_sources(sp, src)
    assert max(sum(i.hits) for i in imgs) == sp.order
    assert all(i.delay_s > 0 for i in imgs)
    floor = [i for i in imgs if i.hits == (0, 0, 0, 0, 1, 0)]
    assert floor and floor[0].el_deg < 0  # the floor reflection comes from below


def test_late_field_has_the_heads_measured_coherence(hs):
    sp = get_space("concert_hall")
    y = late_field(sp, hs, int(1.5 * FS))
    spec = np.fft.rfft(y, axis=-1)
    f = np.fft.rfftfreq(y.shape[1], 1 / FS)
    band = (f > 300) & (f < 400)
    measured = np.real(np.sum(spec[0, band] * np.conj(spec[1, band]))) / np.sqrt(
        np.sum(np.abs(spec[0, band]) ** 2) * np.sum(np.abs(spec[1, band]) ** 2))
    target = np.interp(f[band], hs.freqs, hs.df_coherence).mean()
    assert measured == pytest.approx(target, abs=0.1)


def test_the_low_band_split_is_exact_and_the_bass_passes_untouched():
    x = np.random.default_rng(0).standard_normal((2, FS))
    low, high = split_low_high(x, FS)
    assert np.max(np.abs(low + high - x)) < 1e-12
    y, info = render(x * 0.1, FS, DEFAULT_PROFILE)
    assert info["engine"] == "v2" and info["space"] == "studio"
    low_y, _ = split_low_high(y, FS)
    low_x, _ = split_low_high(x * 0.1, FS)
    # Below the crossover the render is the original: only the crossover's own skirt from the
    # rendered upper band leaks in.
    assert np.corrcoef(low_y.ravel(), low_x.ravel())[0, 1] > 0.99


def test_v2_render_is_aligned_loudness_matched_and_keeps_the_bass():
    fs = 44100
    t = np.arange(4 * fs) / fs
    rng = np.random.default_rng(1)
    x = np.stack([0.2 * np.sin(2 * np.pi * 55 * t), 0.2 * np.sin(2 * np.pi * 55 * t)])
    x += 0.05 * rng.standard_normal(x.shape)
    for k in range(0, x.shape[1], fs // 2):
        x[:, k : k + 400] += rng.standard_normal((2, min(400, x.shape[1] - k))) * 0.3
    y, _ = render(x, fs, "space:studio")
    r = build_report(x, y, fs, {"engine": "test"})
    assert abs(r["alignment_ms"]) < 1.0
    assert abs(r["loudness_lufs"]["render"] - r["loudness_lufs"]["original"]) < 0.1
    assert r["low_end"]["identity_corr"] > 0.99 and abs(r["low_end"]["level_db"]) < 0.5


def test_every_space_is_a_profile():
    names = profile_names()
    assert names[0] == DEFAULT_PROFILE
    assert {f"space:{n}" for n in spaces()} <= set(names) and "max" in names
