"""The separator's DSP back end and fallback chain (numpy only; no torch needed)."""

import numpy as np
import pytest

from stage.analysis.stft import stft
from stage.separation.chain import separate_chain
from stage.separation.demucs_sep import SeparationUnavailable
from stage.separation.ssep.config import STEMS, SsepConfig, band_edges
from stage.separation.ssep.dsp import leakage_db, mixture_consistency, refine, wiener

FS = 44100


def _sources(seed=0):
    rng = np.random.default_rng(seed)
    n = FS
    t = np.arange(n) / FS
    a = np.sin(2 * np.pi * 220 * t)
    b = rng.standard_normal(n) * 0.3
    # a: hard left, b: centre. Different positions are what the spatial covariance uses.
    src = np.stack([np.stack([a, 0.1 * a]), np.stack([b, b])])
    return src, src.sum(axis=0)


def test_band_split_covers_every_bin_once():
    bands = band_edges(2048, 44100)
    assert bands[0][0] == 0 and bands[-1][1] == 1025
    assert all(a[1] == b[0] for a, b in zip(bands[:-1], bands[1:], strict=True))
    assert SsepConfig().n_bins == 1025 and len(STEMS) == 4


def test_wiener_improves_rough_estimates_using_position():
    src, mix = _sources()
    y_true = np.stack([stft(s) for s in src])
    x = stft(mix)
    # Rough estimates: each source plus 30 percent of the other.
    rough = np.stack([y_true[0] + 0.3 * y_true[1], y_true[1] + 0.3 * y_true[0]])
    refined = wiener(rough, x, iterations=2)

    def err(y):
        return float(np.sum(np.abs(y - y_true) ** 2))

    assert err(refined) < 0.5 * err(rough)


def test_mixture_consistency_is_exact():
    src, mix = _sources(1)
    x = stft(mix)
    y = np.stack([stft(s) for s in src]) * 0.7
    fixed = mixture_consistency(y, x)
    assert np.max(np.abs(fixed.sum(axis=0) - x)) < 1e-9


def test_refine_reports_and_keeps_the_sum():
    src, mix = _sources(2)
    x = stft(mix)
    y = np.stack([stft(s) for s in src]) * 0.9
    out, info = refine(y, x)
    assert np.max(np.abs(out.sum(axis=0) - x)) < 1e-9
    assert len(info["leakage_db"]) == 2 and info["raw_residual_snr_db"] > 15


def test_leakage_is_low_for_clean_stems_and_high_for_bleed():
    src, _ = _sources(3)
    clean = np.stack([stft(s) for s in src])
    bleed = np.stack([clean[0] + 0.7 * clean[1], clean[1]])
    assert leakage_db(bleed)[0] > leakage_db(clean)[0] + 6


def test_chain_skips_unpublished_weights_and_uses_the_teacher(tmp_path, monkeypatch,
                                                              fake_separator):
    monkeypatch.setenv("SOUNDSTAGE_SSEP_DIR", str(tmp_path / "none"))
    _, mix = _sources()
    sep = separate_chain(mix, FS, teacher=fake_separator)
    assert sep.model == "fake-bands"
    assert sep.chain[0]["name"] == "ssep" and sep.chain[0]["status"] == "skipped"
    assert "not published" in sep.chain[0]["reason"]
    assert sep.chain[1] == {"name": "teacher", "status": "ok", "reason": "fake-bands"}


def test_chain_reports_every_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("SOUNDSTAGE_SSEP_DIR", str(tmp_path / "none"))

    def broken(audio, sr):
        raise SeparationUnavailable("no demucs here")

    _, mix = _sources()
    with pytest.raises(SeparationUnavailable, match="ssep: .*teacher: .*no demucs"):
        separate_chain(mix, FS, teacher=broken)
