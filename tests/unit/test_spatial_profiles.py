"""Gates of the spatialisation spike, as written in advance in docs/decisions/0007.

Every number below is copied from the proxy table of 0007. A gate that failed in the measurement
is kept literally and marked xfail(strict=True) with the measured value: the gate is not
weakened, and if a later change makes it pass, the strict xfail flags that for review.
All signals are synthetic; no audio files.
"""

import numpy as np
import pytest

from stage.analysis import angle_to_position
from stage.render import render_stereo
from stage.render.pinna import ear_filters, nearfield_ild_db, pinna_response
from stage.render.profiles import (
    Profile,
    get_profile,
    role_impulse_response,
    sector_render_azimuths,
)
from stage.render.proxies import (
    band_coherence,
    directional_tilt_db,
    drr_db,
    echo_density,
    match_rms,
    rms_db_change,
    rt60_t30,
    timbre_deviation_db,
)
from stage.render.room import (
    SPEED_OF_SOUND_M_S,
    Room,
    coherence_mix,
    diffuse_coherence,
    fdn_process,
    image_sources,
    source_position,
)
from stage.render.rotation import AzimuthFilterBank

FS = 44100
N = 6 * FS
FREQS = np.fft.rfftfreq(2048, 1 / FS)


def _pink(n, seed):
    spec = np.fft.rfft(np.random.default_rng(seed).standard_normal(n))
    f = np.fft.rfftfreq(n)
    f[0] = f[1]
    x = np.fft.irfft(spec / np.sqrt(f), n=n)
    return x / x.std()


def _panned(mono, angle_deg):
    pos = float(angle_to_position(angle_deg))
    ratio = (1.0 + pos) / (1.0 - pos)
    g_l = 1.0 / np.sqrt(1.0 + ratio**2)
    return np.stack([g_l * mono, g_l * ratio * mono])


@pytest.fixture(scope="module")
def test_mix():
    """The 0007 pink test mix: a centred, two panned and one decorrelated source."""
    return (
        np.stack([_pink(N, 1)] * 2) * 0.5
        + _panned(_pink(N, 2), 15.0) * 0.4
        + _panned(_pink(N, 3), -25.0) * 0.4
        + np.stack([_pink(N, 4), _pink(N, 5)]) * 0.3
    )


_RENDERS: dict[str, np.ndarray] = {}


def _render(mix, name):
    if name not in _RENDERS:
        _RENDERS[name] = render_stereo(mix, FS, profile=name)
    return _RENDERS[name]


def _edge_ild(name):
    out = render_stereo(np.stack([np.zeros(N), _pink(N, 6)]), FS, profile=name)
    return 10.0 * np.log10(np.sum(out[1] ** 2) / np.sum(out[0] ** 2))


def _tilt(name):
    p = get_profile(name)
    front = ear_filters([0.0], pinna=p.pinna, steering_db=p.steering_db)[0]
    rear = ear_filters([180.0], pinna=p.pinna, steering_db=p.steering_db)[0]
    return directional_tilt_db(front, FREQS) - directional_tilt_db(rear, FREQS)


def _drr(name):
    out = {}
    for role in ("near", "mid", "far"):
        ir = role_impulse_response(name, role, FS)
        out[role] = drr_db(ir["direct"], ir["early"] + ir["late"])
    return out


def _fail(reason):
    return pytest.mark.xfail(strict=True, reason=f"gate failed in 0007 measurement: {reason}")


# --- Profile plumbing --------------------------------------------------------------------------


def test_v0_profile_is_bit_identical_to_the_default(test_mix):
    assert np.array_equal(render_stereo(test_mix, FS, profile="V0"), render_stereo(test_mix, FS))


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError):
        render_stereo(np.zeros((2, 1000)), FS, profile="V9")


@pytest.mark.parametrize("name", ["V1", "V2", "V3", "V4b", "max"])
def test_profiles_are_finite_same_length_and_deterministic(name):
    x = np.stack([_pink(FS, 11), _pink(FS, 12)])
    first = render_stereo(x, FS, profile=name)
    assert first.shape == x.shape and np.all(np.isfinite(first))
    assert np.array_equal(first, render_stereo(x, FS, profile=name))


def test_max_is_exactly_the_passing_toggles():
    m = get_profile("max")
    assert (m.front_limit_deg, m.pinna, m.steering_db, m.early, m.late) == (60.0, True, 1.5, True,
                                                                             False)
    assert (m.early_highpass_hz, m.early_send_db) == (200.0, -3.0)


# --- H11 front-arc limit -------------------------------------------------------------------------


@pytest.mark.parametrize("beta", [1.0, 2.0, 2.4])
def test_h11a_no_sector_is_rendered_past_60_degrees(beta):
    assert np.max(np.abs(sector_render_azimuths(get_profile("V1"), beta))) <= 60.0


