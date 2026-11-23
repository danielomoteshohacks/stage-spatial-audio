import importlib.util
import json
from pathlib import Path

import pytest

_path = Path(__file__).resolve().parents[2] / "scripts" / "process_track.py"
_spec = importlib.util.spec_from_file_location("process_track", _path)
process_track = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(process_track)


def test_cli_runs_lite_and_prints_every_stage(track, tmp_path, capsys):
    out = tmp_path / "run"
    code = process_track.main([str(track), "--profile", "V0", "--seconds", "1",
                               "--out-dir", str(out)])
    text = capsys.readouterr().out
    assert code == 0
    for name in ("load", "separate", "render", "levels", "write"):
        assert name in text
    assert json.loads((out / "run.json").read_text())["ok"] is True


def test_cli_reports_a_fallback(track, tmp_path, capsys, monkeypatch):
    from stage.separation.demucs_sep import SeparationUnavailable

    def unavailable(*a, **k):
        raise SeparationUnavailable("torch and demucs are not installed")

    monkeypatch.setattr("stage.pipeline.separate", unavailable)
    code = process_track.main([str(track), "--mode", "stems", "--profile", "V0",
                               "--out-dir", str(tmp_path / "r")])
    assert code == 0
    assert "fallback: rendered the whole mix in Lite" in capsys.readouterr().out


def test_cli_rejects_a_bad_beta(track, tmp_path):
    with pytest.raises(SystemExit):
        process_track.main([str(track), "--beta", "9", "--out-dir", str(tmp_path / "r")])
