import importlib.util
import json
from pathlib import Path

import soundfile as sf

from stage.catalogue.licences import Licence
from stage.catalogue.model import Track
from stage.groundtruth import make_object_song

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("render_catalogue",
                                              ROOT / "scripts" / "render_catalogue.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)


def test_curated_takes_the_first_of_each_shelf_without_repeats():
    seed = {"shelves": {"a": {"tracks": ["1", "2", "3"]}, "b": {"tracks": ["2", "4"]}}}
    assert rc.curated(seed, 2) == ["1", "2", "4"]
    assert rc.safe("jamendo:abc/def") == "jamendo_abc_def"


def test_a_track_is_rendered_with_its_licence_beside_it(tmp_path, monkeypatch):
    song = make_object_song(seed=5, bars=(("verse", 2, 0.55), ("chorus", 2, 1.0)))
    src = tmp_path / "src.flac"
    sf.write(str(src), song.mix.T, song.sample_rate, subtype="PCM_24")
    import shutil

    monkeypatch.setattr(rc, "download", lambda t, dest: shutil.copy(src, dest) and dest)
    monkeypatch.setattr(rc, "suffix_for", lambda t: ".flac")
    t = Track("jamendo:1", "Tune", "Ada", "https://prod-1.storage.jamendo.com/x",
              "https://www.jamendo.com/track/1", Licence("by-sa", "3.0"), "jamendo")
    out = tmp_path / "out"
    entry = rc.render_track(t, out, "cpu", provider=None)
    m = json.loads((out / entry["manifest"]).read_text())
    assert m["track"]["licence"]["code"] == "by-sa" and "same licence" in m["licence_note"]
    assert "Spatialised by SoundStage" in m["track"]["attribution"]
    assert m["segments"] and (out / m["files_base"] / m["segments"][0]["file"]).is_file()
    assert entry["verdict"] in ("pass", "review")
