"""Evaluate separators on the MUSDB18-HQ test set: SDR, SIR and SAR per stem, size and CPU time.

    python scripts/eval_separation.py --musdb /kaggle/input/musdb18-hq/test \\
        --engines ssep,htdemucs,htdemucs_ft --ssep /kaggle/working/ssep \\
        --out eval.json [--limit 50] [--update-card /kaggle/working/ssep/model.json]

Metric: museval's BSSEval v4 (Stoter, Liutkus and Ito 2018, "The 2018 Signal Separation
Evaluation Campaign"): SDR, SIR and SAR on 1 s windows, the median over windows per track, then
the median over tracks, per stem; the average SDR is the mean of the four stem medians, the
number the Demucs papers report. museval (MIT) is needed for SIR and SAR; without it the script
says so and reports only the plain SDR per track (10 log10 |s|^2 / |s - s_hat|^2), which is not
comparable with the papers.

--update-card writes our engine's and htdemucs' average SDR into the separator's model.json,
which is what lets `stage.separation.chain` make our engine the default (only when ours is at
least htdemucs).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stage.separation.ssep.config import STEMS  # noqa: E402


def load_track(folder: Path) -> tuple[np.ndarray, dict[str, np.ndarray], int]:
    mix, sr = sf.read(str(folder / "mixture.wav"), dtype="float64", always_2d=True)
    refs = {s: sf.read(str(folder / f"{s}.wav"), dtype="float64", always_2d=True)[0].T
            for s in STEMS}
    return mix.T, refs, sr


def engine(name: str, ssep_dir: str | None):
    """(separate(audio, sr) -> stems dict, parameter count, description)."""
    if name == "ssep":
        from stage.separation.ssep.infer import OnnxSeparator

        sep = OnnxSeparator(Path(ssep_dir))
        params = json.loads((Path(ssep_dir) / "model.json").read_text()).get("parameters")
        return (lambda a, sr: sep.separate(a, sr)[0]), params, "SoundStage Separator (ONNX, CPU)"
    from stage.separation.demucs_sep import separate

    try:
        from demucs.pretrained import get_model

        model = get_model(name)
        params = sum(p.numel() for p in model.parameters())
    except Exception:
        params = None
    return (lambda a, sr: separate(a, sr, model=name, device="auto").stems), params, name


def metrics(refs: dict[str, np.ndarray], est: dict[str, np.ndarray], sr: int
            ) -> tuple[dict[str, dict[str, float]], str]:
    try:
        import museval
    except ImportError:
        out = {}
        for s in STEMS:
            num = np.sum(refs[s] ** 2)
            den = np.sum((refs[s] - est[s]) ** 2) + 1e-12
            out[s] = {"SDR": float(10 * np.log10(num / den + 1e-12))}
        return out, "plain SDR (museval not installed; not comparable with the papers)"
    ref = np.stack([refs[s].T for s in STEMS])
    es = np.stack([est[s].T for s in STEMS])
    sdr, _isr, sir, sar = museval.evaluate(ref, es, win=sr, hop=sr)
    return ({s: {"SDR": float(np.nanmedian(sdr[i])), "SIR": float(np.nanmedian(sir[i])),
                 "SAR": float(np.nanmedian(sar[i]))} for i, s in enumerate(STEMS)},
            "museval BSSEval v4, median over 1 s windows, median over tracks")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--musdb", required=True, help="MUSDB18-HQ test folder")
    ap.add_argument("--engines", default="ssep,htdemucs,htdemucs_ft")
    ap.add_argument("--ssep", help="folder with model.onnx and model.json")
    ap.add_argument("--limit", type=int, default=0, help="first N tracks only (0 = all 50)")
    ap.add_argument("--out", default="eval_separation.json")
    ap.add_argument("--update-card", help="model.json to write the averages into")
    args = ap.parse_args()
    tracks = sorted(p for p in Path(args.musdb).iterdir() if (p / "mixture.wav").is_file())
    if args.limit:
        tracks = tracks[: args.limit]
    results: dict[str, dict] = {}
    for name in args.engines.split(","):
        sep, params, desc = engine(name, args.ssep)
        per_track, seconds, audio_s, method = [], 0.0, 0.0, ""
        for folder in tracks:
            mix, refs, sr = load_track(folder)
            t0 = time.perf_counter()
            est = sep(mix, sr)
            seconds += time.perf_counter() - t0
            audio_s += mix.shape[1] / sr
            m, method = metrics(refs, est, sr)
            per_track.append(m)
            print(name, folder.name, {s: round(m[s]["SDR"], 2) for s in STEMS}, flush=True)
        summary = {s: {k: float(np.median([t[s][k] for t in per_track]))
                       for k in per_track[0][s]} for s in STEMS}
        results[name] = {
            "description": desc, "metric": method, "tracks": len(per_track),
            "per_stem": summary,
            "avg_sdr_db": float(np.mean([summary[s]["SDR"] for s in STEMS])),
            "parameters": params,
            "fp16_mb": round(params * 2 / 2**20, 2) if params else None,
            "seconds_per_30s_audio": round(seconds * 30.0 / max(audio_s, 1e-9), 2),
        }
        print(json.dumps({name: results[name]}, indent=2), flush=True)
    Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n| Engine | Avg SDR | Vocals | Drums | Bass | Other | Size (fp16 MB) | s per 30 s |")
    print("|---|---|---|---|---|---|---|---|")
    for name, r in results.items():
        cells = [f"{r['per_stem'][s]['SDR']:.2f}" for s in STEMS]
        print(f"| {name} | {r['avg_sdr_db']:.2f} | " + " | ".join(cells)
              + f" | {r['fp16_mb']} | {r['seconds_per_30s_audio']} |")
    if args.update_card and "ssep" in results and "htdemucs" in results:
        card_path = Path(args.update_card)
        card = json.loads(card_path.read_text())
        card["evaluation"] = {
            "metric": results["ssep"]["metric"], "tracks": results["ssep"]["tracks"],
            "ssep_avg_sdr_db": round(results["ssep"]["avg_sdr_db"], 3),
            "htdemucs_avg_sdr_db": round(results["htdemucs"]["avg_sdr_db"], 3),
            "ssep_per_stem": results["ssep"]["per_stem"],
        }
        card_path.write_text(json.dumps(card, indent=2), encoding="utf-8")
        print(f"updated {card_path}")


if __name__ == "__main__":
    main()
