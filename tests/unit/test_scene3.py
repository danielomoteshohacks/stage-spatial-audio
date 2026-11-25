"""The v3 object scene: placement from data, events, paths, and the renderer's invariants."""

from pathlib import Path

import numpy as np
import pytest

from stage.groundtruth import make_object_song
from stage.guard.report import build_report
from stage.metrics.spatial import diagnose, direction_map, sector_shares
from stage.scene.analysis import analyse_song
from stage.scene3.events import (
    cap_keys,
    eased_path,
    peak_speed,
    smoothstep,
)
from stage.scene3.plan import (
    build_plan_v3,
    infer_role,
    object_paths,
    place,
    roles_config,
    side_of,
)
from stage.scene3.render import (
    DIRECTIONAL_MAX_DB,
    directional_curve_db,
    openness_at,
    render_v3,
)

SHORT = (("verse", 3, 0.55), ("chorus", 3, 1.0))


@pytest.fixture(scope="module")
def scene():
    song = make_object_song(seed=0, bars=SHORT)
    sr = song.sample_rate
    a, b = int(1 * sr), int(11 * sr)
    mix = song.mix[:, a:b]
    leaves = {k: v[:, a:b] for k, v in song.stereo.items()}
    an = analyse_song(mix, sr, {k: v[:, a:b] for k, v in song.four_stems().items()})
    plan = build_plan_v3(an, leaves, sr, track_id="t", genre="pop", motion_depth=0.5)
    return song, mix, leaves, an, plan, sr


def test_roles_come_from_data_and_names_map_to_roles():
    cfg = roles_config()
    assert {"lead_vocal", "kick", "snare", "bass", "cymbals", "toms", "guitar", "pad", "fx"} <= set(
        cfg["roles"])
    assert infer_role("backing_left") == "backing_vocal" and infer_role("hats") == "cymbals"
    assert infer_role("other_right") == "other" and infer_role("guitar_r") == "guitar"
    assert side_of("guitar_left") == 1 and side_of("pad_r") == -1 and side_of("kick") == 0


def test_lead_is_front_raised_and_anchors_never_move(scene):
    *_, plan, _ = scene
    objs = {o["name"]: o for o in plan["stems"]}
    lead = objs["lead_vocal"]
    assert lead["az"] == 0.0 and 5.0 <= lead["el"] <= 10.0 and lead["protected"]
    for k in ("lead_vocal", "kick", "snare", "bass"):
        assert objs[k]["protected"] and objs[k]["events"] == [] and not objs[k]["breathes"]
        assert abs(objs[k]["az"]) < 1e-9
    assert objs["hats"]["el"] >= 30.0 and objs["hats"]["role"] == "cymbals"
    assert objs["pad_l"]["az"] > 100.0 and objs["pad_r"]["az"] < -100.0
    assert objs["pad_l"]["el"] >= 20.0
    assert objs["guitar_l"]["az"] > 60.0 and objs["guitar_r"]["az"] < -60.0
    assert objs["backing_l"]["az"] > 80.0 and objs["backing_l"]["el"] > 0.0
    assert all(abs(o["az"]) <= 170.0 for o in plan["stems"])


def test_genres_scale_the_stage_from_data():
    cfg = roles_config()
    from stage.scene.plan import get_template
    pop = get_template("pop")["v3"]
    classical = get_template("classical")["v3"]
    hip = get_template("hiphop")["v3"]
    a = place("guitar_left", "guitar", cfg, pop, "balanced")["az"]
    b = place("guitar_left", "guitar", cfg, hip, "balanced")["az"]
    assert b < a  # hip-hop's stage is narrower
    pad_pop = place("pad_left", "pad", cfg, pop, "balanced")["el"]
    pad_cl = place("pad_left", "pad", cfg, classical, "balanced")["el"]
    assert pad_cl < pad_pop  # classical has little height
    wide = place("guitar_left", "guitar", cfg, pop, "immersive")["az"]
    narrow = place("guitar_left", "guitar", cfg, pop, "intimate")["az"]
    assert narrow < a < wide
    for g in ("afrobeats", "amapiano", "hiphop", "rnb", "gospel", "house", "pop", "rock",
              "acoustic", "classical"):
        assert get_template(g)["v3"]["space"] == "dry_stage"


