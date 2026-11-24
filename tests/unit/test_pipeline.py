import json
import tracemalloc
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from jsonschema import Draft202012Validator

import stage.pipeline as pipeline
from stage.separation.demucs_sep import STEM_NAMES, Separation, SeparationUnavailable

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "schemas" / "run.schema.json").read_text()
)


def _valid(out_dir: Path) -> dict:
    report = json.loads((out_dir / "run.json").read_text(encoding="utf-8"))
    Draft202012Validator(SCHEMA).validate(report)
    return report


def _frames(path: Path) -> int:
    return sf.info(str(path)).frames


def _statuses(result) -> dict:
    return {s.name: s.status for s in result.stages}


def test_lite_writes_original_and_spatial_of_the_input_length(track, tmp_path):
    out = tmp_path / "out"
    result = pipeline.run(track, mode="lite", profile="V0", out_dir=out)
    assert result.ok and result.mode == "lite" and result.fallback is None
    assert _statuses(result) == {"load": "ok", "separate": "skipped", "render": "ok",
                                 "levels": "ok", "guard": "ok", "write": "ok"}
    n = sf.info(str(track)).frames
    assert _frames(out / "original.flac") == n and _frames(out / "spatial.flac") == n
    info = sf.info(str(out / "spatial.flac"))
    assert info.format == "FLAC" and info.subtype == "PCM_24"
    report = _valid(out)
    assert report["levels"]["spatial_rms_dbfs"] == pytest.approx(
        report["levels"]["original_rms_dbfs"], abs=0.01)
    assert not (out / "stems").exists()


def test_excerpt_is_respected(track, tmp_path):
    result = pipeline.run(track, profile="V0", start=0.5, seconds=1.0, out_dir=tmp_path / "o")
    assert result.ok
    assert _frames(tmp_path / "o" / "spatial.flac") == 44100
    assert result.report["input"]["start_s"] == 0.5


def test_stems_mode_writes_dry_and_spatial_stems_that_sum_to_the_render(
    track, tmp_path, fake_separator
):
    out = tmp_path / "out"
    result = pipeline.run(track, mode="stems", profile="V0", out_dir=out,
                          separator=fake_separator)
    assert result.ok and result.mode == "stems"
    assert all(s == "ok" for s in _statuses(result).values())
    n = sf.info(str(track)).frames
    total = np.zeros((n, 2))
    for name in STEM_NAMES:
        assert _frames(out / "stems" / f"{name}.flac") == n
        y, _ = sf.read(str(out / "stems_spatial" / f"{name}.flac"))
        assert y.shape == (n, 2)
        total += y
    spatial, _ = sf.read(str(out / "spatial.flac"))
    # Shared gain, so the stems mixed back at unity equal the full render up to 24-bit rounding.
    assert np.max(np.abs(total - spatial)) < 1e-5
    report = _valid(out)
    assert report["separation"]["model"] == "fake-bands"
    assert report["separation"]["residual_snr_db"] > 100.0


def test_separation_unavailable_falls_back_to_lite(track, tmp_path):
    def unavailable(audio, sr):
        raise SeparationUnavailable("torch and demucs are not installed")

    out = tmp_path / "out"
    result = pipeline.run(track, mode="stems", profile="V0", out_dir=out, separator=unavailable)
    assert result.ok and result.requested_mode == "stems" and result.mode == "lite"
    assert result.fallback["to"] == "lite" and "not installed" in result.fallback["reason"]
    assert result.stage("separate").status == "failed"
    assert (out / "spatial.flac").exists() and not (out / "stems_spatial").exists()
    report = _valid(out)
    assert report["mode"] == "lite" and report["separation"] is None


def test_default_separator_without_demucs_falls_back(track, tmp_path):
    try:
        import demucs  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("demucs is installed; the real separator runs in the integration test")
    result = pipeline.run(track, mode="stems", profile="V0", out_dir=tmp_path / "o")
    assert result.ok and result.mode == "lite"
    assert "SeparationUnavailable" in result.fallback["reason"]