def test_h11b_v1_keeps_at_least_80_percent_of_the_edge_ild():
    assert _edge_ild("V1") >= 0.8 * _edge_ild("V0")  # measured 2.83 vs 3.04 dB (93 percent)


# --- P1 front-rear tilt in the directional bands --------------------------------------------------


@pytest.mark.parametrize("name", ["V0", "V1"])
def test_p1_mirror_symmetric_profiles_have_no_tilt(name):
    assert abs(_tilt(name)) <= 0.05


def test_p1_v2_pinna_tilt_has_blauerts_sign():
    assert _tilt("V2") >= 1.0  # measured +2.19 dB


def test_p1_v3_steering_tilt():
    assert _tilt("V3") >= 4.0  # measured +7.19 dB


@pytest.mark.parametrize("name", ["V4", "V5", "V4b", "V5b"])
def test_p1_room_profiles_keep_the_v3_direct_path_tilt(name):
    assert abs(_tilt(name) - _tilt("V3")) <= 0.05


# --- H12a pinna elevation ------------------------------------------------------------------------


def test_h12a_pinna_notch_rises_with_elevation():
    f = np.linspace(5000.0, 14000.0, 2000)
    notches = [f[np.argmin(np.abs(pinna_response([0.0], [el], f))[0])]
               for el in (-30.0, -15.0, 0.0, 15.0, 30.0, 45.0)]
    assert np.all(np.diff(notches) > 0.0), notches  # measured 9.8 to 13.5 kHz


# --- P5 timbre and P6 loudness -------------------------------------------------------------------

_TIMBRE_GATES = [
    ("V0", 3.0),  # baseline, 2.45 measured; 3.0 only guards against regression
    ("V1", 3.45),
    ("V2", 3.45),
    ("V3", 3.45),
    pytest.param("V4", 4.0, marks=_fail("10.36 dB, low-frequency build-up of reflections")),
    pytest.param("V5", 4.0, marks=_fail("10.88 dB, as V4 plus late field")),
    ("V4b", 4.0),
    pytest.param("V5b", 4.0, marks=_fail("4.30 dB, late field dulls 8 kHz by -4.3 dB")),
]


@pytest.mark.parametrize(("name", "gate_db"), _TIMBRE_GATES)
def test_p5_worst_octave_deviation(test_mix, name, gate_db):
    dev = timbre_deviation_db(test_mix, _render(test_mix, name), FS)
    assert np.max(np.abs(dev)) <= gate_db, np.round(dev, 2)


_LOUDNESS_GATES = [
    ("V0", 1.5),
    ("V1", 1.5),
    ("V2", 3.0),
    ("V3", 3.0),
    pytest.param("V4", 3.0, marks=_fail("+7.60 dB before matching")),
    pytest.param("V5", 3.0, marks=_fail("+8.49 dB before matching")),
    ("V4b", 3.0),
    ("V5b", 3.0),
]


@pytest.mark.parametrize(("name", "gate_db"), _LOUDNESS_GATES)
def test_p6_raw_level_change_and_match_residual(test_mix, name, gate_db):
    out = _render(test_mix, name)
    assert abs(rms_db_change(test_mix, out)) <= gate_db
    assert abs(rms_db_change(test_mix, match_rms(test_mix, out))) <= 0.05


# --- P2 DRR against role distance ----------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["V4b", pytest.param("V4", marks=_fail("near DRR +5.6 dB, gate at least +6"))],
)
def test_p2_early_reflection_drr(name):
    d = _drr(name)  # V4b measured +8.7 / +4.6 / +0.2 dB
    assert d["near"] >= 6.0
    assert d["near"] - d["mid"] >= 2.0 and d["mid"] - d["far"] >= 2.0


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("V5", marks=_fail("+4.6 / +0.6 / -3.8 dB: near below +6, steps 4.0, 4.4")),
        pytest.param("V5b", marks=_fail("+7.0 / +2.9 / -1.6 dB: steps 4.1 and 4.5, below 5")),
    ],
)
def test_p2_late_field_drr(name):
    d = _drr(name)
    assert 6.0 <= d["near"] <= 14.0 and 0.0 <= d["mid"] <= 8.0 and -6.0 <= d["far"] <= 3.0
    assert d["near"] - d["mid"] >= 5.0 and d["mid"] - d["far"] >= 5.0


def test_p2_profiles_without_a_room_have_no_reverberant_part():
    ir = role_impulse_response("V3", "mid", FS)
    assert not np.any(ir["early"]) and not np.any(ir["late"])


# --- H14 image sources ---------------------------------------------------------------------------


