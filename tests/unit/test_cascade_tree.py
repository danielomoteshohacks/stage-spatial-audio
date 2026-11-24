import numpy as np

from stage.groundtruth import make_object_song
from stage.separation.cascade.config import models, preset, usable
from stage.separation.cascade.tree import Cache, Cascade

SHORT = (("verse", 2, 0.55), ("chorus", 3, 1.0))


class OracleEngine:
    """Returns the true stem for whatever it is asked, to test the tree without a network."""

    def __init__(self, name, fn):
        self.name, self.fn, self.calls = name, fn, 0

    def separate(self, audio, sr):
        self.calls += 1
        return self.fn(audio)


def test_models_file_is_complete_and_licences_are_classified():
    ms = models()
    assert {"kim_mbr_vocals", "bs_rofo_sw", "drumsep_mdx23c", "anvuew_dereverb"} <= set(ms)
    for m in ms.values():
        assert m.licence and m.licence_class in ("open", "copyleft", "nc", "unverified")
        assert m.source.startswith("https://")
    assert ms["bs_rofo_sw"].licence_class == "unverified"
    assert usable(ms["bs_rofo_sw"])[0] is False  # off until the owner enables it
    assert usable(ms["bs_rofo_sw"], ("open", "copyleft", "nc", "unverified"))[0]
    assert usable(ms["kim_mbr_vocals"])[0]
    for p in ("best", "fast", "cpu"):
        assert preset(p)["levels"]


def test_cache_roundtrip_is_keyed_by_content(tmp_path):
    c = Cache(tmp_path)
    x = np.random.default_rng(0).standard_normal((2, 4410)).astype(np.float32) * 0.3
    k = Cache.key(x, "L1", ["a"])
    assert c.get(k) is None
    c.put(k, 44100, {"vocals": x})
    got = c.get(k)
    np.testing.assert_allclose(got["vocals"], x, atol=2e-7)
    assert Cache.key(x, "L1", ["b"]) != k
    assert Cache.key(x * 1.001, "L1", ["a"]) != k
    assert (c.hits, c.misses) == (1, 1)


def test_cascade_with_four_stem_fallback_reports_and_sums_to_the_mix(tmp_path):
    song = make_object_song(seed=0, bars=SHORT)
    sr = song.sample_rate
    a, b = int(2 * sr), int(10 * sr)
    mix = song.mix[:, a:b]
    st = {k: v[:, a:b] for k, v in song.four_stems().items()}
    casc = Cascade("cpu", cache_dir=tmp_path)
    res = casc.run(mix, sr, fallback_stems=st, refine=False)
    assert res.report["sum_error"] < 1e-3
    assert "lead" in res.leaves and "bass" in res.leaves and "kick" in res.leaves
    assert res.roles["kick"] == "kick" and res.roles["lead"] == "lead_vocal"
    assert all(0.0 <= q.score <= 100.0 for q in res.quality.values())
    assert res.report["levels"]["3"] == "fallback four-stem separator"
    assert "bs_rofo_sw" not in res.report["models"]


def test_level1_uses_injected_engine_and_caches_it(tmp_path):
    song = make_object_song(seed=0, bars=SHORT)
    sr = song.sample_rate
    mix = song.mix[:, int(2 * sr) : int(8 * sr)]
    voc = song.four_stems()["vocals"][:, int(2 * sr) : int(8 * sr)]
    eng = OracleEngine("kim", lambda audio: {"vocals": voc})
    casc = Cascade("fast", engines={"kim_mbr_vocals": eng}, cache_dir=tmp_path)
    v, inst = casc.level1(mix, sr, None)
    assert np.abs(v + inst - mix).max() < 1e-6 and eng.calls == 1
    casc2 = Cascade("fast", engines={"kim_mbr_vocals": eng}, cache_dir=tmp_path)
    casc2.level1(mix, sr, None)
    assert eng.calls == 1 and casc2.cache.hits == 1  # second run read the cache
    assert casc.report["models"]["kim_mbr_vocals"]["class"] == "open"


def test_unverified_model_is_skipped_with_a_reason():
    casc = Cascade("best", engines={"bs_rofo_sw": OracleEngine("sw", lambda a: {})})
    assert casc._engines_for(3) == [] or all(e.name != "sw" for e in casc._engines_for(3))
    assert any("unverified" in s for s in casc.report["skipped"])
