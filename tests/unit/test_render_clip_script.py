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
