"""The SoundStage Separator network: it learns, it exports to ONNX, and training resumes.

Needs torch (and onnx with onnxruntime for the export tests); skipped where they are missing.
CI runs these in the `separator` job with the CPU build of torch.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "training"))

from losses import sdr_db, separation_loss  # noqa: E402

from data import synthetic_multitrack  # noqa: E402
from stage.separation.ssep.config import SsepConfig  # noqa: E402
from stage.separation.ssep.model import (  # noqa: E402
    SsepNet,
    count_parameters,
    separate_tensor,
    torch_istft,
    torch_stft,
)

SMALL = SsepConfig(dim=48, layers=2, heads=4, wave_channels=(16, 32, 48))
#: The overfit gate: mean SDR over the four stems after 100 steps on one toy batch.
OVERFIT_STEPS = 100
OVERFIT_MIN_SDR_DB = 8.0


def test_full_model_fits_the_size_budget():
    n = count_parameters(SsepNet())
    assert n * 2 < 10 * 2**20, f"{n} parameters is {n * 2 / 2**20:.1f} MB in fp16"


def test_torch_stft_matches_the_numpy_reference():
    from stage.analysis.stft import stft

    x = torch.randn(2, 20000, dtype=torch.float64)
    ref = stft(x.numpy(), 2048, 512)
    assert np.max(np.abs(torch_stft(x, 2048, 512).numpy() - ref)) < 1e-9
    back = torch_istft(torch_stft(x, 2048, 512), 20000, 2048, 512)
    assert torch.max(torch.abs(back - x)) < 1e-9


def test_overfits_a_tiny_synthetic_multitrack_batch():
    torch.manual_seed(0)
    mix, stems = synthetic_multitrack(2, 1.5, 44100)
    mix, stems = torch.from_numpy(mix), torch.from_numpy(stems)
    scale = mix.std(dim=(1, 2), keepdim=True)
    mix, stems = mix / scale, stems / scale[:, None]
    net = SsepNet(SMALL)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3)
    for _ in range(OVERFIT_STEPS):
        est = separate_tensor(net, mix)
        loss = separation_loss(est, stems, None)
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0)
        opt.step()
    sdr = sdr_db(separate_tensor(net, mix).detach(), stems)
    assert float(sdr.mean()) >= OVERFIT_MIN_SDR_DB, sdr.tolist()
    assert float(sdr.min()) > 0.0, sdr.tolist()


def test_onnx_export_matches_pytorch(tmp_path):
    pytest.importorskip("onnx")
    ort = pytest.importorskip("onnxruntime")
    from export import export_onnx

    torch.manual_seed(1)
    net = SsepNet(SMALL)
    export_onnx(net, tmp_path, fp16=False)
    sess = ort.InferenceSession(str(tmp_path / "model.onnx"), providers=["CPUExecutionProvider"])
    for frames in (30, 90):
        spec = torch.randn(1, 4, SMALL.n_bins, frames)
        wave = torch.randn(1, 2, (frames - 1) * SMALL.hop)
        with torch.no_grad():
            m, r = net(spec, wave)
        om, orr = sess.run(None, {"spec": spec.numpy(), "wave": wave.numpy()})
        assert np.max(np.abs(om - m.numpy())) < 1e-4
        assert np.max(np.abs(orr - r.numpy())) < 1e-4
    card = json.loads((tmp_path / "model.json").read_text())
    assert card["config"]["dim"] == 48 and card["evaluation"] == {}


def test_onnx_separator_returns_stems_that_sum_to_the_mix(tmp_path, monkeypatch):
    pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    from export import export_onnx

    from stage.separation.ssep.infer import OnnxSeparator

    export_onnx(SsepNet(SMALL), tmp_path, fp16=True)
    mix, _ = synthetic_multitrack(1, 8.0, 44100, seed=4)
    stems, info = OnnxSeparator(tmp_path).separate(mix[0].astype(np.float64), 48000)
    total = sum(stems.values())
    assert set(stems) == {"vocals", "drums", "bass", "other"}
    assert all(s.shape == mix[0].shape for s in stems.values())
    assert np.max(np.abs(total - mix[0])) < 1e-6
    assert info["seconds_per_30s"] > 0 and len(info["leakage_db"]) == 4


def test_training_script_resumes_and_exports(tmp_path):
    pytest.importorskip("onnx")
    import soundfile as sf

    mix, stems = synthetic_multitrack(2, 8.0, 44100)
    root = tmp_path / "train"
    for i in range(2):
        d = root / f"song{i}"
        d.mkdir(parents=True)
        sf.write(str(d / "mixture.wav"), mix[i].T, 44100)
        for j, name in enumerate(("vocals", "drums", "bass", "other")):
            sf.write(str(d / f"{name}.wav"), stems[i, j].T, 44100)
    out = tmp_path / "out"
    cmd = [sys.executable, str(ROOT / "training" / "train.py"), "--musdb", str(root),
           "--out", str(out), "--batch", "1", "--save-every", "1"]
    subprocess.run(cmd + ["--steps", "1"], check=True, capture_output=True, timeout=600)
    second = subprocess.run(cmd + ["--steps", "2"], check=True, capture_output=True, text=True,
                            timeout=600)
    assert "resumed at step 1" in second.stdout
    card = json.loads((out / "model.json").read_text())
    assert card["training"]["steps"] == 2 and (out / "model.onnx").stat().st_size > 1e6
