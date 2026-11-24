"""Neural engines for the cascade: fetch a checkpoint by its manifest entry and run it.

Nothing here runs at install time or in CI. On the Space, `NeuralEngine.separate` is called
inside a function decorated with `@spaces.GPU`; the checkpoint and its config are downloaded to
the cache on first use and the checkpoint's SHA-256 is checked against configs/cascade/models.json
(an entry whose hash is null is recorded on first download and reported, never silently trusted).

Stem names are the model config's `training.instruments` order (MSST format); a model with one
output returns its target and the rest is the mix minus it.
"""

from __future__ import annotations

import hashlib
import urllib.request
from math import gcd
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.signal import resample_poly

from stage.separation.cascade.config import ModelSpec
from stage.spatial.hrtf import cache_dir


def _download(url: str, dest: Path, sha256: str | None, timeout_s: float = 900.0) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and sha256 and _sha(dest) == sha256:
        return sha256
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "soundstage"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp, open(tmp, "wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
    got = _sha(tmp)
    if sha256 and got != sha256:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"{url} does not match its published checksum ({got})")
    tmp.replace(dest)
    return got


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def checkpoint_url(spec: ModelSpec) -> str:
    """The direct download URL of a model's file (a Hugging Face resolve path or a release)."""
    if spec.source.startswith("https://huggingface.co/"):
        return f"{spec.source}/resolve/main/{spec.file}"
    if "/releases/tag/" in spec.source:
        return spec.source.replace("/releases/tag/", "/releases/download/") + "/" + spec.file
    raise ValueError(f"cannot derive a download URL for {spec.id}")


class NeuralEngine:
    def __init__(self, spec: ModelSpec, device: str | None = None) -> None:
        self.spec = spec
        self.name = spec.id
        self.device = device
        self._model: Any = None
        self.fetched_sha256: str | None = None

    def load(self) -> Any:
        if self._model is not None:
            return self._model
        import yaml

        from stage.separation.cascade.runner import TorchModel

        root = cache_dir() / "cascade" / self.spec.id
        ckpt = root / self.spec.file
        self.fetched_sha256 = _download(checkpoint_url(self.spec), ckpt, self.spec.sha256)
        cfg_path = root / "config.yaml"
        if not cfg_path.is_file():
            _download(self.spec.config or "", cfg_path, None, timeout_s=60.0)
        cfg = yaml.load(cfg_path.read_text(encoding="utf-8"), Loader=yaml.UnsafeLoader)
        self._model = TorchModel(self.spec.family, str(ckpt), cfg, self.device)
        return self._model

    @property
    def gpu_seconds(self) -> float:
        return self._model.timing.seconds if self._model else 0.0

    def separate(self, audio: NDArray, sample_rate: int) -> dict[str, NDArray]:
        model = self.load()
        x = np.asarray(audio, dtype=np.float32)
        if sample_rate != model.sample_rate:
            g = gcd(sample_rate, model.sample_rate)
            x = resample_poly(x, model.sample_rate // g, sample_rate // g, axis=1).astype(
                np.float32)
        y = model.separate(x)
        if sample_rate != model.sample_rate:
            g = gcd(sample_rate, model.sample_rate)
            y = resample_poly(y, sample_rate // g, model.sample_rate // g, axis=2).astype(
                np.float32)
        n = audio.shape[1]
        y = y[..., :n] if y.shape[-1] >= n else np.pad(y, ((0, 0), (0, 0), (0, n - y.shape[-1])))
        names = list(self.spec.stems)
        out = {names[i]: y[i] for i in range(min(len(names), y.shape[0]))}
        if y.shape[0] == 1:
            out[names[1] if len(names) > 1 else "rest"] = audio - y[0]
        return out


def build_engines(preset_models: list[str], specs: dict[str, ModelSpec]) -> dict[str, NeuralEngine]:
    return {m: NeuralEngine(specs[m]) for m in preset_models}