def test_h14_twelve_reflections_with_geometric_delays():
    room = Room()
    src = source_position(room, 0.0, 1.0)
    refl = image_sources(room, src)[:12]
    assert len(refl) == 12
    # The floor image is the mirror of the source in z = 0: an independent closed form.
    h = room.listener_m[2]
    floor = next(r for r in refl if r.hits == (0, 0, 0, 0, 1, 0))
    expected = (np.hypot(1.0, 2.0 * h) - 1.0) / SPEED_OF_SOUND_M_S
    assert abs(floor.delay_s - expected) * FS < 0.5
    assert floor.el_deg < 0.0  # it comes from below
    assert all(r.delay_s > 0.0 for r in refl)


# --- P3 coherence and P4 room --------------------------------------------------------------


@pytest.fixture(scope="module")
def late_ir():
    imp = np.zeros(int(2.4 * FS))
    imp[0] = 1.0
    return coherence_mix(fdn_process(imp, FS), FS)


@_fail("V0 ambient-path coherence is 0.64 at 125 Hz: the primary path of uncorrelated input is "
       "coherent at low frequency; the expectation in 0007 was wrong, not a regression")
def test_p3_v0_ambient_path_is_decorrelated_in_every_octave():
    out = render_stereo(np.stack([_pink(N, 7), _pink(N, 8)]), FS)
    assert np.all(np.abs(band_coherence(out[0], out[1], FS)) <= 0.1)


def test_p3_late_field_coherence_tracks_the_target(late_ir):
    coh = band_coherence(late_ir[0], late_ir[1], FS)
    target = diffuse_coherence(np.array([125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0]))
    assert np.all(np.abs(coh[:6] - target) <= 0.15), (coh, target)
    assert coh[0] >= 0.8  # bass stays together; measured 0.88


def test_p4_rt60(late_ir):
    mono = late_ir.sum(axis=0)
    assert 0.51 <= rt60_t30(mono, FS, 1000.0) <= 0.69  # measured 0.596 s
    assert rt60_t30(mono, FS, 4000.0) < rt60_t30(mono, FS, 500.0)


def test_p4_echo_density(late_ir):
    ned = echo_density(late_ir[0][: int(0.32 * FS)], FS)
    assert ned[int(0.1 * FS) : int(0.3 * FS)].mean() >= 0.90  # measured 0.95


def test_fdn_is_stable_and_decays(late_ir):
    first, last = late_ir[:, : FS // 4], late_ir[:, -FS // 4 :]
    assert np.all(np.isfinite(late_ir))
    assert np.sum(last**2) < 1e-4 * np.sum(first**2)


# --- H16 near field -------------------------------------------------------------------------------


def test_h16_nearfield_ild():
    assert nearfield_ild_db(60.0, 1.0) >= 1.0  # measured 1.47 dB
    assert abs(nearfield_ild_db(0.0, 1.0)) < 0.01


# --- H17 rotation ---------------------------------------------------------------------------------


@pytest.mark.parametrize("k", [1, 7, 90, 359])
def test_h17a_rotation_is_an_exact_index_roll(k):
    bank = AzimuthFilterBank(1.0)
    az = np.array([-50.0, -12.5, 0.0, 33.3, 50.0])
    rolled = AzimuthFilterBank(1.0)
    rolled.residual = np.roll(bank.residual, k, axis=0)
    rolled.delay_s = np.roll(bank.delay_s, k, axis=0)
    # Turning the head by k steps = reading a table rolled by k: no filter is redesigned.
    assert np.max(np.abs(bank.lookup(az, yaw_deg=k) - rolled.lookup(az))) <= 1e-12


@pytest.mark.parametrize("cues", [{}, {"pinna": True, "steering_db": 1.5}])
def test_h17b_interpolation_halfway_between_grid_points(cues):
    bank = AzimuthFilterBank(1.0, **cues)
    sel = (FREQS > 100.0) & (FREQS < 16000.0)
    for az in (0.5, 30.5, 89.5, 150.5):
        got = bank.lookup([az])[0][:, sel]
        exact = ear_filters([az], **cues)[0][:, sel]
        assert np.max(np.abs(20.0 * np.log10(np.abs(got) / np.abs(exact)))) <= 0.5
        # Same phase up to 0.5 samples of delay at 1 kHz.
        k = int(np.argmin(np.abs(FREQS[sel] - 1000.0)))
        dphi = np.angle(got[:, k] / exact[:, k])
        assert np.all(np.abs(dphi) / (2 * np.pi * FREQS[sel][k]) * FS <= 0.5)


def test_look_yaw_turns_the_scene():
    x = np.stack([np.zeros(2 * FS), _pink(2 * FS, 9)])
    front = render_stereo(x, FS, profile="V1")
    turned = render_stereo(x, FS, profile=Profile("yaw", front_limit_deg=60.0, look_yaw_deg=45.0))
    ild = [10 * np.log10(np.sum(o[1] ** 2) / np.sum(o[0] ** 2)) for o in (front, turned)]
    assert ild[1] < ild[0] - 1.0  # head turned toward the source: it moves toward the centre
