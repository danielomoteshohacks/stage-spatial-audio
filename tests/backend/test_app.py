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


def test_the_api_endpoints_are_process_rerender_and_v3(app):
    names = [d.api_name for d in app.demo.fns.values()
             if d.api_name and getattr(d, "api_visibility", "public") != "private"]
    assert names == ["process", "rerender", "v3_process", "v3_catalog"]


def test_profile_choices_cover_every_profile(app):
    from stage.engines import profile_names

    dropdowns = [b for b in app.demo.blocks.values() if isinstance(b, gr.Dropdown)
                 and b.label == "Profile"]
    choices = {c[0] if isinstance(c, tuple) else c for c in dropdowns[0].choices}
    assert choices == set(profile_names())


def test_without_spaces_the_separator_is_not_wrapped(app):
    if app.spaces is None:
        assert app.gpu_separate is app._separate


def test_process_streams_stages_and_ends_with_files(app, track):
    updates = list(app.process(str(track), "lite", "V0", 2.0, None, 1.0))
    assert len(updates) >= 3
    first, last = updates[0][0], updates[-1][0]
    assert first["done"] is False and last["done"] is True and last["error"] is None
    assert [s["status"] for s in last["stages"]] == ["ok", "skipped", "skipped", "ok", "ok", "ok",
                                                     "ok"]
    _, original, spatial, stems, run_json = updates[-1]
    assert Path(original).exists() and Path(spatial).exists() and stems is None
    assert json.loads(Path(run_json).read_text())["ok"] is True
    assert last["report"]["verdict"] in ("pass", "review", "fail")


def test_empty_and_zero_lengths(app, track):
    # Empty fields mean the defaults; a zero length is refused with a message, never rendered.
    *_, last = app.process(str(track), "lite", "V0", 2.0, "", "")
    assert last[0]["error"] is None and last[0]["run"]["input"]["start_mode"] == "auto"
    *_, last = app.process(str(track), "lite", "V0", 2.0, "", "0")
    assert "between" in last[0]["error"] and last[1:] == (None, None, None, None)


def test_start_and_length_fields_are_single_text_boxes(app):
    labels = [b.label for b in app.demo.blocks.values() if isinstance(b, gr.Textbox)]
    assert labels.count("Start (seconds)") == 1
    assert labels.count("Excerpt length (seconds)") == 1
    assert not [b for b in app.demo.blocks.values() if isinstance(b, gr.Number)]


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
        job = client.submit(gradio_client.handle_file(str(track)), "lite", "V0", 2.0, "", "1",
                            "auto", 0.5, "", False, "balanced", api_name="/process")
        progress, original, spatial, stems, run_json = job.result()
        assert progress["done"] and progress["run"]["ok"]
        assert len(job.outputs()) >= 3  # streamed updates, not one final answer
        assert sf.info(spatial).frames == sf.info(original).frames == 44100
        assert sf.info(spatial).subtype == "PCM_24"
    finally:
        app.demo.close()


def test_v2_process_then_rerender_from_the_cache(app, track, monkeypatch):
    *_, last = app.process(str(track), "lite", "space:studio", 2.0, "", "", "pop", 0.4, "",
                           True)
    progress = last[0]
    assert progress["error"] is None and progress["plan"]["genre"] == "pop"
    assert len(progress["track_id"]) == 24 and Path(progress["files"]["bed_7_1_4"]).exists()
    plan = progress["plan"]
    plan["space"] = "club"
    *_, again = app.rerender(progress["track_id"], "lite", "space:studio", 2.0, "", 0.4,
                             json.dumps(plan), False)
    assert again[0]["error"] is None and again[0]["plan"]["space"] == "club"
    assert "re-rendered from the track cache" in again[0]["notes"]


def test_rerender_of_an_unknown_track_is_a_message(app):
    *_, last = app.rerender("0" * 24, "lite", "space:studio", 2.0, "auto", 0.5, "", False)
    assert "expired" in last[0]["error"]


def test_v3_event_refuses_a_missing_file_and_bad_options(app):
    import json

    first = next(iter(app.v3_process(None)))
    assert json.loads(first)["error"] == "No file was uploaded."
    out = list(app.v3_process("/nonexistent.flac", '{"character": "wild"}'))
    assert "refused" in json.loads(out[0])["error"]


def test_the_combined_app_serves_gradio_and_the_v3_routes(app):
    from fastapi.testclient import TestClient

    client = TestClient(app.build_app())
    assert client.get("/v3/health").json()["engine"] == "soundstage-v3"
    assert client.get("/").status_code == 200
    r = client.options("/v3/health", headers={"Origin": "https://soundstage-phi.vercel.app",
                                              "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") in ("*", "https://soundstage-phi.vercel.app")


def test_ensure_routes_puts_missing_v3_routes_in_front(app):
    """The ZeroGPU launcher dropped the app_kwargs routes; ensure_routes must restore them so
    they match before Gradio's own catch-all pages."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    served = FastAPI()

    @served.get("/{rest:path}")
    def catch_all(rest: str) -> dict:
        return {"page": "gradio"}

    routes = [route for r in app._routers() for route in r.routes]
    added = app.ensure_routes(served, routes)
    assert added == len(routes)
    assert app.ensure_routes(served, routes) == 0  # idempotent
    body = TestClient(served).get("/v3/health").json()
    assert body["engine"] == "soundstage-v3"
