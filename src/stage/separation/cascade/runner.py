"""Chunked, overlap-added inference for any model that maps a stereo chunk to stems.

Separators are trained on a fixed segment (about 12 s) and lose accuracy and memory at the
edges of every segment. The standard remedy, used by ZFTurbo's MSST inference script and the
Demucs apply function, is to cut the song into overlapping chunks, run each, and cross-fade
the outputs. `chunked_apply` does that for any `forward(chunk) -> stems` callable, with a
sin^2 cross-fade (constant sum, so a model that returns its input as one stem reproduces the
input exactly: tests/unit/test_cascade_runner.py), reflect padding at both ends, and the
output at the input's exact length.

`TorchModel` wraps a checkpoint in the MSST format: ZFTurbo's model classes when the Space has
them on its path (they match the published checkpoints' parameter names), else the
`bs_roformer` package. The model runs in float16 under autocast on CUDA and in float32 on CPU,
and GPU time is measured with a CUDA synchronise, so the GPU seconds per minute of audio in
`run.json` are real.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

Forward = Callable[[NDArray[np.float32]], NDArray[np.float32]]


def chunk_plan(n: int, chunk: int, overlap: int) -> list[int]:
    """Start offsets of the chunks that cover `n` samples with `overlap` samples between them."""
    if n <= chunk:
        return [0]
    step = chunk - overlap
    starts = list(range(0, n - chunk + 1, step))
    if starts[-1] + chunk < n:
        starts.append(n - chunk)
    return starts


def crossfade_window(chunk: int, overlap: int) -> NDArray[np.float32]:
    """sin^2 ramps over the overlap at both ends: two neighbours' ramps sum to exactly one."""
    w = np.ones(chunk, dtype=np.float32)
    if overlap > 0:
        ramp = np.sin(0.5 * np.pi * (np.arange(overlap) + 0.5) / overlap).astype(np.float32) ** 2
        w[:overlap] = ramp
        w[-overlap:] = ramp[::-1]
    return w


def chunked_apply(forward: Forward, audio: NDArray, chunk: int, overlap: int,
                  n_stems: int) -> NDArray[np.float32]:
    """Run `forward` on overlapping chunks of (2, n) `audio`; returns (n_stems, 2, n) float32."""
    x = np.asarray(audio, dtype=np.float32)
    n = x.shape[1]
    overlap = min(overlap, chunk // 2)
    pad = overlap if n > chunk else 0
    if pad:
        x = np.pad(x, ((0, 0), (pad, pad)), mode="reflect")
    total = x.shape[1]
    if total < chunk:
        x = np.pad(x, ((0, 0), (0, chunk - total)))
    starts = chunk_plan(x.shape[1], chunk, overlap)
    win = crossfade_window(chunk, overlap)
    out = np.zeros((n_stems, 2, x.shape[1]), dtype=np.float32)
    norm = np.zeros(x.shape[1], dtype=np.float32)
    for s in starts:
        part = x[:, s : s + chunk]
        y = forward(part)
        # The first and last chunks have no neighbour to fade with on the outer side.
        w = win.copy()
        if s == starts[0]:
            w[:overlap] = 1.0
        if s == starts[-1]:
            w[-overlap:] = 1.0 if overlap else w[-overlap:]
        out[:, :, s : s + chunk] += y * w
        norm[s : s + chunk] += w
    out /= np.maximum(norm, 1e-8)
    return out[:, :, pad : pad + n]


@dataclass
class GpuTiming:
    seconds: float = 0.0
    audio_seconds: float = 0.0

    @property
    def per_minute(self) -> float:
        return self.seconds / max(self.audio_seconds / 60.0, 1e-9)


class TorchModel:
    """A checkpoint in the MSST format, run in fp16 on CUDA and fp32 on CPU."""

    def __init__(self, family: str, ckpt_path: str, cfg: dict[str, Any], device: str | None = None
                 ) -> None:
        import torch

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.half = self.device == "cuda"
        self.cfg = cfg
        self.sample_rate = int(cfg["audio"]["sample_rate"])
        self.chunk = int(cfg["audio"]["chunk_size"])
        self.model = build_model(family, cfg["model"])
        state = torch.load(ckpt_path, map_location="cpu", weights_only=True)
        state = state.get("state_dict", state)
        self.model.load_state_dict(state, strict=True)
        self.model.eval().to(self.device)
        if self.half:
            self.model.half()
        self.n_stems = int(cfg["model"].get("num_stems", 1))
        self.timing = GpuTiming()

    def __call__(self, chunk: NDArray[np.float32]) -> NDArray[np.float32]:
        torch = self.torch
        t0 = time.perf_counter()
        with torch.inference_mode():
            x = torch.from_numpy(np.ascontiguousarray(chunk))[None].to(self.device)
            if self.half:
                x = x.half()
            y = self.model(x)
            if y.dim() == 3:  # one stem comes back as (batch, channels, time)
                y = y[:, None]
            y = y[0].float().cpu().numpy()
        m = chunk.shape[1]
        if y.shape[-1] != m:  # an inverse STFT can come back a few samples short
            y = y[..., :m] if y.shape[-1] > m else np.pad(y, ((0, 0), (0, 0), (0, m - y.shape[-1])))
        if self.device == "cuda":
            torch.cuda.synchronize()
        self.timing.seconds += time.perf_counter() - t0
        return y

    def separate(self, audio: NDArray, overlap_s: float = 2.0) -> NDArray[np.float32]:
        n = audio.shape[1]
        self.timing.audio_seconds += n / self.sample_rate
        return chunked_apply(self, audio, self.chunk, int(overlap_s * self.sample_rate),
                             self.n_stems)


def build_model(family: str, model_cfg: dict[str, Any]):
    """The network for a config's `model:` block."""
    cfg = {k: (tuple(v) if isinstance(v, list) else v) for k, v in model_cfg.items()}
    try:  # ZFTurbo's classes, on the path when the Space has cloned the repository
        from models.bs_roformer import BSRoformer, MelBandRoformer  # type: ignore
    except ImportError:
        from bs_roformer import BSRoformer, MelBandRoformer
        # The package's newer defaults add residual streams that published checkpoints lack.
        cfg.setdefault("add_value_residual", False)
        cfg.setdefault("num_residual_streams", 1)
    classes = {"mel_band_roformer": MelBandRoformer, "bs_roformer": BSRoformer}
    if family not in classes:
        raise ValueError(f"no loader for the model family {family!r}")
    cls = classes[family]
    known = set(inspect.signature(cls.__init__).parameters)
    for k in [k for k in cfg if k not in known]:
        # A setting the installed class does not have is dropped only when it is switched off
        # (a zero-depth linear transformer in a BS-RoFormer config); anything else would build a
        # different network from the one the checkpoint was trained with.
        if cfg[k] not in (0, False, None):
            raise ValueError(f"{family} has no parameter {k!r} (config value {cfg[k]!r})")
        del cfg[k]
    return cls(**cfg)
