"""Shared test fixtures. Everything here is test-only and is never imported by the package."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from stage.separation.demucs_sep import STEM_NAMES, Separation, residual_snr_db

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "make_test_signal", ROOT / "scripts" / "make_test_signal.py"
)
make_test_signal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_test_signal)


def fake_split(audio: np.ndarray, sample_rate: int) -> Separation:
    """Deterministic stand-in for Demucs: frequency bands and mid/side, summing exactly to the mix.

    bass is below 200 Hz, drums above 4 kHz, and the band between is split into its mid part
    (vocals) and side part (other). It exercises the stems path without a neural network.
    """
    spec = np.fft.rfft(audio, axis=-1)
    freqs = np.fft.rfftfreq(audio.shape[-1], d=1.0 / sample_rate)
    low, high = freqs < 200.0, freqs >= 4000.0
    band = ~(low | high)
    mid = 0.5 * (spec[0] + spec[1])
    n = audio.shape[-1]

    def back(s: np.ndarray) -> np.ndarray:
        return np.fft.irfft(s, n=n, axis=-1)

    vocals = back(np.stack([mid * band, mid * band]))
    bass = back(spec * low)
    drums = back(spec * high)
    other = audio - vocals - bass - drums  # exact by construction, rounding included
    stems = dict(zip(STEM_NAMES, (vocals, drums, bass, other), strict=True))
    return Separation(stems=stems, sample_rate=sample_rate,
                      residual_snr_db=residual_snr_db(audio, stems), model="fake-bands",
                      device="cpu")


@pytest.fixture
def fake_separator():
    return fake_split


@pytest.fixture
def track(tmp_path) -> Path:
    """A 2 s generated test track at 44.1 kHz, written to a temporary folder."""
    path = tmp_path / "track.wav"
    sf.write(str(path), make_test_signal.make_test_signal(2.0, 44100).T, 44100, subtype="PCM_24")
    return path