def test_plan_is_deterministic_and_json_serialisable(scene):
    import json
    song, mix, leaves, an, plan, sr = scene
    again = build_plan_v3(an, leaves, sr, track_id="t", genre="pop", motion_depth=0.5)
    assert json.dumps(plan, sort_keys=True) == json.dumps(again, sort_keys=True)
    assert plan["version"] == 3 and plan["space"] == "dry_stage"
    for o in plan["stems"]:
        total = sum(f["weight"] for f in o["energy_feeds"])
        assert abs(total - 1.0) < 0.02 or o["kind"] == "return"
        assert all(f["direct"] + f["early"] <= 1.0 + 1e-6 for f in o["energy_feeds"])


def test_eased_paths_and_caps():
    k = [[0.0, 0.0], [1.0, 60.0], [2.0, -60.0], [3.0, 0.0]]
    t = np.array([-1.0, 0.0, 1.0, 1.5, 2.0, 5.0])
    np.testing.assert_allclose(eased_path(k, t), [0, 0, 60, 0, -60, 0], atol=1e-9)
    assert smoothstep(np.array([0.5]))[0] == pytest.approx(0.5)
    capped = cap_keys(k, max_speed=90.0, max_range=100.0)
    assert peak_speed(capped) <= 90.0 + 1e-6
    assert max(abs(v) for _, v in capped) <= 100.0
    # Timing is never changed, only amplitude.
    assert [t for t, _ in capped] == [t for t, _ in k]


def test_breathing_opens_in_loud_sections_and_never_moves_protected(scene):
    *_, plan, sr = scene
    plan = {**plan, "sections": [
        {"start_s": 0.0, "end_s": 10.0, "label": "verse", "openness": 0.2},
        {"start_s": 10.0, "end_s": 20.0, "label": "chorus", "openness": 0.95}]}
    objs = {o["name"]: o for o in plan["stems"]}
    t = np.linspace(0, 19.9, 200)
    op = openness_at(plan, t)
    az, el = object_paths(objs["pad_l"], plan, t, op)[0]
    assert az[np.argmax(op)] > az[np.argmin(op)]  # wider when more open
    assert np.ptp(az) > 5.0
    kaz, kel = object_paths(objs["kick"], plan, t, op)[0]
    assert np.ptp(kaz) == 0.0 and np.ptp(kel) == 0.0


def test_directional_boost_is_bounded_and_directional():
    f = np.fft.rfftfreq(512, 1 / 44100)
    for az, el in ((0, 0), (0, 60), (180, 0), (90, 30), (-120, 40)):
        c = directional_curve_db(f, az, el, DIRECTIONAL_MAX_DB)
        assert c.min() >= 0.0 and c.max() <= DIRECTIONAL_MAX_DB + 1e-9
    up = directional_curve_db(f, 0, 60, 2.0)
    assert up[np.argmin(np.abs(f - 8500))] > up[np.argmin(np.abs(f - 500))]
    assert directional_curve_db(f, 90, 0, 2.0).max() < 0.1  # the side has no band


def test_render_invariants_dry_objects_sum_guard_and_direction(scene):
    song, mix, leaves, an, plan, sr = scene
    res = render_v3(mix, sr, plan, leaves)
    assert res.binaural.shape == mix.shape and np.isfinite(res.binaural).all()
    assert res.info["late_field"] is False and res.info["space"] == "dry_stage"
    rep = build_report(mix, res.binaural, sr, {"engine": "v3"})
    assert rep["verdict"] == "pass", rep
    assert rep["low_end"]["identity_corr"] > 0.999
    # The object stems and the low band add up to the render.
    from stage.scene3.fastdsp import fast_split
    low, _ = fast_split(mix, sr, plan["crossover_hz"])
    np.testing.assert_allclose(sum(res.objects.values()) + low, res.binaural, atol=2e-3)
    # Direction: the left-panned guitar is louder in the left ear, the right one in the right.
    gl, gr = res.objects["guitar_l"], res.objects["guitar_r"]
    assert np.sum(gl[0] ** 2) > 1.5 * np.sum(gl[1] ** 2)
    assert np.sum(gr[1] ** 2) > 1.5 * np.sum(gr[0] ** 2)
    d = diagnose(plan, res.objects, res.binaural, sr)
    assert d["late_energy_share"] == 0.0 and d["sectors"]["outside_front_az"] > 0.25
    assert d["sectors"]["height"] > 0.03 and d["drr_db_median"] > 10.0


