"""SoundStage Separator inference on the CPU with ONNX Runtime (no torch needed).

The track is processed in overlapping chunks (6 s, 25 percent overlap): per chunk, the numpy
STFT goes into the ONNX graph, the masks and the waveform branch give stem spectra, and the DSP
back end (Wiener refinement, bleed reduction, mixture consistency) runs on that chunk. Chunks are
joined with complementary linear crossfades, so the stems still sum to the mixture exactly.

The weights are a model.onnx plus model.json (configuration and the evaluation that decides
whether this engine may be the default). They are looked for in the cache, or downloaded from the
Hugging Face model repository by `fetch_weights`, which the Space calls at start-up.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.signal import resample_poly

from stage.analysis.stft import istft, stft
from stage.separation.ssep.config import WEIGHTS_REPO, SsepConfig
from stage.separation.ssep.dsp import refine

WEIGHT_FILES = ("model.onnx", "model.json")


def weights_dir() -> Path:
    base = Path(os.environ.get("SOUNDSTAGE_CACHE", Path.home() / ".cache" / "soundstage"))
    return Path(os.environ.get("SOUNDSTAGE_SSEP_DIR", base / "ssep"))


def find_weights() -> Path | None:
    d = weights_dir()
    return d if all((d / f).is_file() for f in WEIGHT_FILES) else None


def fetch_weights(repo: str = WEIGHTS_REPO) -> Path | None:
    """Download model.onnx and model.json from the model repository, if they are published.

    Returns None (and leaves the cache alone) when the repository or its files do not exist yet,
    which is the case until the first Kaggle training run has pushed a checkpoint.
    """
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        return None
    d = weights_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        for name in WEIGHT_FILES:
            hf_hub_download(repo_id=repo, filename=name, local_dir=str(d))
    except Exception:
        return None
    return find_weights()


@dataclass
class ModelCard:
    config: SsepConfig
    evaluation: dict[str, Any]

    @property
    def meets_baseline(self) -> bool:
        """True only when a museval evaluation shows our average SDR at least htdemucs'."""
        ev = self.evaluation or {}
        ours, base = ev.get("ssep_avg_sdr_db"), ev.get("htdemucs_avg_sdr_db")
        return ours is not None and base is not None and float(ours) >= float(base)


def read_card(path: Path) -> ModelCard:
    meta = json.loads((path / "model.json").read_text(encoding="utf-8"))
    return ModelCard(config=SsepConfig.from_json(json.dumps(meta["config"])),
                     evaluation=meta.get("evaluation", {}))


def _spec_input(chunk: NDArray, cfg: SsepConfig) -> tuple[NDArray, NDArray]:
    x = stft(chunk, n_fft=cfg.n_fft, hop=cfg.hop)  # (2, T, F) complex
    spec = np.stack([x[0].real, x[0].imag, x[1].real, x[1].imag]).transpose(0, 2, 1)
    return x, spec[np.newaxis].astype(np.float32)


class OnnxSeparator:
    def __init__(self, path: Path, threads: int | None = None) -> None:
        import onnxruntime as ort

        self.card = read_card(path)
        self.cfg = self.card.config
        opts = ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(path / "model.onnx"), sess_options=opts,
                                            providers=["CPUExecutionProvider"])

    def _chunk(self, chunk: NDArray) -> tuple[NDArray, dict[str, Any]]:
        cfg = self.cfg
        x, spec = _spec_input(chunk, cfg)
        mask, resid = self.session.run(None, {"spec": spec,
                                              "wave": chunk[np.newaxis].astype(np.float32)})
        m = mask[0].astype(np.float64)  # (S, 4, F, T)
        mr, mi = m[:, 0::2], m[:, 1::2]  # (S, 2, F, T)
        xt = x.transpose(0, 2, 1)[np.newaxis]  # (1, 2, F, T)
        y = ((mr + 1j * mi) * xt).transpose(0, 1, 3, 2)  # (S, 2, T, F)
        r = resid[0].astype(np.float64)  # (S, 2, n)
        y = y + np.stack([stft(r[s], n_fft=cfg.n_fft, hop=cfg.hop) for s in range(r.shape[0])])
        y, info = refine(y, x)
        stems = np.stack([istft(y[s], chunk.shape[1], n_fft=cfg.n_fft, hop=cfg.hop)
                          for s in range(y.shape[0])])
        return stems, info

    def separate(self, audio: NDArray, sample_rate: int) -> tuple[dict[str, NDArray],
                                                                  dict[str, Any]]:
        cfg = self.cfg
        audio = np.asarray(audio, dtype=np.float64)
        n_in = audio.shape[1]
        x = audio if sample_rate == cfg.sample_rate else resample_poly(
            audio, cfg.sample_rate, sample_rate, axis=-1)
        # The network sees a mixture of unit standard deviation, as in training; the stems are
        # scaled back afterwards (the Demucs convention).
        scale = float(np.std(x)) or 1.0
        x = x / scale
        n = x.shape[1]
        seg = int(cfg.segment_s * cfg.sample_rate)
        step = int(seg * (1.0 - cfg.overlap))
        fade = seg - step
        out = np.zeros((len(cfg.stems), 2, n))
        infos = []
        t0 = time.perf_counter()
        start = 0
        while True:
            end = min(start + seg, n)
            chunk = x[:, start:end]
            if chunk.shape[1] < 2 * cfg.n_fft:
                chunk = np.pad(chunk, ((0, 0), (0, 2 * cfg.n_fft - chunk.shape[1])))
            stems, info = self._chunk(chunk)
            stems = stems[..., : end - start]
            w = np.ones(end - start)
            if start > 0:
                w[:fade] = np.linspace(0.0, 1.0, fade, endpoint=False)
            if end < n:
                # 1 - k / fade: the exact complement of the next chunk's fade-in.
                w[-fade:] = np.minimum(w[-fade:], np.linspace(1.0, 0.0, fade, endpoint=False))
            out[..., start:end] += stems * w
            infos.append(info)
            if end >= n:
                break
            start += step
        elapsed = time.perf_counter() - t0
        out *= scale
        if sample_rate != cfg.sample_rate:
            out = resample_poly(out, sample_rate, cfg.sample_rate, axis=-1)
        if out.shape[-1] < n_in:
            out = np.pad(out, ((0, 0), (0, 0), (0, n_in - out.shape[-1])))
        out = out[..., :n_in]
        # The crossfades and the resampling keep the sum to rounding; the last residual goes to
        # the stems by energy so the sum is exact again.
        resid = audio - out.sum(axis=0)
        energy = np.sum(out**2, axis=(1, 2)) + 1e-12
        out += (energy / energy.sum())[:, None, None] * resid[None]
        leak = np.mean([i["leakage_db"] for i in infos], axis=0)
        return ({name: out[i] for i, name in enumerate(cfg.stems)},
                {"cpu_seconds": round(elapsed, 3),
                 "seconds_per_30s": round(elapsed * 30.0 / max(n / cfg.sample_rate, 1e-9), 3),
                 "leakage_db": dict(zip(cfg.stems, [round(float(v), 2) for v in leak],
                                        strict=True)),
                 "raw_residual_snr_db": infos[0]["raw_residual_snr_db"],
                 "evaluation": self.card.evaluation})
