"""The Gradio adapter in space/app.py. Skipped where gradio is not installed (the python CI job)."""

import importlib.util
import json
from pathlib import Path

import pytest
import soundfile as sf

gr = pytest.importorskip("gradio")
gradio_client = pytest.importorskip("gradio_client")

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def app():
    spec = importlib.util.spec_from_file_location("soundstage_space_app", ROOT / "space" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_only_api_endpoint_is_process(app):
    names = [d.api_name for d in app.demo.fns.values()
             if d.api_name and getattr(d, "api_visibility", "public") != "private"]
    assert names == ["process"]


def test_profile_choices_cover_every_profile(app):
    from stage.render.profiles import PROFILES

    dropdowns = [b for b in app.demo.blocks.values() if isinstance(b, gr.Dropdown)]
    choices = {c[0] if isinstance(c, tuple) else c for c in dropdowns[0].choices}
    assert choices == set(PROFILES)


def test_without_spaces_the_separator_is_not_wrapped(app):
    if app.spaces is None:
        assert app.gpu_separate is app._separate


def test_process_streams_stages_and_ends_with_files(app, track):
    updates = list(app.process(str(track), "lite", "V0", 2.0, None, 1.0))
    assert len(updates) >= 3
    first, last = updates[0][0], updates[-1][0]
    assert first["done"] is False and last["done"] is True and last["error"] is None
    assert [s["status"] for s in last["stages"]] == ["ok", "skipped", "ok", "ok", "ok"]
    _, original, spatial, stems, run_json = updates[-1]
    assert Path(original).exists() and Path(spatial).exists() and stems is None
    assert json.loads(Path(run_json).read_text())["ok"] is True


def test_process_stems_with_a_fake_separator_returns_four_stem_files(app, track, fake_separator,
                                                                    monkeypatch):
    monkeypatch.setattr(app, "gpu_separate", fake_separator)
    *_, last = app.process(str(track), "stems", "V0", 2.0, None, 1.0)
    stems = last[3]
    assert sorted(Path(p).name for p in stems) == ["bass.flac", "drums.flac", "other.flac",
                                                   "vocals.flac"]
    assert last[0]["run"]["mode"] == "stems"


def test_a_refused_upload_is_reported_not_raised(app, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("not audio")
    *_, last = app.process(str(bad), "lite", "max", 2.0, None, None)
    assert last[0]["done"] is True and "not supported" in last[0]["error"]
    assert last[1:] == (None, None, None, None)


def test_endpoint_through_gradio_client(app, track):
    app.demo.launch(prevent_thread_lock=True, server_name="127.0.0.1", quiet=True,
                    allowed_paths=[str(app.WORK_ROOT)])
    try:
        client = gradio_client.Client(app.demo.local_url, verbose=False)
        job = client.submit(gradio_client.handle_file(str(track)), "lite", "V0", 2.0, None, 1.0,
                            api_name="/process")
        progress, original, spatial, stems, run_json = job.result()
        assert progress["done"] and progress["run"]["ok"]
        assert len(job.outputs()) >= 3  # streamed updates, not one final answer
        assert sf.info(spatial).frames == sf.info(original).frames == 44100
        assert sf.info(spatial).subtype == "PCM_24"
    finally:
        app.demo.close()