def test_a_separator_with_wrong_shapes_is_rejected_and_falls_back(track, tmp_path):
    def short(audio, sr):
        stems = {k: audio[:, :-10] / 4 for k in STEM_NAMES}
        return Separation(stems=stems, sample_rate=sr, residual_snr_db=0.0)

    result = pipeline.run(track, mode="stems", profile="V0", out_dir=tmp_path / "o",
                          separator=short)
    assert result.ok and result.mode == "lite"
    assert "shape" in result.stage("separate").error


def test_a_failing_render_never_crashes_the_run(track, tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise MemoryError("out of memory in the renderer")

    monkeypatch.setattr(pipeline, "render_engine", broken)
    out = tmp_path / "out"
    result = pipeline.run(track, profile="V0", out_dir=out)
    assert not result.ok
    assert _statuses(result) == {"load": "ok", "separate": "skipped", "render": "failed",
                                 "levels": "skipped", "guard": "skipped",
                                 "write": "ok"}
    assert "MemoryError" in result.stage("render").error
    assert (out / "original.flac").exists() and not (out / "spatial.flac").exists()
    assert _valid(out)["ok"] is False


def test_a_missing_file_fails_load_and_skips_the_rest(tmp_path):
    out = tmp_path / "out"
    result = pipeline.run(tmp_path / "nope.wav", out_dir=out)
    assert not result.ok
    assert _statuses(result) == {"load": "failed", "separate": "skipped", "render": "skipped",
                                 "levels": "skipped", "guard": "skipped",
                                 "write": "skipped"}
    assert _valid(out)["stages"][0]["error"]


def test_a_start_past_the_end_fails_load(track, tmp_path):
    result = pipeline.run(track, start=10.0, out_dir=tmp_path / "o")
    assert result.stage("load").status == "failed" and "empty" in result.stage("load").error


def test_progress_events_arrive_in_order_and_a_broken_callback_is_harmless(track, tmp_path):
    events = []

    def on_stage(event):
        events.append((event["stage"], event["status"]))
        raise RuntimeError("display crashed")

    result = pipeline.run(track, profile="V0", out_dir=tmp_path / "o", on_stage=on_stage)
    assert result.ok
    assert events == [("load", "running"), ("load", "ok"), ("separate", "skipped"),
                      ("render", "running"), ("render", "ok"), ("levels", "running"),
                      ("levels", "ok"), ("guard", "running"), ("guard", "ok"),
                      ("write", "running"), ("write", "ok")]


def test_stems_are_rendered_one_at_a_time(track, tmp_path, fake_separator, monkeypatch):
    real = pipeline.render_engine
    active, seen = [0], []

    def tracking(audio, sr, profile, beta):
        active[0] += 1
        assert active[0] == 1, "two stems were being rendered at once"
        seen.append(audio)
        try:
            return real(audio, sr, profile, beta)
        finally:
            active[0] -= 1

    monkeypatch.setattr(pipeline, "render_engine", tracking)
    pipeline.run(track, mode="stems", profile="V0", out_dir=tmp_path / "o",
                 separator=fake_separator)
    assert len(seen) == len(STEM_NAMES)
    assert all(a.shape[0] == 2 for a in seen)


def test_stems_peak_memory_stays_near_one_lite_render(track, tmp_path, fake_separator):
    def peak(**kwargs) -> int:
        tracemalloc.start()
        try:
            pipeline.run(track, profile="V0", out_dir=tmp_path / kwargs.pop("name"), **kwargs)
            return tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

    lite = peak(name="lite")
    stems = peak(name="stems", mode="stems", separator=fake_separator)
    # Four renders held at once would be about 4x; one at a time plus the kept (2, n) outputs
    # is close to 1x.
    assert stems < 1.6 * lite, (stems, lite)


@pytest.mark.parametrize("kwargs", [{"mode": "atmos"}, {"profile": "V9"}, {"beta": 3.0}])
def test_invalid_arguments_are_rejected_up_front(track, tmp_path, kwargs):
    with pytest.raises(ValueError):
        pipeline.run(track, out_dir=tmp_path / "o", **kwargs)
