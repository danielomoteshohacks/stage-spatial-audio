import numpy as np
import pytest

from stage.guard.levels import PEAK_CEILING, limit_peak, match_rms, peak_gain, rms


def test_rms_of_a_full_scale_square_wave_is_one():
    x = np.array([[1.0, -1.0, 1.0, -1.0], [-1.0, 1.0, -1.0, 1.0]])
    assert rms(x) == 1.0


def test_match_rms_hits_the_target_and_keeps_the_shape():
    x = np.random.default_rng(0).standard_normal((2, 5000))
    y = match_rms(x, 0.1)
    assert abs(rms(y) - 0.1) < 1e-12
    assert np.allclose(y / x, y[0, 0] / x[0, 0])


def test_match_rms_returns_silence_unchanged():
    x = np.zeros((2, 10))
    assert match_rms(x, 0.1) is x


@pytest.mark.parametrize("peak,expected", [(0.5, 1.0), (PEAK_CEILING, 1.0), (1.96, 0.5)])
def test_peak_gain(peak, expected):
    assert peak_gain(peak) == pytest.approx(expected)


def test_limit_peak_scales_down_to_the_ceiling():
    x = np.array([[0.5, -2.0, 1.0], [0.1, 0.2, 0.3]])
    y, gain = limit_peak(x)
    assert np.max(np.abs(y)) == pytest.approx(PEAK_CEILING)
    assert np.allclose(y, x * gain)


def test_limit_peak_with_a_custom_ceiling_and_empty_input():
    y, gain = limit_peak(np.array([[0.8, -0.2]]), ceiling=0.4)
    assert gain == pytest.approx(0.5) and np.max(np.abs(y)) == pytest.approx(0.4)
    empty, g = limit_peak(np.zeros((2, 0)))
    assert g == 1.0 and empty.shape == (2, 0)


def test_scripts_use_the_shared_helpers():
    import importlib.util
    from pathlib import Path

    import stage.guard.levels as levels

    root = Path(__file__).resolve().parents[2] / "scripts"
    for name in ("render_clip", "make_abx"):
        spec = importlib.util.spec_from_file_location(name, root / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.rms is levels.rms and mod.match_rms is levels.match_rms
        assert mod.PEAK_CEILING == levels.PEAK_CEILING
