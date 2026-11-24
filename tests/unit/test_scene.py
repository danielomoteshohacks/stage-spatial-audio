"""The v2 scene: analysis, templates, plan, decorrelators, motion and the scene render."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from stage.guard.report import build_report
from stage.scene.analysis import analyse_song
from stage.scene.decorrelate import decorrelate, transient_gate, velvet_filter
from stage.scene.genre import template_scores
from stage.scene.plan import (
    MAX_DEG_PER_S,
    build_plan,
    cap_motion,
    plan_json,
    templates,
    validate_plan,
)
from stage.scene.render import BED_LAYOUT, motion_offsets, pan_bed, render_scene
from stage.spatial.neutral import split_low_high
from stage.testsongs import make_song

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas" / "plan.schema.json").read_text())
FS = 44100
GENRES = {"afrobeats", "amapiano", "hiphop", "rnb", "gospel", "house", "pop", "rock",
          "acoustic", "classical"}


@pytest.fixture(scope="module")
def song():
    return make_song(seed=3, tempo_bpm=118.0)


@pytest.fixture(scope="module")
def analysis(song):
    return analyse_song(song.mix, FS, song.stems)


def test_tempo_and_chorus_boundaries(song, analysis):
    assert analysis.tempo_bpm == pytest.approx(118.0, abs=1.0)
    choruses = [s for s in analysis.sections if s.label == "chorus"]
    truth = [b for label, b, _ in song.sections if label == "chorus"]
    # Every true chorus start is found within a bar.
    bar = 4 * 60 / 118.0
    for t in truth:
        assert min(abs(c.start_s - t) for c in choruses) < bar
    assert set(analysis.stem_activity) == {"vocals", "drums", "bass", "other"}


def test_every_genre_has_a_documented_template():
    t = templates()
    assert GENRES <= set(t)
    for name, tpl in t.items():
        assert len(tpl["why"]) > 60, name
        names = [o["name"] for o in tpl["objects"]]
        lead = next(o for o in tpl["objects"] if o["source"] == "vocals.direct")
        bass = next(o for o in tpl["objects"] if o["source"] == "bass.all")
        assert lead["protected"] and bass["protected"] and "motion" not in lead, name
        assert len(set(names)) == len(names)
        for o in tpl["objects"]:
            assert len(o["why"]) > 10, (name, o["name"])


def test_plan_is_valid_deterministic_and_protects_vocal_bass_and_kick(analysis):
    kw = dict(track_id="t", mode="stems", genre="afrobeats", space=None, motion_depth=1.0)
    a, b = build_plan(analysis, **kw), build_plan(analysis, **kw)
    assert plan_json(a) == plan_json(b)
    Draft202012Validator(SCHEMA).validate(a)
    validate_plan(a)
    for o in a["stems"]:
        if o["name"] in ("lead_vocal", "bass", "kit"):
            assert "motion" not in o
    moving = [o for o in a["stems"] if "motion" in o]
    assert moving and all(o["motion"]["max_deg_per_s"] <= MAX_DEG_PER_S for o in moving)


def test_motion_depth_zero_is_a_static_scene(analysis):
    plan = build_plan(analysis, track_id="t", mode="stems", genre="house", space="club",
                      motion_depth=0.0)
    assert not any("motion" in o for o in plan["stems"])


def test_speed_cap_lengthens_fast_paths():
    m = cap_motion({"path": "orbit", "period_bars": 1, "depth": 360}, 180.0, 1.0)
    assert m["max_deg_per_s"] <= MAX_DEG_PER_S and m["period_bars"] > 1


def test_motion_is_tempo_locked_and_smooth(analysis):
    plan = build_plan(analysis, track_id="t", mode="stems", genre="hiphop", space=None,
                      motion_depth=1.0)
    m = next(o["motion"] for o in plan["stems"] if "motion" in o)
    period = m["period_bars"] * 4 * 60 / plan["tempo_bpm"]
    t = np.linspace(0, 3 * period, 5000)
    off = motion_offsets(plan, m, t)
    assert np.allclose(motion_offsets(plan, m, t + period), off, atol=1e-6)
    speed = np.max(np.abs(np.diff(off) / np.diff(t)))
    assert speed <= MAX_DEG_PER_S + 1e-6


def test_validate_refuses_a_moving_protected_object(analysis):
    plan = build_plan(analysis, track_id="t", mode="stems", genre="pop", space=None,
                      motion_depth=0.5)
    bad = copy.deepcopy(plan)
    lead = next(o for o in bad["stems"] if o["name"] == "lead_vocal")
    lead["motion"] = {"path": "sway", "period_bars": 8, "depth": 30}
    with pytest.raises(ValueError, match="protected"):
        validate_plan(bad)


def test_velvet_decorrelators_are_flat_and_mutually_decorrelated():
    x = np.random.default_rng(0).standard_normal(5 * FS)
    a, b = decorrelate(x, 1, FS), decorrelate(x, 2, FS)
    r = np.corrcoef(a, b)[0, 1]
    assert abs(r) < 0.15
    h = velvet_filter(3, FS)
    mag = 20 * np.log10(np.abs(np.fft.rfft(h, 8192)) + 1e-12)
    smooth = np.convolve(mag, np.ones(200) / 200, mode="valid")
    # Broadly flat once smoothed over 1 kHz: a sparse 25 ms filter is not perfectly flat, and
    # the timbre matcher removes the residual tilt of the whole bed.
    assert np.ptp(smooth[50:-50]) < 8.0


def test_transient_gate_opens_on_clicks_only():
    x = 0.05 * np.sin(2 * np.pi * 300 * np.arange(2 * FS) / FS)
    x[FS] += 1.0
    g = transient_gate(x, FS)
    assert g[FS + 50] > 0.5 and g[FS // 2] < 0.05


def test_bed_panner_is_power_normalised_and_reaches_heights():
    for az, el in ((0, 0), (30, 0), (100, 0), (-150, 10), (45, 45), (180, 60)):
        g = pan_bed(az, el)
        assert sum(v * v for v in g.values()) == pytest.approx(1.0, abs=1e-6)
        assert all(k in BED_LAYOUT for k in g)
    assert set(pan_bed(45, 45)) <= {"Ltf", "Rtf", "Ltr", "Rtr"}


def test_genre_scores_map_audioset_labels_and_report_missing_ones():
    scores, missing = template_scores({"Afrobeat": 0.6, "House music": 0.2}, templates())
    assert scores["afrobeats"] == pytest.approx(0.6)
    assert "Amapiano" not in templates()["amapiano"]["audioset"]
    assert isinstance(missing["afrobeats"], list)


def test_scene_render_keeps_the_record(song):
    a0, a1 = 20 * FS, 32 * FS
    mix = song.mix[:, a0:a1]
    stems = {k: v[:, a0:a1] for k, v in song.stems.items()}
    plan = build_plan(analyse_song(mix, FS, stems), track_id="t", mode="stems",
                      genre="afrobeats", space="studio", motion_depth=1.0)
    res = render_scene(mix, FS, plan, stems, export_bed=True)
    low, _ = split_low_high(mix, FS)
    assert np.max(np.abs(sum(res.objects.values()) + low - res.binaural)) < 1e-9
    assert res.bed.shape == (12, mix.shape[1]) and res.info["moving_sources"] > 0
    r = build_report(mix, res.binaural, FS, {"engine": "test"})
    assert r["low_end"]["identity_corr"] > 0.99
    assert abs(r["loudness_lufs"]["render"] - r["loudness_lufs"]["original"]) < 0.1
    assert r["verdict"] in ("pass", "review") and not any(
        f["kind"] in ("clipping", "pre_echo") for f in r["artifact_flags"])
