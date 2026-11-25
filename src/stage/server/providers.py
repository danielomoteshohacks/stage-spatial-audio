"""Where a job gets its leaves from on this machine.

* With `SOUNDSTAGE_NEURAL=1` (the Space, with its GPU) the cascade runs its neural levels for the
  preset, downloaded on first use and checked against their manifest hashes.
* Otherwise, or if a neural level cannot load, the four-stem fallback chain runs (the SoundStage
  Separator when it has been published and evaluated, then htdemucs) and the cascade's model-free
  levels refine it.
* With no separator at all, the model-free decomposition runs and the job's run.json says so.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from stage.separation.cascade import config as cc
from stage.separation.chain import separate_chain
from stage.spatial.hrtf import cache_dir
from stage.stream.job import Provider, make_cascade_provider


def neural_engines(preset: str) -> dict[str, Any]:
    if os.environ.get("SOUNDSTAGE_NEURAL") != "1":
        return {}
    from stage.separation.cascade.neural import NeuralEngine

    specs = cc.models()
    wanted = [m for ids in cc.preset(preset)["levels"].values() if isinstance(ids, list)
              for m in ids]
    return {m: NeuralEngine(specs[m]) for m in wanted}


def default_provider_factory(gpu_wrap: Callable | None = None) -> Callable[[str], Provider]:
    """`gpu_wrap` wraps the callable that touches the GPU (the Space passes `spaces.GPU(...)`)."""
    wrap = gpu_wrap or (lambda fn: fn)

    def factory(preset: str) -> Provider:
        engines = neural_engines(preset)
        root = Path(os.environ.get("SOUNDSTAGE_CASCADE_CACHE", cache_dir() / "cascade-levels"))
        sep = wrap(lambda a, sr: separate_chain(a, sr))
        inner = make_cascade_provider(preset, engines, root, sep)
        return wrap(inner) if engines else inner

    return factory