def test_v3_puts_more_energy_outside_the_front_than_v2_on_the_same_song(scene):
    from stage.scene.plan import build_plan
    from stage.scene.render import render_scene
    song, mix, leaves, an, plan3, sr = scene
    four = {k: v[:, int(1 * sr) : int(11 * sr)] for k, v in song.four_stems().items()}
    plan2 = build_plan(analyse_song(mix, sr, four), track_id="t", mode="stems", genre="pop",
                       space="living_room", motion_depth=0.5)
    plan2["analysis_sample_rate"] = sr
    r2 = render_scene(mix, sr, plan2, four)
    r3 = render_v3(mix, sr, plan3, leaves)
    s2 = sector_shares(direction_map(plan2, r2.objects, sr))
    s3 = sector_shares(direction_map(plan3, r3.objects, sr))
    assert s3["outside_front_az"] > 2.0 * s2["outside_front_az"]
    assert s3["height"] > s2["height"] + 0.03


def test_a_real_plan_validates_against_the_v3_schema(scene):
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator

    schema = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "plan3.schema.json")
                        .read_text())
    *_, plan, _ = scene
    Draft202012Validator(schema).validate(json.loads(json.dumps(plan)))


def test_events_from_a_riser_a_tom_fill_and_a_throw():
    from stage.scene3.events import detect_events

    sr = 22050
    rng = np.random.default_rng(0)
    n = 24 * sr
    t = np.arange(n) / sr
    fx = np.zeros((2, n))
    # A riser from 4 s to 8 s (noise whose level grows 30 dB) and a short throw at 16 s.
    seg = slice(4 * sr, 8 * sr)
    fx[:, seg] = rng.standard_normal((2, 4 * sr)) * 10 ** (np.linspace(-40, -8, 4 * sr) / 20)
    fx[:, 16 * sr : 16 * sr + sr] = rng.standard_normal((2, sr)) * 0.2 * np.hanning(sr)
    toms = np.zeros((2, n))
    for k in range(8):
        o = int((12 + 0.15 * k) * sr)
        toms[:, o : o + 2000] += 0.4 * np.sin(2 * np.pi * 150 * t[:2000]) * np.exp(-t[:2000] * 20)
    beats = list(np.arange(0, 24, 0.5))
    ev = detect_events({"fx": fx, "toms": toms}, sr, beats, [8.0], 120.0,
                       {"fx": "fx", "toms": "toms"})
    kinds = [e["type"] for e in ev]
    assert "riser" in kinds and "lift" in kinds and "fill" in kinds and "throw" in kinds
    riser = next(e for e in ev if e["type"] == "riser")
    assert 3.0 <= riser["t0"] <= 5.0 and 7.0 <= riser["t1"] <= 9.0
    assert max(v for _, v in riser["el"]) > 5.0
    for e in ev:  # every move is capped in speed and range, and lands on the beat grid
        for ax in ("az", "el"):
            assert peak_speed(e[ax]) <= 90.0 + 1e-6
            assert max(abs(v) for _, v in e[ax]) <= 100.0
    fill = next(e for e in ev if e["type"] == "fill")
    az = [v for _, v in fill["az"]]
    assert max(az) > 0 > min(az)  # sweeps from one side to the other


def test_returns_are_diffuse_behind_and_above_and_keep_their_level(scene):
    song, mix, leaves, an, plan, sr = scene
    rng = np.random.default_rng(1)
    ret = {"lead": rng.standard_normal(mix.shape) * 0.02}
    plan_r = build_plan_v3(an, {**leaves, "lead": leaves["lead_vocal"] * 0.5}, sr, track_id="t",
                           genre="pop", returns=ret)
    rets = [o for o in plan_r["stems"] if o["kind"] == "return"]
    assert len(rets) == 1 and rets[0]["role"] == "return"
    assert all(abs(f["az"]) >= 45.0 for f in rets[0]["feeds"])  # nothing from the front
    assert abs(sum(f["weight"] for f in rets[0]["feeds"]) - 1.0) < 1e-6
    res = render_v3(mix, sr, plan_r, {**leaves, "lead": leaves["lead_vocal"] * 0.5},
                    returns=ret)
    y = res.objects["lead~return"]
    from scipy.signal import butter, sosfilt
    hp = sosfilt(butter(2, 200, "highpass", fs=sr, output="sos"), ret["lead"], axis=-1)
    ratio = float(np.sum(y**2) / np.sum(hp**2))
    assert 0.35 < ratio < 2.5  # at its original level, to within the head filters and the match
    d = diagnose(plan_r, res.objects, res.binaural, sr)
    assert d["late_energy_share"] > 0.0  # the record's own reverb counts as late energy


