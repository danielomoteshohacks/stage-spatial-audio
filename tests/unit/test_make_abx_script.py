import csv
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

_path = Path(__file__).resolve().parents[2] / "scripts" / "make_abx.py"
_spec = importlib.util.spec_from_file_location("make_abx", _path)
make_abx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_abx)


def test_equalise_matches_rms_and_shares_one_peak_gain():
    rng = np.random.default_rng(0)
    renders = {"a": rng.standard_normal((2, 4000)), "b": 0.1 * rng.standard_normal((2, 4000))}
    out = make_abx.equalise(renders, 0.5)
    levels = [make_abx.rms(v) for v in out.values()]
    assert abs(levels[0] - levels[1]) < 1e-12  # equal loudness even after peak safety
    assert max(np.max(np.abs(v)) for v in out.values()) <= make_abx.PEAK_CEILING + 1e-12


def test_shuffle_is_a_permutation_and_decodes_back():
    names = ["V0", "V1", "V2", "V3", "V4", "V5"]
    key = make_abx.shuffle_assignment(names, np.random.default_rng(3))
    assert sorted(key) == ["01", "02", "03", "04", "05", "06"]
    assert sorted(key.values()) == names
    order = ["6", "2", "3", "1", "5", "4"]
    assert make_abx.decode_ranking(order, key) == [key[f"0{o}"] for o in order]


@pytest.mark.parametrize("order", [["1", "2"], ["1", "1", "2", "3", "4", "5"], ["7", "1"]])
def test_incomplete_or_repeated_ranking_is_rejected(order):
    key = {f"0{i}": f"V{i}" for i in range(1, 7)}
    with pytest.raises(ValueError):
        make_abx.decode_ranking(order, key)


def test_render_then_rank_end_to_end(tmp_path):
    rng = np.random.default_rng(1)
    clip = tmp_path / "clip.wav"  # synthetic noise, written to a temporary folder only
    sf.write(str(clip), 0.1 * rng.standard_normal((44100, 2)), 44100, subtype="PCM_24")
    session = tmp_path / "abx"
    make_abx.main(["render", str(clip), "--seconds", "1", "--profiles", "V0", "V1", "V3",
                   "--out-dir", str(session), "--seed", "7"])
    meta = json.loads((session / "key.json").read_text(encoding="utf-8"))
    assert sorted(meta["files"].values()) == ["V0", "V1", "V3"]
    levels = [make_abx.rms(sf.read(str(session / f"{n}.wav"))[0]) for n in meta["files"]]
    assert max(levels) - min(levels) < 1e-4  # 24-bit rounding only

    results = tmp_path / "results.csv"
    make_abx.main(["rank", "--session", str(session), "--listener", "L01", "--order", "2 3 1",
                   "--outside", "2", "--natural", "1", "--results", str(results)])
    make_abx.main(["rank", "--session", str(session), "--listener", "L02", "--order", "1,2,3",
                   "--outside", "3", "--natural", "3", "--results", str(results)])
    rows = list(csv.DictReader(results.open(encoding="utf-8")))
    assert [r["listener"] for r in rows] == ["L01", "L02"]
    key = meta["files"]
    assert rows[0]["ranking_best_to_worst"] == ">".join([key["02"], key["03"], key["01"]])
    assert rows[0]["most_outside_head"] == key["02"]
    assert rows[1]["most_natural"] == key["03"]
