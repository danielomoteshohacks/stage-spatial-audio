"""Measure the separation cascade on one file: seconds per level, GPU seconds per minute of audio.

    python scripts/measure_cascade.py song.flac --preset fast [--seconds 60] [--out cascade.json]

Run it on the Space's hardware (a ZeroGPU worker or any CUDA machine): GPU seconds come from
CUDA-synchronised timers around every model call (stage.separation.cascade.runner.TorchModel),
so they exclude downloads and CPU post-processing. The report is what decides which levels the
"fast" preset keeps so that one whole song fits a visitor's daily quota (docs/research/
separation-v3.md). Nothing is claimed from a run on a CPU: the script says so and still prints
the wall times.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stage.separation.cascade import config as cc  # noqa: E402
from stage.separation.cascade.neural import NeuralEngine  # noqa: E402
from stage.separation.cascade.tree import Cascade  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("audio")
    ap.add_argument("--preset", default="fast")
    ap.add_argument("--seconds", type=float, default=0.0, help="first N seconds only (0 = all)")
    ap.add_argument("--allow-unverified", action="store_true",
                    help="enable models whose licence is not stated at the source")
    ap.add_argument("--out", default="cascade.json")
    args = ap.parse_args()
    x, sr = sf.read(args.audio, dtype="float32", always_2d=True)
    x = x.T
    if args.seconds:
        x = x[:, : int(args.seconds * sr)]
    specs = cc.models()
    wanted = [m for ids in cc.preset(args.preset)["levels"].values() if isinstance(ids, list)
              for m in ids]
    engines = {m: NeuralEngine(specs[m]) for m in wanted}
    allowed = cc.ALLOWED_DEFAULT + (("unverified",) if args.allow_unverified else ())
    casc = Cascade(args.preset, engines=engines, allowed=allowed)
    t0 = time.perf_counter()
    res = casc.run(x, sr)
    wall = time.perf_counter() - t0
    minutes = x.shape[1] / sr / 60.0
    gpu = {m: round(e.gpu_seconds, 2) for m, e in engines.items()}
    on_gpu = any(getattr(e._model, "device", "cpu") == "cuda" for e in engines.values()
                 if e._model is not None)
    report = {**res.report, "audio_s": round(x.shape[1] / sr, 1), "wall_s": round(wall, 1),
              "gpu_s_by_model": gpu, "gpu_s_per_audio_minute": round(sum(gpu.values()) / minutes, 2)
              if on_gpu else None,
              "ran_on_cuda": on_gpu,
              "leaves": {k: q.as_dict() for k, q in res.quality.items()}}
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "leaves"}, indent=2))
    if not on_gpu:
        print("note: no model ran on CUDA, so no GPU figure is reported")


if __name__ == "__main__":
    main()
