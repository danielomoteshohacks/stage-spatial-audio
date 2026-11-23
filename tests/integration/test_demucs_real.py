"""Runs the real Demucs model. Skipped unless torch and demucs are installed (the separation extra).

The first run downloads the htdemucs weights into the torch hub cache, so it needs network once.
"""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch")
pytest.importorskip("demucs")

from stage.pipeline import run  # noqa: E402
from stage.separation.demucs_sep import STEM_NAMES, separate  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "make_test_signal", Path(__file__).resolve().parents[2] / "scripts" / "make_test_signal.py"
)
make_test_signal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_test_signal)


@pytest.mark.parametrize("sample_rate", [44100, 48000])
def test_real_demucs_returns_four_stems_of_the_input_length(sample_rate):
    audio = make_test_signal.make_test_signal(4.0, sample_rate)
    sep = separate(audio, sample_rate, model="htdemucs", device="auto")
    assert list(sep.stems) == list(STEM_NAMES)
    for stem in sep.stems.values():
        assert stem.shape == audio.shape and stem.dtype == np.float64
    # Demucs is not constrained to sum to the mix; on a simple signal it should come close.
    assert sep.residual_snr_db > 10.0


def test_real_stems_run_end_to_end(track, tmp_path):
    result = run(track, mode="stems", profile="V0", out_dir=tmp_path / "o")
    assert result.ok and result.mode == "stems", result.report
    assert (tmp_path / "o" / "stems_spatial" / "vocals.flac").exists()
