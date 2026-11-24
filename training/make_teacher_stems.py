"""Write teacher stems for distillation: run the teacher ensemble over a folder of music.

    python training/make_teacher_stems.py --input /kaggle/input/musdb18-hq/train \\
        --out /kaggle/working/teacher/musdb [--models htdemucs_ft] [--mixture-name mixture.wav]

For each track folder (or each audio file, for extra music) it writes vocals, drums, bass and
other as 44.1 kHz float WAV under <out>/<track>/. With several --models the stems are averaged,
which is the ensemble; each model is downloaded by the demucs package on the machine that runs
this (a Kaggle GPU), never on a phone. Teachers are used only here, never shipped.

Teachers (decisions 0015 and 0023). `--teacher htdemucs_ft` is the original: htdemucs_ft from the
demucs repository (MIT). `--teacher cascade:best` (or `cascade:fast`) is the v3 teacher: the whole
separation cascade (vocal RoFormer ensemble, 6-stem model, dereverberation, post-processing),
collapsed to the four stems the separator learns, so the student is distilled from the strongest
open pipeline rather than from one model. The cascade's models carry GPL-3.0 or CC BY-NC-SA
weights (models/MANIFEST.md); the student's weights are research-only already (MUSDB18-HQ) and
stay so until the owner confirms the terms of every teacher in writing. The student is never the
cascade: the cascade runs on the Space's GPU, the student on a phone's CPU.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stage.separation.demucs_sep import separate  # noqa: E402
from stage.separation.ssep.config import STEMS  # noqa: E402

AUDIO = (".wav", ".flac", ".mp3", ".ogg", ".m4a")


def sources(root: Path, mixture_name: str) -> list[tuple[str, Path]]:
    out = []
    for p in sorted(root.iterdir()):
        if p.is_dir() and (p / mixture_name).is_file():
            out.append((p.name, p / mixture_name))
        elif p.is_file() and p.suffix.lower() in AUDIO:
            out.append((p.stem, p))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--models", default="htdemucs_ft",
                    help="demucs models, averaged (used when --teacher is htdemucs)")
    ap.add_argument("--teacher", default="htdemucs", help="htdemucs, or cascade:<preset>")
    ap.add_argument("--mixture-name", default="mixture.wav")
    args = ap.parse_args()
    out = Path(args.out)
    models = args.models.split(",")
    cascade = None
    if args.teacher.startswith("cascade:"):
        from stage.separation.cascade import config as cc
        from stage.separation.cascade.neural import NeuralEngine
        from stage.separation.cascade.tree import Cascade, collapse_to_four

        preset = args.teacher.split(":", 1)[1]
        specs = cc.models()
        wanted = [m for ids in cc.preset(preset)["levels"].values() if isinstance(ids, list)
                  for m in ids]
        cascade = Cascade(preset, engines={m: NeuralEngine(specs[m]) for m in wanted})
    for name, path in sources(Path(args.input), args.mixture_name):
        target = out / name
        if all((target / f"{s}.wav").is_file() for s in STEMS):
            continue  # resumable: a restarted session skips finished tracks
        audio, sr = sf.read(str(path), dtype="float64", always_2d=True)
        audio = audio.T if audio.shape[1] == 2 else np.repeat(audio.T[:1], 2, axis=0)
        acc = {s: np.zeros_like(audio) for s in STEMS}
        if cascade is not None:
            res = collapse_to_four(cascade.run(audio, sr))
            for s in STEMS:
                acc[s] = res[s]
        else:
            for m in models:
                sep = separate(audio, sr, model=m, device="auto")
                for s in STEMS:
                    acc[s] += sep.stems[s] / len(models)
        target.mkdir(parents=True, exist_ok=True)
        for s in STEMS:
            sf.write(str(target / f"{s}.wav"), acc[s].T.astype(np.float32), sr, subtype="FLOAT")
        if not (target / "mixture.wav").exists():
            sf.write(str(target / "mixture.wav"), audio.T.astype(np.float32), sr, subtype="FLOAT")
        print(f"{name}: done with {args.teacher if cascade else models}", flush=True)


if __name__ == "__main__":
    main()
