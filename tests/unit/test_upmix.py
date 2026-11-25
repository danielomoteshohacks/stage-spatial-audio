"""Decision 0031: parts keep their stereo width and the render is never narrower than the record."""

import numpy as np
from scipy.signal import butter, sosfiltfilt

from stage.spatial.upmix import centre_sides, width_ratio

SR = 44100


def _three_sources():
    t = np.arange(SR * 3) / SR
    rng = np.random.default_rng(0)
    centre = np.sin(2 * np.pi * 440 * t)
    left = 0.3 * rng.standard_normal(t.size)
    right = 0.5 * np.sin(2 * np.pi * 660 * t)
    return centre, left, right, np.stack([centre + left, centre + right])


def test_centre_and_sides_rebuild_the_part_exactly():
    *_, x = _three_sources()
    p = centre_sides(x, SR)
    assert np.max(np.abs(np.stack([p["C"] + p["Ls"], p["C"] + p["Rs"]]) - x)) < 1e-5


def test_centre_and_sides_find_where_each_source_was_panned():
    centre, left, right, x = _three_sources()
    p = centre_sides(x, SR)
    corr = lambda u, v: float(np.dot(u, v) / np.sqrt(np.dot(u, u) * np.dot(v, v)))  # noqa: E731
    assert corr(p["C"], centre) > 0.99
    assert corr(p["Ls"], left) > 0.99
    assert corr(p["Rs"], right) > 0.99


def test_the_render_is_not_narrower_than_the_record(tmp_path):
    """v3 measured a side-to-mid ratio of 0.06 against the record's 0.27 (it sounded mono)."""
    from types import SimpleNamespace

    import soundfile as sf

    from stage.groundtruth import make_object_song
    from stage.stream.job import JobOptions, make_cascade_provider, new_job, run_job

    song = make_object_song(seed=2, bars=(("verse", 2, 0.6), ("chorus", 2, 1.0)))
    path = tmp_path / "s.flac"
    sf.write(str(path), song.mix.T, song.sample_rate, subtype="PCM_24")
    sep = lambda a, sr: SimpleNamespace(stems=song.four_stems(), model="oracle")  # noqa: E731
    job = new_job(tmp_path, JobOptions(preset="cpu"))
    run_job(job, path, provider=make_cascade_provider("cpu", {}, None, sep))
    assert job.snapshot()["status"] == "done"
    y, sr = sf.read(str(job.dir / "spatial.flac"), always_2d=True)
    sos = butter(4, [300, 8000], btype="band", fs=sr, output="sos")
    orig = width_ratio(sosfiltfilt(sos, song.mix, axis=-1))
    spat = width_ratio(sosfiltfilt(sos, y.T, axis=-1))
    assert spat >= 0.85 * orig, (spat, orig)
    assert spat <= 2.0 * orig, (spat, orig)  # wider is allowed, but not a hollow, inside-out stage
