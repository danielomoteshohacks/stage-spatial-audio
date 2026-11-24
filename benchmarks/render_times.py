"""Measure v1 and v2 render times through the whole pipeline on a generated 30 s song.

Usage:
    python benchmarks/render_times.py [--seconds 30] [--repeat 2]

Each configuration runs in this process with cold caches first (the room responses are built on
first use) and then warm; separation is replaced by the song's true stems, so "stems" times are
the render alone and the separator's own time is reported by its model card. The machine is
printed with the numbers, because they depend on it.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import tempfile
import time
from pathlib import Path

import soundfile as sf

from stage.pipeline import run
from stage.separation.demucs_sep import Separation, residual_snr_db
from stage.testsongs import make_song

CONFIGS = (("v1 Lite (max)", "lite", "max"), ("v2 Lite (studio)", "lite", "space:studio"),
           ("v2 stems scene (living room)", "stems", "space:living_room"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--repeat", type=int, default=2)
    args = ap.parse_args()
    song = make_song(seed=1)
    sr = song.sample_rate
    a, b = int(20 * sr), int((20 + args.seconds) * sr)
    stems = {k: v[:, a:b] for k, v in song.stems.items()}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "song.wav"
        sf.write(str(path), song.mix[:, a:b].T, sr, subtype="FLOAT")

        def truth(audio, rate):
            return Separation(stems=stems, sample_rate=rate,
                              residual_snr_db=residual_snr_db(audio, stems), model="truth")

        rows = []
        for label, mode, profile in CONFIGS:
            for i in range(args.repeat):
                t0 = time.perf_counter()
                res = run(path, mode=mode, profile=profile, start=0.0, seconds=args.seconds,
                          out_dir=Path(tmp) / f"o{i}", separator=truth, genre="afrobeats",
                          tag_genre=False)
                wall = time.perf_counter() - t0
                stages = {s.name: round(s.duration_s, 2) for s in res.stages}
                rows.append({"config": label, "run": "cold" if i == 0 else "warm",
                             "wall_s": round(wall, 2), "stages": stages,
                             "verdict": res.report.get("guard", {}).get("verdict")})
                print(json.dumps(rows[-1]), flush=True)
    print(f"\nmachine: {platform.processor() or platform.machine()}, {os.cpu_count()} CPUs, "
          f"Python {platform.python_version()}; {args.seconds:.0f} s at {sr} Hz")
    print("| Configuration | Run | Render (s) | Whole pipeline (s) | Guard |")
    print("|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['config']} | {r['run']} | {r['stages']['render']} | {r['wall_s']} | "
              f"{r['verdict']} |")


if __name__ == "__main__":
    main()
