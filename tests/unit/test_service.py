import json
import os
import shutil
import subprocess
import time

import numpy as np
import pytest
import soundfile as sf

from stage import service
from stage.service import (
    ServiceOptions,
    ValidationError,
    process_upload,
    resolve_excerpt,
    stream_process_upload,
    sweep_expired,
)


@pytest.fixture
def root(tmp_path):
    return tmp_path / "runs"


def test_lite_upload_returns_existing_outputs(track, root):
    res = process_upload(track, ServiceOptions(profile="V0", seconds=1.0), root=root)
    assert res.ok and res.spatial.exists() and res.original.exists() and res.run_json.exists()
    assert res.run_dir.parent == root
    assert json.loads(res.run_json.read_text())["mode"] == "lite"
    assert res.stems_spatial == {}
    assert res.expires_at > time.time()


def test_default_excerpt_moves_earlier_for_a_short_track(track, root):
    res = process_upload(track, ServiceOptions(profile="V0"), root=root)
    assert res.run["input"]["start_s"] == 0.0
    assert any("only 2.0 s long" in n for n in res.notes)


@pytest.mark.parametrize(
    "duration,start,seconds,expected",
    [
        (240.0, None, None, (30.0, 30.0)),  # the documented default
        (45.0, None, None, (15.0, 30.0)),  # moved earlier so 30 s still fits
        (240.0, 200.0, 60.0, (200.0, 40.0)),  # shortened at the end
        (20.0, None, 60.0, (0.0, 20.0)),
    ],
)
def test_resolve_excerpt(duration, start, seconds, expected):
    begin, length, _ = resolve_excerpt(duration, start, seconds)
    assert (begin, length) == pytest.approx(expected)


@pytest.mark.parametrize("start,seconds", [(300.0, 10.0), (-1.0, 10.0), (0.0, 0.5),
                                           (0.0, 500.0)])
def test_resolve_excerpt_rejects_bad_ranges(start, seconds):
    with pytest.raises(ValidationError):
        resolve_excerpt(240.0, start, seconds)


def test_unsupported_extension_is_refused_with_the_allowed_list(tmp_path, root):
    bad = tmp_path / "song.aiff"
    bad.write_bytes(b"0" * 100)
    with pytest.raises(ValidationError, match="wav, flac, mp3, ogg, m4a"):
        process_upload(bad, root=root)
    assert list(root.iterdir()) == []  # the refused run left nothing behind


def test_garbage_with_an_audio_extension_is_refused(tmp_path, root, monkeypatch):
    bad = tmp_path / "song.wav"
    bad.write_bytes(b"this is not audio" * 10)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ValidationError, match="cannot decode"):
        process_upload(bad, root=root)


def test_too_long_a_track_is_refused(tmp_path, root, monkeypatch):
    monkeypatch.setattr(service, "MAX_TRACK_S", 1.0)
    path = tmp_path / "long.flac"
    sf.write(str(path), np.zeros((44100 * 2, 2)), 44100, subtype="PCM_16")
    with pytest.raises(ValidationError, match="limit is 0 minutes|minutes long"):
        process_upload(path, root=root)


def test_bad_options_are_refused(track, root):
    for opts in (ServiceOptions(mode="atmos"), ServiceOptions(profile="V9"),
                 ServiceOptions(beta=0.5)):
        with pytest.raises(ValidationError):
            process_upload(track, opts, root=root)


def test_mp3_is_read(tmp_path, root):
    path = tmp_path / "clip.mp3"
    try:
        sf.write(str(path), 0.1 * np.random.default_rng(0).standard_normal((44100, 2)), 44100,
                 format="MP3")
    except Exception:
        pytest.skip("this libsndfile cannot write MP3")
    res = process_upload(path, ServiceOptions(profile="V0", seconds=1.0), root=root)
    assert res.ok


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_m4a_is_decoded_with_ffmpeg(track, tmp_path, root):
    path = tmp_path / "clip.m4a"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(track), "-c:a", "aac",
                    str(path)], check=True)
    res = process_upload(path, ServiceOptions(profile="V0", seconds=1.0), root=root)
    assert res.ok and any("ffmpeg" in n for n in res.notes)
    assert not (res.run_dir / "decoded.flac").exists()


def test_stems_upload_with_an_injected_separator(track, root, fake_separator):
    res = process_upload(track, ServiceOptions(mode="stems", profile="V0", seconds=1.0),
                         separator=fake_separator, root=root)
    assert res.run["mode"] == "stems"
    assert sorted(res.stems_spatial) == ["bass", "drums", "other", "vocals"]
    assert all(p.exists() for p in res.stems_spatial.values())


def test_sweep_deletes_only_expired_runs(root):
    root.mkdir()
    old, new = root / "old", root / "new"
    old.mkdir()
    new.mkdir()
    (old / "spatial.flac").write_bytes(b"x")
    past = time.time() - 3600
    os.utime(old, (past, past))
    removed = sweep_expired(root, ttl_s=60)
    assert removed == [old] and not old.exists() and new.exists()


def test_each_upload_sweeps_expired_runs_first(track, root):
    first = process_upload(track, ServiceOptions(profile="V0", seconds=1.0), root=root)
    past = time.time() - 7200
    os.utime(first.run_dir, (past, past))
    process_upload(track, ServiceOptions(profile="V0", seconds=1.0), root=root, ttl_s=60)
    assert not first.run_dir.exists()


def test_stream_yields_stage_events_then_the_result(track, root):
    events = list(stream_process_upload(track, ServiceOptions(profile="V0", seconds=1.0),
                                        root=root))
    kinds = [e["type"] for e in events]
    assert kinds[-1] == "result" and kinds.count("result") == 1
    stages = [(e["stage"], e["status"]) for e in events if e["type"] == "stage"]
    assert stages[0] == ("load", "running") and stages[-1] == ("write", "ok")
    assert events[-1]["result"].ok


def test_stream_turns_a_validation_error_into_an_error_event(tmp_path, root):
    bad = tmp_path / "x.txt"
    bad.write_text("hello")
    events = list(stream_process_upload(bad, root=root))
    assert events == [{"type": "error", "message": events[0]["message"]}]
    assert "not supported" in events[0]["message"]