def test_head_selection_picks_the_head_with_the_smaller_error_and_fewer_confusions():
    from stage.spatial.heads import (
        Trial,
        angular_error_deg,
        is_front_back_confusion,
        score_trials,
        select_head,
    )

    assert angular_error_deg(0, 0, 90, 0) == pytest.approx(90)
    # A source at 30 degrees in front answered as 150 degrees behind is a front-back confusion;
    # a plain 20 degree miss is not; a source at the side cannot be confused.
    assert is_front_back_confusion(30.0, 150.0)
    assert not is_front_back_confusion(30.0, 50.0)
    assert not is_front_back_confusion(90.0, 90.0)
    good = [Trial(a, 0, a + 8, 0) for a in (-120, -60, 30, 150)]
    bad = [Trial(a, 0, 180 - a, 0) for a in (-120, -60, 30, 150)]
    assert score_trials(good)["front_back_rate"] == 0.0
    assert score_trials(bad)["front_back_rate"] == 1.0
    best, scores = select_head({"D1": bad, "H3": good, "D2": bad})
    assert best == "H3" and scores["H3"]["mean_error_deg"] < scores["D1"]["mean_error_deg"]
    # With identical results the default head wins.
    assert select_head({"H3": good, "D1": good})[0] == "D1"


def test_an_unavailable_head_falls_back_to_the_default_pack(monkeypatch):
    from stage.spatial import heads
    from stage.spatial.hrtf import get_hrtf

    # Whatever heads this machine has downloaded, pretend this one is absent: the test is about
    # the fallback, and a laptop that has run the Space has every head cached.
    monkeypatch.setattr(heads, "pack_path", lambda head: Path("/nonexistent") / f"{head}.npz")
    a = get_hrtf(44100)
    b = get_hrtf(44100, head="H7")
    assert a is b


def test_two_clusters_on_one_side_keep_distinct_leaves():
    assert side_of("other_left2") == 1 and side_of("other_right3") == -1
    assert infer_role("other_left2") == "other"


def test_fast_building_blocks_match_the_originals():
    from scipy.signal import oaconvolve

    from stage.scene3.fastconv import convolve_feeds
    from stage.scene3.fastdsp import fast_match_loudness, fast_split
    from stage.spatial.neutral import match_loudness_upper, split_low_high

    rng = np.random.default_rng(0)
    sr, n = 22050, 22050 * 4
    sigs = [rng.standard_normal(n).astype(np.float32) for _ in range(4)]
    fil = [rng.standard_normal((2, 900)).astype(np.float32) * 0.05 for _ in range(4)]
    ref = sum(oaconvolve(s[None], f, axes=-1) for s, f in zip(sigs, fil, strict=True))
    got = convolve_feeds(sigs, list(range(4)), fil, n)
    np.testing.assert_allclose(got, ref, atol=1e-3)
    each = convolve_feeds(sigs, list(range(4)), fil, n, per_feed=True)
    np.testing.assert_allclose(sum(each), ref, atol=1e-3)
    x = np.cumsum(rng.standard_normal((2, n)), axis=1) * 0.01 + rng.standard_normal((2, n)) * 0.05
    low, high = split_low_high(x, sr, 120.0)
    lo2, hi2 = fast_split(x, sr, 120.0)
    inner = slice(sr, -sr)
    assert np.abs(low - lo2)[:, inner].max() < 1e-4 * np.abs(low).max()
    np.testing.assert_allclose(lo2 + hi2, x, atol=1e-5)
    up = high * 0.7 + rng.standard_normal((2, n)) * 0.01
    g1 = match_loudness_upper(x, low, up, sr)[1]
    g2 = fast_match_loudness(x, low, up, sr)[1]
    assert g2 == pytest.approx(g1, rel=1e-3)
