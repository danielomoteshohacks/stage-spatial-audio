import importlib.util
from pathlib import Path

import numpy as np

_path = Path(__file__).resolve().parents[2] / "scripts" / "render_clip.py"
_spec = importlib.util.spec_from_file_location("render_clip", _path)
render_clip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_clip)


def test_match_rms_hits_the_target():
    x = np.random.default_rng(0).standard_normal((2, 5000))
    assert abs(render_clip.rms(render_clip.match_rms(x, 0.1)) - 0.1) < 1e-12


def test_match_rms_leaves_silence_alone():
    x = np.zeros((2, 10))
    assert np.array_equal(render_clip.match_rms(x, 0.1), x)


def test_peak_limit_never_exceeds_the_ceiling_and_only_scales():
    x = np.array([[0.5, -2.0, 1.0], [0.1, 0.2, 0.3]])
    y, gain = render_clip.limit_peak(x)
    assert np.max(np.abs(y)) <= render_clip.PEAK_CEILING + 1e-12
    assert np.allclose(y, x * gain)  # a gain change, so the waveform shape is unchanged


def test_peak_limit_is_a_no_op_below_the_ceiling():
    x = np.array([[0.5, -0.4], [0.1, 0.2]])
    y, gain = render_clip.limit_peak(x)
    assert gain == 1.0 and np.array_equal(x, y)


def test_guard_flag_prints_the_report(tmp_path, monkeypatch, capsys):
    # A synthetic stereo clip written to a temporary folder, never to the repository.
    import soundfile as sf

    fs = 44100
    rng = np.random.default_rng(4)
    centre = rng.standard_normal(3 * fs)
    clip = 0.1 * np.stack([centre + 0.3 * rng.standard_normal(3 * fs),
                           centre + 0.3 * rng.standard_normal(3 * fs)])
    wav = tmp_path / "clip.wav"
    sf.write(str(wav), clip.T, fs, subtype="PCM_24")
    out = tmp_path / "renders"
    monkeypatch.setattr(
        "sys.argv", ["render_clip.py", str(wav), "--seconds", "3", "--out-dir", str(out), "--guard"]
    )
    render_clip.main()
    text = capsys.readouterr().out
    for row in ("alignment", "loudness", "timbre", "low end", "overall:"):
        assert row in text
    assert (out / "input_stage.wav").exists()
