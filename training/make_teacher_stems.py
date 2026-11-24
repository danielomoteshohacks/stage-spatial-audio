"""Write teacher stems for distillation: run the teacher ensemble over a folder of music.

    python training/make_teacher_stems.py --input /kaggle/input/musdb18-hq/train \\
        --out /kaggle/working/teacher/musdb [--models htdemucs_ft] [--mixture-name mixture.wav]

For each track folder (or each audio file, for extra music) it writes vocals, drums, bass and
other as 44.1 kHz float WAV under <out>/<track>/. With several --models the stems are averaged,
which is the ensemble; each model is downloaded by the demucs package on the machine that runs
this (a Kaggle GPU), never on a phone. Teachers are used only here, never shipped.

Teacher licences (decision 0015): htdemucs_ft comes with the demucs repository (MIT). A RoFormer
teacher can be added the same way once a checkpoint with a confirmed permissive licence is
chosen; none is confirmed yet, so the default ensemble is htdemucs_ft alone.
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
    ap.add_argument("--models", default="htdemucs_ft")
    ap.add_argument("--mixture-name", default="mixture.wav")
    args = ap.parse_args()
    out = Path(args.out)
    models = args.models.split(",")
    for name, path in sources(Path(args.input), args.mixture_name):
        target = out / name
        if all((target / f"{s}.wav").is_file() for s in STEMS):
            continue  # resumable: a restarted session skips finished tracks
        audio, sr = sf.read(str(path), dtype="float64", always_2d=True)
        audio = audio.T if audio.shape[1] == 2 else np.repeat(audio.T[:1], 2, axis=0)
        acc = {s: np.zeros_like(audio) for s in STEMS}
        for m in models:
            sep = separate(audio, sr, model=m, device="auto")
            for s in STEMS:
                acc[s] += sep.stems[s] / len(models)
        target.mkdir(parents=True, exist_ok=True)
        for s in STEMS:
            sf.write(str(target / f"{s}.wav"), acc[s].T.astype(np.float32), sr, subtype="FLOAT")
        if not (target / "mixture.wav").exists():
            sf.write(str(target / "mixture.wav"), audio.T.astype(np.float32), sr, subtype="FLOAT")
        print(f"{name}: done with {models}", flush=True)


if __name__ == "__main__":
    main()
