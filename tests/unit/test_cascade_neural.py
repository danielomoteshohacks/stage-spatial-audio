"""The neural plumbing, without published weights: a tiny randomly initialised BS-RoFormer is
saved as an MSST checkpoint and loaded back by the same code that loads the real ones."""

import numpy as np
import pytest

from stage.separation.cascade.config import models
from stage.separation.cascade.neural import checkpoint_url

torch = pytest.importorskip("torch")
pytest.importorskip("bs_roformer")
pytest.importorskip("yaml")


def test_checkpoint_urls_follow_the_manifest():
    ms = models()
    assert checkpoint_url(ms["kim_mbr_vocals"]) == (
        "https://huggingface.co/KimberleyJSN/melbandroformer/resolve/main/MelBandRoformer.ckpt")
    assert checkpoint_url(ms["drumsep_mdx23c"]).startswith(
        "https://github.com/jarredou/models/releases/download/DrumSep/")


def test_tiny_checkpoint_roundtrip_and_chunked_separation(tmp_path):
    from stage.separation.cascade.runner import TorchModel, build_model

    model_cfg = {"dim": 32, "depth": 1, "stereo": True, "num_stems": 2,
                 "time_transformer_depth": 1, "freq_transformer_depth": 1,
                 "linear_transformer_depth": 0, "freqs_per_bands": [257, 256, 256, 256],
                 "dim_head": 8, "heads": 2, "attn_dropout": 0.0, "ff_dropout": 0.0,
                 "flash_attn": False, "stft_n_fft": 2048, "stft_hop_length": 512,
                 "stft_win_length": 2048, "mask_estimator_depth": 1,
                 "multi_stft_resolution_loss_weight": 1.0,
                 "multi_stft_resolutions_window_sizes": [2048, 1024],
                 "multi_stft_hop_size": 512, "multi_stft_normalized": False}
    net = build_model("bs_roformer", model_cfg)
    path = tmp_path / "tiny.ckpt"
    torch.save(net.state_dict(), path)
    cfg = {"audio": {"sample_rate": 44100, "chunk_size": 44100}, "model": model_cfg}
    tm = TorchModel("bs_roformer", str(path), cfg, device="cpu")
    x = (np.random.default_rng(0).standard_normal((2, 3 * 44100)) * 0.1).astype(np.float32)
    y = tm.separate(x, overlap_s=0.25)
    assert y.shape == (2, 2, x.shape[1]) and np.isfinite(y).all()
    assert tm.timing.audio_seconds == pytest.approx(3.0)
    assert tm.timing.seconds > 0
