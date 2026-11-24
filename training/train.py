"""Train the SoundStage Separator. Runs on a Kaggle GPU (see kaggle_notebook.ipynb) or the CPU.

    python training/train.py --musdb /kaggle/input/musdb18-hq/train \\
        [--teacher /kaggle/working/teacher/musdb] [--extra /kaggle/working/teacher/extra] \\
        --out /kaggle/working/ssep --hours 8 [--push danieltesh/soundstage-separator]

* Supervised on MUSDB18-HQ ground truth; distilled from the teacher's stems where given
  (`--teacher` for MUSDB tracks, `--extra` for music with teacher stems only).
* Mixed precision on CUDA, gradient clipping, AdamW with a cosine schedule.
* Resumes from <out>/ckpt.pt, saves every --save-every steps and when the --hours budget runs out,
  because Kaggle sessions stop after 12 hours (9 on some GPUs) without warning.
* Exports model.onnx and model.json at the end and, with --push and the HF_TOKEN environment
  variable (a Kaggle secret), uploads them and the checkpoint to the model repository.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from export import export_onnx  # noqa: E402
from losses import sdr_db, separation_loss  # noqa: E402

from data import Augment, list_tracks  # noqa: E402
from stage.separation.ssep.config import SsepConfig  # noqa: E402
from stage.separation.ssep.model import SsepNet, count_parameters, separate_tensor  # noqa: E402


def lr_at(step: int, total: int, base: float, warmup: int = 500) -> float:
    if step < warmup:
        return base * (step + 1) / warmup
    progress = min(1.0, (step - warmup) / max(1, total - warmup))
    return base * (0.05 + 0.95 * 0.5 * (1.0 + math.cos(math.pi * progress)))


def batch(aug: Augment, tracks, size: int, seconds: float, sr: int, device: str):
    mixes, refs, teach = [], [], []
    for _ in range(size):
        m, s, t = aug.example(tracks, seconds, sr)
        mixes.append(m)
        refs.append(s)
        teach.append(t)
    mix = torch.from_numpy(np.stack(mixes)).to(device)
    ref = torch.from_numpy(np.stack(refs)).to(device)
    t = torch.from_numpy(np.stack(teach)).to(device) if all(x is not None for x in teach) else None
    # Unit standard deviation per example, as at inference; references scaled the same way.
    scale = mix.std(dim=(1, 2), keepdim=True).clamp_min(1e-5)
    return mix / scale, ref / scale[:, None], (t / scale[:, None] if t is not None else None)


def push(folder: Path, repo: str) -> None:
    from huggingface_hub import HfApi

    api = HfApi(token=os.environ["HF_TOKEN"])
    api.create_repo(repo, repo_type="model", exist_ok=True, private=False)
    api.upload_folder(repo_id=repo, folder_path=str(folder), repo_type="model",
                      allow_patterns=["model.onnx", "model.json", "ckpt.pt", "train_log.jsonl"],
                      commit_message="SoundStage Separator checkpoint")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--musdb", required=True, help="MUSDB18-HQ train folder")
    ap.add_argument("--teacher", help="teacher stems for the MUSDB tracks (same layout)")
    ap.add_argument("--extra", help="music with teacher stems only (same layout)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=120_000)
    ap.add_argument("--hours", type=float, default=8.0, help="stop and save after this long")
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--distill", type=float, default=0.5)
    ap.add_argument("--save-every", type=int, default=2000)
    ap.add_argument("--push", help="Hugging Face model repository to upload to")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(args.seed)
    cfg = SsepConfig()
    net = SsepNet(cfg).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=0.01)
    amp = device == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=amp)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ckpt = out / "ckpt.pt"
    step = 0
    if ckpt.is_file():
        state = torch.load(ckpt, map_location=device)
        net.load_state_dict(state["model"])
        opt.load_state_dict(state["opt"])
        scaler.load_state_dict(state["scaler"])
        step = int(state["step"])
        print(f"resumed at step {step}", flush=True)
    musdb = list_tracks(args.musdb, args.teacher)
    extra = list_tracks(args.extra) if args.extra else []
    print(f"{len(musdb)} MUSDB tracks, {len(extra)} extra tracks, "
          f"{count_parameters(net)} parameters, device {device}", flush=True)
    aug = Augment(seed=args.seed + step)
    started = time.time()
    log = open(out / "train_log.jsonl", "a", encoding="utf-8")

    def save() -> None:
        torch.save({"model": net.state_dict(), "opt": opt.state_dict(),
                    "scaler": scaler.state_dict(), "step": step, "config": cfg.to_json()},
                   ckpt.with_suffix(".tmp"))
        ckpt.with_suffix(".tmp").replace(ckpt)

    net.train()
    while step < args.steps:
        use_extra = extra and aug.rng.random() < 0.3
        mix, ref, teach = batch(aug, extra if use_extra else musdb, args.batch, cfg.segment_s,
                                cfg.sample_rate, device)
        if use_extra:  # the "stems" of extra music are the teacher's
            teach, ref = ref, None
        for g in opt.param_groups:
            g["lr"] = lr_at(step, args.steps, args.lr)
        with torch.autocast(device_type=device, dtype=torch.float16, enabled=amp):
            est = separate_tensor(net, mix)
        loss = separation_loss(est.float(), ref, teach, distill=args.distill)
        opt.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        scaler.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0)
        scaler.step(opt)
        scaler.update()
        step += 1
        if step % 100 == 0:
            with torch.no_grad():
                target = ref if ref is not None else teach
                sdr = sdr_db(est.float(), target).tolist()
            hours = round((time.time() - started) / 3600, 3)
            rec = {"step": step, "loss": round(float(loss), 4), "sdr": [round(v, 2) for v in sdr],
                   "lr": opt.param_groups[0]["lr"], "hours": hours}
            log.write(json.dumps(rec) + "\n")
            log.flush()
            print(rec, flush=True)
        if step % args.save_every == 0:
            save()
        if time.time() - started > args.hours * 3600:
            print("time budget reached", flush=True)
            break
    save()
    export_onnx(net.cpu(), out, training={"steps": step, "musdb_tracks": len(musdb),
                                          "extra_tracks": len(extra), "distill": args.distill},
                fp16=True)
    if args.push:
        push(out, args.push)
        print(f"pushed to {args.push}", flush=True)


if __name__ == "__main__":
    main()
