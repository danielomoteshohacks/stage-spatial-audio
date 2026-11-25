import pytest
import soundfile as sf

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from stage.catalogue.sources import Openverse  # noqa: E402
from stage.catalogue.store import Catalogue  # noqa: E402
from stage.groundtruth import make_object_song  # noqa: E402
from stage.server import catalog as catalog_mod  # noqa: E402
from stage.server.api import JobStore, create_router  # noqa: E402
from stage.server.catalog import create_catalog_router  # noqa: E402

REC = {"id": "t1", "title": "Tune", "creator": "Ada", "license": "by-sa", "license_version": "3.0",
       "source": "jamendo", "provider": "jamendo", "genres": ["gospel"], "duration": 200000,
       "url": "https://prod-1.storage.jamendo.com/?trackid=1&format=mp32",
       "foreign_landing_url": "https://www.jamendo.com/track/1", "thumbnail": "https://x/t/",
       "audio_set": {"title": "Alb"}}


def client(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_mod, "prerendered_index", lambda timeout=8.0: {"tracks": {}})
    cat = Catalogue(openverse=Openverse(fetch=lambda u: {"results": [REC]}),
                    seed={"shelves": {}, "tracks": {}})
    router, store = create_router(JobStore(tmp_path), background=True)
    app = FastAPI()
    app.include_router(router)
    app.include_router(create_catalog_router(cat, store, background=True))
    return TestClient(app), cat, store


def test_shelves_search_track_legal_and_unknowns(tmp_path, monkeypatch):
    c, cat, _ = client(tmp_path, monkeypatch)
    assert c.get("/catalog/shelves").json()["shelves"] == []
    r = c.get("/catalog/search", params={"q": "tune"}).json()
    assert r["tracks"][0]["id"] == "jamendo:t1"
    t = c.get("/catalog/track/jamendo:t1").json()
    assert t["licence"]["code"] == "by-sa" and "CC BY-SA" in t["attribution"]
    assert t["prerendered"] is None
    assert c.get("/catalog/track/nope:1").status_code == 404
    legal = c.get("/catalog/legal").json()
    assert "NoDerivatives" in legal["what"] and legal["tracks_listed"] == 1
    assert c.get("/catalog/genre/gospel").json()["key"] == "gospel"
    assert c.get("/catalog/genre/nonsense").status_code == 404
    assert c.get("/catalog/search", params={"q": "x" * 200}).status_code == 400
    assert c.get("/catalog/artist", params={"name": "Ada"}).json()["tracks"]


def test_the_audio_proxy_refuses_unlisted_tracks(tmp_path, monkeypatch):
    c, cat, _ = client(tmp_path, monkeypatch)
    assert c.get("/audio/jamendo:never").status_code == 404
    assert c.get("/audio/../../etc/passwd").status_code == 404


def test_render_from_the_catalogue_downloads_server_side(tmp_path, monkeypatch):
    song = make_object_song(seed=4, bars=(("verse", 2, 0.55), ("chorus", 2, 1.0)))
    src = tmp_path / "src.flac"
    sf.write(str(src), song.mix.T, song.sample_rate, subtype="PCM_24")
    c, cat, store = client(tmp_path, monkeypatch)
    c.get("/catalog/search", params={"q": "tune"})  # registers the track
    import shutil

    monkeypatch.setattr(catalog_mod, "download", lambda t, dest: shutil.copy(src, dest) and dest)
    monkeypatch.setattr(catalog_mod, "suffix_for", lambda t: ".flac")
    r = c.post("/v3/jobs/from-catalog", json={"id": "jamendo:t1", "options": {
        "chunk_s": 4, "first_s": 2.5, "overlap_s": 0.4}})
    assert r.status_code == 200, r.text
    import time

    jid = r.json()["id"]
    for _ in range(300):
        st = c.get(f"/v3/jobs/{jid}").json()
        if st["done"]:
            break
        time.sleep(0.3)
    assert st["status"] == "done", st.get("error")
    assert st["track"]["id"] == "jamendo:t1"
    assert c.post("/v3/jobs/from-catalog", json={"id": "x:y"}).status_code == 404
    assert c.post("/v3/jobs/from-catalog", json={"id": "jamendo:t1",
                                                  "options": {"fmt": "mp9"}}).status_code == 400
