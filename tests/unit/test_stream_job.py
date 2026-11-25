"""A whole-song job end to end on a generated song: chunks, segments, seams, guard, files."""

import json

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import correlate as fftcorrelate

from stage.groundtruth import make_object_song
from stage.stream import codec
from stage.stream.job import JobOptions, make_cascade_provider, new_job, run_job

SONG = (("verse", 3, 0.55), ("chorus", 4, 1.0), ("outro", 1, 0.3))


@pytest.fixture(scope="module")
def song_file(tmp_path_factory):
    song = make_object_song(seed=1, bars=SONG)
    p = tmp_path_factory.mktemp("song") / "song.flac"
    sf.write(str(p), song.mix.T, song.sample_rate, subtype="PCM_24")
    return song, p


def oracle_provider(song):
    from types import SimpleNamespace

    def separator(audio, sr):
        # The true four stems of the same song, found by position in time through the mix: the
        # chunks passed in are slices, so look the slice up by its first samples.
        n = audio.shape[1]
        full = song.mix
        key = audio[0, :4000].astype(np.float64)
        hay = full[0].astype(np.float64)
        # Exact slice search: minimise the squared difference, 2<h,k> - |h|^2 over windows.
        corr = fftcorrelate(hay, key, mode="valid", method="fft")
        c = np.concatenate([[0.0], np.cumsum(hay**2)])
        energy = c[len(key):] - c[: len(c) - len(key)]
        i = int(np.argmax(2.0 * corr - energy))
        four = song.four_stems()
        return SimpleNamespace(stems={k: v[:, i : i + n] for k, v in four.items()})

    return make_cascade_provider("cpu", {}, None, separator)


def test_a_whole_song_streams_in_chunks_and_the_segments_join(song_file, tmp_path):
    song, path = song_file
    job = new_job(tmp_path, JobOptions(preset="cpu", chunk_s=6.0, first_s=3.0, overlap_s=0.5))
    run_job(job, path, provider=oracle_provider(song))
    st = job.snapshot()
    assert st["status"] == "done", st.get("error")
    n = song.mix.shape[1]
    segs = st["segments"]
    assert len(segs) == st["chunks_total"] >= 3 and st["chunks_done"] == len(segs)
    # Segments are contiguous and cover the song.
    t = 0.0
    for s in segs:
        assert s["start_s"] == pytest.approx(t, abs=1e-3)
        t += s["duration_s"]
    assert t == pytest.approx(n / song.sample_rate, abs=2e-3)
    assert st["time_to_first_sound_s"] is not None
    # Decode, trim the context and join; compare with the full render the job wrote.
    parts = []
    for s in segs:
        y, sr = codec.decode((job.dir / "seg" / s["file"]).read_bytes())
        parts.append(y[:, s["pre"] : y.shape[1] - s["post"]])
    joined = np.concatenate(parts, axis=1)
    full, sr0 = sf.read(str(job.dir / "spatial.flac"), dtype="float32", always_2d=True)
    from math import gcd

    from scipy.signal import resample_poly
    g = gcd(48000, sr0)
    ref = resample_poly(full.T, 48000 // g, sr0 // g, axis=1)
    m = min(joined.shape[1], ref.shape[1])
    assert abs(joined.shape[1] - ref.shape[1]) <= len(segs) + 2

    def snr(x):
        r = ref[:, 3000 : m - 3000]
        return 10 * np.log10(np.sum(r**2) / np.sum((x[:, 3000 : m - 3000] - r) ** 2))

    # The same render encoded as one stream is the codec's own error; the segment-joined version
    # may not be worse than that by more than a decibel (the joints cost nothing audible).
    single, _ = codec.decode(codec.encode_segment(full.T, sr0, "opus").data)
    assert snr(joined) > snr(single[:, :m]) - 1.0, (snr(joined), snr(single[:, :m]))
    # Files and report.
    for f in ("spatial.flac", "plan.json", "report.json", "run.json"):
        assert (job.dir / f).is_file()
    run = json.loads((job.dir / "run.json").read_text())
    assert run["guard"]["verdict"] in ("pass", "review") and run["chunks"] == len(segs)
    plan = json.loads((job.dir / "plan.json").read_text())
    assert plan["version"] == 3 and plan["space"] == "dry_stage"


def test_a_bad_option_and_a_missing_file_fail_cleanly(tmp_path):
    with pytest.raises(ValueError):
        new_job(tmp_path, JobOptions(character="wild"))
    job = new_job(tmp_path, JobOptions())
    run_job(job, tmp_path / "nope.flac")
    st = job.snapshot()
    assert st["status"] == "failed" and st["done"] and st["error"]


def test_model_free_leaves_when_there_is_no_separator(song_file, tmp_path):
    song, path = song_file
    job = new_job(tmp_path, JobOptions(chunk_s=6.0, first_s=3.0, overlap_s=0.5, seconds=9.0))
    run_job(job, path)  # the default provider is the model-free decomposition
    st = job.snapshot()
    assert st["status"] == "done", st.get("error")
    assert st["run"]["providers"][0]["provider"].startswith("model-free")


def test_the_separator_runs_once_over_the_whole_song(song_file, tmp_path):
    """One GPU call per song: per-chunk calls each reserved quota on ZeroGPU and the job failed
    after two chunks once the quota ran out."""
    from types import SimpleNamespace

    song, path = song_file
    calls = []

    def separator(audio, sr):
        calls.append(audio.shape[1])
        return SimpleNamespace(stems=song.four_stems(), model="oracle")

    job = new_job(tmp_path, JobOptions(preset="cpu", chunk_s=6.0, first_s=3.0, overlap_s=0.5))
    run_job(job, path, provider=make_cascade_provider("cpu", {}, None, separator))
    st = job.snapshot()
    assert st["status"] == "done", st.get("error")
    assert calls == [song.mix.shape[1]]
    assert st["chunks_total"] >= 3


def test_a_failing_separator_still_renders_the_whole_song(song_file, tmp_path):
    """When separation fails (no quota, no model), every chunk uses the model-free leaves and no
    chunk loses its audio, even though those leaves have other names than a separator's."""
    song, path = song_file

    def separator(audio, sr):
        raise RuntimeError("ZeroGPU quota exceeded")

    job = new_job(tmp_path, JobOptions(preset="cpu", chunk_s=6.0, first_s=3.0, overlap_s=0.5))
    run_job(job, path, provider=make_cascade_provider("cpu", {}, None, separator))
    st = job.snapshot()
    assert st["status"] == "done", st.get("error")
    full, _ = sf.read(str(job.dir / "spatial.flac"), dtype="float32", always_2d=True)
    hop = full.shape[0] // 8
    rms = [float(np.sqrt(np.mean(full[i : i + hop] ** 2))) for i in range(0, hop * 8, hop)]
    assert min(rms[:-1]) > 1e-3, rms  # no silent stretch


def test_route_leaves_never_drops_a_leaf():
    from stage.stream.job import route_leaves

    plan = {"stems": [{"kind": "object", "leaf": "vocals", "role": "lead_vocal", "protected": True},
                      {"kind": "object", "leaf": "other", "role": "pad"}]}
    x = np.ones((2, 8), np.float32)
    out = route_leaves({"mystery_leaf": x, "vocals": x}, plan)
    assert set(out) == {"other", "vocals"}
