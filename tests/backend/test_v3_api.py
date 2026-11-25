"""The v3 HTTP routes, driven through FastAPI's test client with a small generated song."""

import time

import pytest
import soundfile as sf

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("multipart")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from stage.groundtruth import make_object_song  # noqa: E402
from stage.server.api import JobStore, create_router  # noqa: E402


@pytest.fixture(scope="module")
def song_file(tmp_path_factory):
    song = make_object_song(seed=3, bars=(("verse", 2, 0.55), ("chorus", 3, 1.0)))
    p = tmp_path_factory.mktemp("s") / "s.flac"
    sf.write(str(p), song.mix.T, song.sample_rate, subtype="PCM_24")
    return p


def make_client(tmp_path):
    router, store = create_router(JobStore(tmp_path))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), store


def wait(client, jid, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get(f"/v3/jobs/{jid}").json()
        if st["done"]:
            return st
        time.sleep(0.3)
    raise AssertionError("job did not finish")


def test_health_lists_formats(tmp_path):
    c, _ = make_client(tmp_path)
    h = c.get("/v3/health").json()
    assert h["engine"] == "soundstage-v3" and "opus" in h["formats"]


def test_upload_stream_segments_and_files(song_file, tmp_path):
    c, _ = make_client(tmp_path)
    with open(song_file, "rb") as fh:
        r = c.post("/v3/jobs", files={"file": ("s.flac", fh, "audio/flac")},
                   data={"options": '{"chunk_s": 5, "first_s": 3, "overlap_s": 0.5}'})
    assert r.status_code == 200
    jid = r.json()["id"]
    st = wait(c, jid)
    assert st["status"] == "done", st.get("error")
    assert st["chunks_done"] == st["chunks_total"] == len(st["segments"]) >= 2
    seg = st["segments"][0]
    got = c.get(f"/v3/jobs/{jid}/seg/{seg['file']}")
    assert got.status_code == 200 and got.headers["content-type"].startswith("audio/ogg")
    assert len(got.content) == seg["bytes"]
    for name in ("spatial.flac", "plan.json", "report.json", "run.json"):
        assert c.get(f"/v3/jobs/{jid}/file/{name}").status_code == 200
    assert c.get(f"/v3/jobs/{jid}/file/../../etc/passwd").status_code == 404
    assert c.get(f"/v3/jobs/{jid}/seg/..%2Fx").status_code in (404, 422)
    assert c.get("/v3/jobs/nope").status_code == 404


def test_bad_upload_and_bad_options_are_refused(tmp_path):
    c, _ = make_client(tmp_path)
    r = c.post("/v3/jobs", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400 and "supported" in r.json()["detail"]
    r = c.post("/v3/jobs", files={"file": ("x.wav", b"RIFF", "audio/wav")},
               data={"options": '{"preset": "fast", "nonsense": 1}'})
    assert r.status_code == 400
    r = c.post("/v3/jobs", files={"file": ("x.wav", b"", "audio/wav")},
               data={"options": '{"character": "wild"}'})
    assert r.status_code == 400


def test_bench_reports_real_time_factors(tmp_path):
    c, _ = make_client(tmp_path)
    r = c.get("/v3/bench", params={"seconds": 4}).json()
    assert len(r["rows"]) == 4 and all(row["rtf"] > 0 for row in r["rows"])
    assert r["rows"][1]["run"] == "warm" and "convolve" in r["rows"][0]["stages"]
